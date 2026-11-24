"""Write app/models.json: the fine-tuned builds per size, their dev metrics, and the default per size.

Rule (docs/gate2.md, round 3): per size, the default is the round with the lowest dev wrong-answer rate
on phone prompts (the shipped app setting), with checks applied. A tie (same number of wrong items)
is broken by the lower "declined, should answer" rate. All rounds are scored on the same r2 dev
prompts in EVAL_DIR (default ~/waicy-work/eval_r2). Metrics are percentages.

Usage (repo root):  ~/waicy-work/envs/mlx/bin/python train/scripts/app_models.py [--out app/models.json] [--hf-user U]

--hf-user U adds the Hugging Face location of the released builds (the per-size defaults, uploaded by
hf_release.py): hf_repo, model_url (WebLLM "model", it appends resolve/main/) and model_lib_url (the
WebGPU library in the same repo). Without it, HF fields already in the output file are kept.
"""

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("EVAL_DIR", str(Path("~/waicy-work/eval_r2").expanduser()))
from compare_dev import EVAL, load, metric  # noqa: E402

ROUNDS = {  # round -> run-name infix in EVAL_DIR (r2 runs have none)
    "r1": "_r1", "r2": "", "r3": "_r3"}
SIZES = {"2B": ("C2b", "", ("phone", "oracle", "desktop")), "0.8B": ("C08", "lite-", ("phone", "oracle"))}
KEYS = ("wrong_rate", "overall_correct", "answerable_correct", "false_decline_rate", "false_answer_rate",
        "miss_decline", "select_ok")


def scores(run: str):
    if not (EVAL / f"{run}.graded.jsonl").exists():
        return None
    rows = list(load(run).values())
    m = {k: round(100 * v, 1) for k in KEYS if (v := metric(rows, "checks", k)) is not None}
    m["n"] = len(rows)
    m["n_wrong"] = sum(r["checks"] in ("wrong", "wrong_answered", "invalid") for r in rows)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="app/models.json")
    ap.add_argument("--hf-user")
    a = ap.parse_args()
    old = json.loads(Path(a.out).read_text())["models"] if Path(a.out).exists() else {}
    models, default = {}, {}
    for size, (prefix, kp, prompt_sets) in SIZES.items():
        cands = []
        for rnd, infix in ROUNDS.items():
            key = f"{kp}{rnd}-ft"
            dev = {p: s for p in prompt_sets if (s := scores(f"{prefix}{infix}_{p}"))}
            models[key] = {"size": size, "round": rnd,
                           "mlc_dir": f"Qwen3.5-{size}-medlabel-{rnd}-q4f16_1-MLC", "dev": dev}
            if "phone" in dev:
                cands.append((dev["phone"]["n_wrong"], dev["phone"]["false_decline_rate"], rnd, key))
        default[size] = min(cands)[3]
    for key, m in models.items():
        if a.hf_user and key in default.values():
            from hf_release import repo_name, wasm_name
            repo = f"https://huggingface.co/{a.hf_user}/{repo_name(m['size'], m['round'])}"
            m.update(hf_repo=repo.split("huggingface.co/")[1], model_url=repo,
                     model_lib_url=f"{repo}/resolve/main/{wasm_name(m['size'])}")
        elif not a.hf_user:
            m.update({k: v for k, v in old.get(key, {}).items() if k in ("hf_repo", "model_url", "model_lib_url")})
    doc = {
        "default": default,
        "models": models,
        "selection": "per size: lowest dev wrong-answer rate on phone prompts with checks; ties broken by "
                     "lower 'declined, should answer' (false_decline_rate). See docs/gate2.md.",
        "mlc_root": "~/waicy-work/models/mlc",
        "metrics": "percent, with checks, on the r2 dev prompts (EVAL_DIR=~/waicy-work/eval_r2)",
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(doc, indent=1) + "\n")
    print(json.dumps({"default": default, **{k: v["dev"].get("phone", {}).get("wrong_rate") for k, v in models.items()}}))


if __name__ == "__main__":
    main()
