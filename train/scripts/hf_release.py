"""Stage, upload and link the PillProof MLC builds on Hugging Face (see docs/release.md).

Ships the per-size defaults in app/models.json (r1-ft, lite-r1-ft) as public model repos
<user>/PillProof-Qwen3.5-{2B,0.8B}-<round>-q4f16_1-MLC. Each repo holds the q4f16_1 MLC weights,
the WebGPU model library it was tested with, the Qwen LICENSE and a model card (README.md).

    PY=~/waicy-work/envs/mlx/bin/python
    $PY train/scripts/hf_release.py stage  [--user U]   # ~/waicy-work/release/<repo>/ (APFS clones)
    $PY train/scripts/hf_release.py upload --user U     # refuses unless the HF login is U (not jmamitha)
    $PY train/scripts/app_models.py --hf-user U         # adds hf_repo / model_url / model_lib_url
"""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORK = Path("~/waicy-work").expanduser()
MLC, LIBS, RELEASE = WORK / "models" / "mlc", WORK / "models" / "libs", WORK / "release"
EVAL = Path(os.environ.get("EVAL_DIR", WORK / "eval_r2"))
BLOCKED_USERS = {"jmamitha"}  # the current personal login; the release goes to a different account
WEBLLM = "0.2.88"


def repo_name(size: str, rnd: str) -> str:
    return f"PillProof-Qwen3.5-{size}-{rnd}-q4f16_1-MLC"


def wasm_name(size: str) -> str:
    return f"Qwen3.5-{size}-q4f16_1_cs1k-webgpu.wasm"


def shipped() -> list[tuple[str, dict]]:
    doc = json.loads((REPO / "app" / "models.json").read_text())
    return [(doc["default"][s], doc["models"][doc["default"][s]]) for s in ("2B", "0.8B")]


def ci(run: str):
    f = EVAL / f"{run}.grade.json"
    return json.loads(f.read_text())["checks"].get("wrong_rate_ci") if f.exists() else None


def base_metrics(size: str):
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    os.environ.setdefault("EVAL_DIR", str(EVAL))
    from app_models import scores
    return scores(f"{'B2b' if size == '2B' else 'B08'}_phone")


SYSTEM = (
    "You answer questions about a medicine using only the numbered sentences from its FDA label. "
    "If the sentences answer the question, reply in two lines:\n"
    "SENTENCES: <numbers of the sentences that answer it, separated by commas>\n"
    "ANSWER: <a short, plain restatement that uses only facts from those sentences>\n"
    "If the sentences do not answer the question, reply with exactly:\n"
    "NOT IN LABEL"
)


def card(user: str, key: str, m: dict) -> str:
    size, rnd = m["size"], m["round"]
    name = repo_name(size, rnd)
    p = m["dev"]["phone"]
    o = m["dev"].get("oracle")
    c = ci(f"{'C2b' if size == '2B' else 'C08'}_{rnd}_phone")
    b = base_metrics(size)
    ci_s = f" (95% CI {100 * c[0]:.1f}–{100 * c[1]:.1f}, bootstrap over labels)" if c else ""
    other = "0.8B" if size == "2B" else "2B"
    role = ("the primary PillProof model" if size == "2B"
            else "the lite PillProof model, for phones that cannot run the 2B (tested target: iPhone 17e)")
    flip = (" Example: on an atorvastatin label, \"Can I drink grapefruit juice?\" is answered correctly by the\n"
            "  full-precision 2B but declined (`NOT IN LABEL`) by this 4-bit build." if size == "2B" else "")
    base_note = ("\nThe base 0.8B's low wrong-answer rate comes from declining almost every question; it is not a usable "
                 "baseline." if size == "0.8B" else "")
    base_row = (f"| Base Qwen3.5-{size} + same label sentences (no fine-tune) | {b['wrong_rate']} | "
                f"{b['answerable_correct']} | {b['false_decline_rate']} | {b['false_answer_rate']} |\n") if b else ""
    oracle = (f"\nWith the gold passages in the prompt instead of retrieval (\"oracle\"), the wrong-answer rate is "
              f"{o['wrong_rate']}% and {o['answerable_correct']}% of answerable questions are answered correctly.\n") if o else ""
    return f"""---
license: apache-2.0
base_model: Qwen/Qwen3.5-{size}
library_name: mlc-llm
pipeline_tag: text-generation
language:
- en
tags:
- mlc-llm
- web-llm
- webgpu
- medication
- fda-label
- grounded-qa
- pillproof
---

# {name}

{role[0].upper() + role[1:]}: Qwen3.5-{size} fine-tuned with LoRA (round {rnd}) to answer questions about a medicine
**only from numbered sentences of its FDA label**, then merged and quantized to MLC `q4f16_1` so it runs
fully in the browser with [WebLLM](https://github.com/mlc-ai/web-llm) (WebGPU). Built for PillProof, a
WAICY 2026 high-school AI Showcase entry.

> **Not medical advice.** This is a student research demo. It can be wrong, and it is not a substitute
> for a pharmacist, doctor or the full label. Always read the quoted label sentences yourself.

## Intended use

- Label-grounded answers in the PillProof demo app: the app retrieves sentences from the drug's FDA label,
  the model replies with the numbers of the sentences that answer the question plus a short plain
  restatement, and the app's checks verify the numbers, show the quoted sentences, and block restatements
  whose numbers, units, drug names or warnings are not in the cited sentences.
- Out of scope: open-ended medical chat, diagnosis, dosing decisions, anything without label sentences in the
  prompt. Outside its prompt format the model behaves like a small general model and is not reliable.

## Prompt format

System prompt (exact, used in training):

```text
{SYSTEM}
```

User message:

```text
Drug: FESOTERODINE FUMARATE

Label sentences:
[Section: 2.2 Recommended Dosage ...]
[1] ...
[2] The recommended dosage of fesoterodine fumarate extended-release tablets is 4 mg orally once daily.

Question: What is the recommended dosage ...?
```

Reply: `SENTENCES: 2` and `ANSWER: The recommended dose is 4 mg by mouth once a day.` on two lines,
or exactly `NOT IN LABEL`. Thinking is off (`enable_thinking: false`). Keep the prompt within the phone
budget used in evaluation (about 600 tokens of label sentences, context 2048).

## Usage (WebLLM {WEBLLM})

```js
import * as webllm from "https://esm.run/@mlc-ai/web-llm@{WEBLLM}";
// SYSTEM = the system prompt above; prompt = the user message in the format above

const repo = "https://huggingface.co/{user}/{name}";
const base = webllm.prebuiltAppConfig.model_list.find((r) => r.model_id === "Qwen3.5-{size}-q4f16_1-MLC");
const rec = {{
  ...structuredClone(base),
  model: repo,                                                // WebLLM appends resolve/main/
  model_id: "{name}",
  model_lib: `${{repo}}/resolve/main/{wasm_name(size)}`,
  overrides: {{ ...base.overrides, context_window_size: 2048 }},
}};
const engine = await webllm.CreateMLCEngine(rec.model_id, {{
  appConfig: {{ ...webllm.prebuiltAppConfig, model_list: [rec] }},
}});
const r = await engine.chat.completions.create({{
  messages: [{{ role: "system", content: SYSTEM }}, {{ role: "user", content: prompt }}],
  temperature: 0, max_tokens: 256, extra_body: {{ enable_thinking: false }},
}});
```

The model library (`{wasm_name(size)}`) is the unmodified WebLLM v0_2_87 prebuilt library for the base
model (Apache-2.0); fine-tuning changed only the weights. Size: {"1.0 GB" if size == "2B" else "426 MB"} of weights.

## Training

- Base: [Qwen/Qwen3.5-{size}](https://huggingface.co/Qwen/Qwen3.5-{size}) (Apache-2.0).
- Method: LoRA with MLX-LM (rank 16, scale 20, dropout 0.05, LR 5e-5 cosine, 1 epoch, batch 4, prompt
  masked, thinking off), merged into the base weights, converted with MLC-LLM to `q4f16_1`.
- Data: 7,577 training examples built from [FDARxBench](https://github.com/xiongbetty/FDARxBench)
  (Apache-2.0) question-answer pairs over FDA drug labels (public domain). Whole active ingredients are held
  out for development and test. About 30% of examples are "NOT IN LABEL" items, made by removing the label
  passages that contain the answer.
- **AI-written training text (disclosure).** The ANSWER lines of the training targets were rewritten into
  plain language by Claude Sonnet 5.5 (Anthropic), under automatic checks that every number, unit and drug
  name still appears in the cited label sentences. FDARxBench's own question-answer pairs were generated
  with GPT-4o-mini by its authors. No evaluation data was rewritten.

## Evaluation (development split only)

1,193 dev items from held-out drug labels (whole active ingredients unseen in training), with phone-budget retrieval (BM25 + bge-small-en-v1.5 embeddings,
about 600 tokens of sentences). Greedy decoding, with the app's checks applied. Percentages:

| System | Wrong answers | Answerable answered correctly | Declined, should answer | Answered, should decline |
|---|---|---|---|---|
| **This model** | **{p['wrong_rate']}**{ci_s} | {p['answerable_correct']} | {p['false_decline_rate']} | {p['false_answer_rate']} |
{base_row}{oracle}
"Wrong" counts wrong sentence choices, answers to questions that should be declined, and unparseable replies;
declining an answerable question is counted separately ("Declined, should answer").{base_note}
These are development numbers: checkpoint and retrieval settings were chosen on this split, so they are
slightly optimistic. The one-time held-out test evaluation is reported separately in the project write-up.
In a 100-prompt check, this 4-bit browser build gave the same graded outcome as the full-precision MLX
model on {"98" if size == "2B" else "94"} items.

## Known limitations

- **Over-declining.** It says `NOT IN LABEL` for {p['false_decline_rate']}% of answerable questions, and the
  training "NOT IN LABEL" items are noisy: a single-grader human check found 19 of 20 sampled decline items not clean
  (mostly partly answerable from elsewhere in the label). Two retraining rounds that cleaned the declines (r2, r3) did
  not lower the wrong-answer rate, so this round ({rnd}) ships.
- **4-bit flips.** Quantization changes the outcome on a few items per hundred.{flip}
- **Restatements can drop meaning.** The checks block made-up numbers, units, names and dropped warnings,
  not every change in meaning. The app always shows the quoted label sentences.
- **Single-grader audits.** The decline and training audits were each done by one grader (the round 1 and 2
  decline audits unblinded). Blind pharmacist grading is part of the final evaluation, not this card.
- Not measured here: speed and memory on phones (Mac Chrome: {"57" if size == "2B" else "74"} tok/s decode).
- {"Lite alternative for small phones" if size == "2B" else "Primary model, for devices that can run it"}: `{repo_name(other, rnd)}`.

## License and attribution

Apache-2.0, following the Qwen3.5 base model (LICENSE included). Training data: FDARxBench (Apache-2.0;
Xiong et al., arXiv:2603.19539) and FDA drug labels (public domain, via DailyMed/openFDA).
"""


def stage(a):
    RELEASE.mkdir(parents=True, exist_ok=True)
    for key, m in shipped():
        name = repo_name(m["size"], m["round"])
        dst = RELEASE / name
        if dst.exists():
            shutil.rmtree(dst)
        subprocess.run(["cp", "-cR", str(MLC / m["mlc_dir"]), str(dst)], check=True)  # APFS clone, no extra space
        subprocess.run(["cp", "-c", str(LIBS / wasm_name(m["size"])), str(dst)], check=True)
        shutil.copy(WORK / "models" / f"Qwen3.5-{m['size']}" / "LICENSE", dst / "LICENSE")
        (dst / "README.md").write_text(card(a.user or "<user>", key, m))
        print(key, "->", dst, sum(f.stat().st_size for f in dst.iterdir()) // 2**20, "MB")


def upload(a):
    from huggingface_hub import HfApi
    api = HfApi()
    who = api.whoami()["name"]
    if who in BLOCKED_USERS or who != a.user:
        raise SystemExit(f"HF login is {who!r}; log in as {a.user!r} (not {sorted(BLOCKED_USERS)}) first")
    for key, m in shipped():
        name = repo_name(m["size"], m["round"])
        src = RELEASE / name
        readme = (src / "README.md").read_text()
        if "<user>" in readme:
            (src / "README.md").write_text(card(a.user, key, m))
        rid = f"{a.user}/{name}"
        api.create_repo(rid, repo_type="model", private=False, exist_ok=True)
        api.upload_folder(repo_id=rid, folder_path=str(src), commit_message=f"PillProof {key} ({m['mlc_dir']})")
        print("uploaded", f"https://huggingface.co/{rid}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["stage", "upload"])
    ap.add_argument("--user")
    a = ap.parse_args()
    if a.cmd == "upload" and not a.user:
        ap.error("upload needs --user")
    {"stage": stage, "upload": upload}[a.cmd](a)


if __name__ == "__main__":
    main()
