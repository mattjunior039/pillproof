"""Model-judging harness for label-change pairs (plan section 7, T5).

The model sees an old and a new sentence and answers with a label ("meaning changed" or
"reworded") plus one plain sentence. The explanation goes through the app's number check
(numbers, units and drug names must appear in the old or new sentence) and an advice check
(a change is never phrased as a reason to stop or change a medicine). An explanation that
fails either check is dropped; the label is kept.

T5 is blind: this harness refuses to score T5 until every row of the user's sheet carries a
mark, so no model output can be seen before the marks exist. The text-similarity baseline is
scored on the same items for comparison.

Run (Gate 1 MLX environment; GPU, so only when no other job is using it):

    PYTHONPATH=datapipe/src ~/waicy-work/envs/mlx/bin/python -m medlabel_data.changes.judge \
        --model ~/waicy-work/models/Qwen3.5-2B [--adapter-path ~/waicy-work/models/adapters/X] \
        [--name base-2b]

    --split dev        run on the development sample instead (datapipe/eval/changes_dev_marks.csv)
    --dry-run          print prompts for the first items, load no model
    --backend mock     deterministic stand-in model, for tests
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from ..paths import BUILD, CONFIG, REPO
from ..text import restatement_problems
from .baseline import THETA, baseline_label

OUT = BUILD / "changes"
T5_DIR = OUT / "t5"
JUDGE_DIR = OUT / "judge"
DEV_CSV = REPO / "datapipe" / "eval" / "changes_dev_marks.csv"

LABELS = ("meaning changed", "reworded")
SAFETY_NOTE = "Ask your pharmacist or doctor before changing anything."

SYSTEM = (
    "You compare two versions of a sentence from a U.S. prescription drug label. "
    "Decide whether the safety meaning changed, or whether the sentence was only reworded "
    "or reformatted with the same meaning. Then write one plain sentence, readable by a "
    "high-school student, that says what changed in the label. Use only facts from the two "
    "sentences. Do not give advice and do not tell anyone to start, stop or change a medicine."
)

FORMAT = (
    "Answer in exactly two lines:\n"
    "LABEL: meaning changed  OR  LABEL: reworded\n"
    "EXPLANATION: one plain sentence starting with \"The label\""
)

_ADVICE = re.compile(
    r"\b(you should|you must|you need to|stop (taking|using|your)|do not take|don't take|"
    r"quit|discontinue|switch to|ask your|talk to your|call your|consult)\b", re.I)
_THINK = re.compile(r"<think>.*?(</think>|$)", re.S)
_LABEL = re.compile(r"LABEL\s*:\s*\**\s*(meaning\s+changed|reworded)", re.I)
_EXPL = re.compile(r"EXPLANATION\s*:\s*(.+)", re.I | re.S)


def lexicon() -> set[str]:
    out = set()
    for d in json.loads((CONFIG / "t3_drugs.json").read_text())["drugs"]:
        out.add(d["ingredient"].lower())
        if d.get("brand"):
            out.add(d["brand"].lower())
    return out


# ---------------------------------------------------------------- items

def norm_mark(m: str) -> str | None:
    m = (m or "").strip().lower()
    if m in ("meaning changed", "meaning", "m", "changed"):
        return "meaning changed"
    if m in ("reworded", "r", "reword", "formatting only", "formatting", "f"):
        return "reworded"
    return None


def load_t5() -> list[dict]:
    """T5 rows joined to their candidates. Refuses unless every row has a valid mark."""
    sheet = list(csv.DictReader(open(T5_DIR / "t5_sheet.csv", newline="")))
    missing = [r["t5_id"] for r in sheet if norm_mark(r.get("mark", "")) is None]
    if missing:
        sys.exit(f"T5 is not fully marked ({len(missing)} of {len(sheet)} rows missing or "
                 f"invalid, e.g. {missing[:5]}). Mark every row 'meaning changed' or "
                 "'reworded' first; the harness will not run before that.")
    key = {k["t5_id"]: k for k in map(json.loads, open(T5_DIR / "t5_key_hidden.jsonl"))}
    cands = {c["id"]: c for c in map(json.loads, open(OUT / "candidates.jsonl"))}
    items = []
    for r in sheet:
        k = key[r["t5_id"]]
        c = cands[k["id"]]
        items.append({**_item(c), "item_id": r["t5_id"], "gold": norm_mark(r["mark"]),
                      "stratum": k["stratum"], "weight": k["weight"]})
    return items


def load_dev() -> list[dict]:
    rows = list(csv.DictReader(open(DEV_CSV, newline="")))
    cands = {c["id"]: c for c in map(json.loads, open(OUT / "candidates.jsonl"))}
    items = []
    for r in rows:
        c = cands.get(r["id"])
        if c is None:
            continue
        items.append({**_item(c), "item_id": r["id"], "gold": norm_mark(r["dev_mark"]),
                      "stratum": c["kind"], "weight": 1.0})
    return items


def _item(c: dict) -> dict:
    return {"id": c["id"], "drug": c["drug"], "section": c.get("section", ""), "kind": c["kind"],
            "old_text": c.get("old_text") or "", "new_text": c.get("new_text") or "",
            "closest_text": c.get("closest_text") or "", "similarity": c["similarity"]}


# ---------------------------------------------------------------- prompt / parse / checks

def build_prompt(it: dict) -> str:
    kind = it["kind"]
    if kind == "added":
        body = ("A sentence was ADDED to the newer label.\n"
                f"NEW: {it['new_text']}\n"
                f"Most similar sentence in the older label: {it['closest_text'] or '(none)'}")
    elif kind == "removed":
        body = ("A sentence was REMOVED from the newer label.\n"
                f"OLD: {it['old_text']}\n"
                f"Most similar sentence in the newer label: {it['closest_text'] or '(none)'}")
    else:
        body = f"OLD: {it['old_text']}\nNEW: {it['new_text']}"
    return f"Label section: {it['section']}\n{body}\n\n{FORMAT}"


def source_text(it: dict) -> str:
    return " ".join([it["old_text"], it["new_text"], it["closest_text"]])


def parse(raw: str) -> tuple[str | None, str]:
    text = _THINK.sub("", raw or "").strip()
    m = _LABEL.search(text)
    label = re.sub(r"\s+", " ", m.group(1).lower()) if m else None
    e = _EXPL.search(text)
    expl = e.group(1).strip().splitlines()[0].strip() if e else ""
    return label, expl


def check_explanation(expl: str, source: str, lex: set[str]) -> list[str]:
    if not expl:
        return ["empty"]
    probs = restatement_problems(expl, source, lex)
    if _ADVICE.search(expl):
        probs.append("advice")
    return probs


def judge_item(it: dict, raw: str, lex: set[str]) -> dict:
    label, expl = parse(raw)
    probs = check_explanation(expl, source_text(it), lex)
    return {
        "item_id": it["item_id"], "id": it["id"], "drug": it["drug"], "stratum": it["stratum"],
        "weight": it["weight"], "gold": it["gold"], "raw": raw,
        "parsed": label is not None,
        # an unparsable answer is treated as "meaning changed": the app would show the change
        "label": label or "meaning changed",
        "explanation": expl if not probs else None,
        "explanation_problems": probs,
        "baseline": baseline_label(it["similarity"]),
        "note": SAFETY_NOTE,
    }


# ---------------------------------------------------------------- backends

class MockBackend:
    """Stand-in for tests: labels by similarity and copies text from the item."""

    def __init__(self, items: list[dict]):
        self.by_prompt = {build_prompt(it): it for it in items}

    def generate(self, prompt: str) -> str:
        it = self.by_prompt[prompt]
        lab = baseline_label(it["similarity"])
        return f"<think></think>LABEL: {lab}\nEXPLANATION: The label now says: {it['new_text'] or it['old_text']}"


class MLXBackend:
    def __init__(self, model: str, adapter_path: str | None, max_tokens: int):
        from mlx_lm import generate, load  # lazy: GPU environment only
        from mlx_lm.sample_utils import make_sampler

        self._generate = generate
        self.model, self.tok = load(model, adapter_path=adapter_path)
        self.sampler = make_sampler(temp=0.0)
        self.max_tokens = max_tokens

    def generate(self, prompt: str) -> str:
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]
        try:
            text = self.tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True,
                                                enable_thinking=False)
        except TypeError:
            text = self.tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        return self._generate(self.model, self.tok, prompt=text, max_tokens=self.max_tokens,
                              sampler=self.sampler, verbose=False)


# ---------------------------------------------------------------- scoring

def confusion(rows: list[dict], field: str) -> dict:
    c = Counter()
    for r in rows:
        g, p = r["gold"] == LABELS[0], r[field] == LABELS[0]
        c["tp" if g and p else "fn" if g else "fp" if p else "tn"] += 1
    return dict(c)


def rates(cm: dict) -> dict:
    tp, fn, fp, tn = (cm.get(k, 0) for k in ("tp", "fn", "fp", "tn"))

    def div(a, b):
        return round(a / b, 3) if b else None

    return {"catch_rate": div(tp, tp + fn), "false_flag_rate": div(fp, fp + tn),
            "accuracy": div(tp + tn, tp + tn + fp + fn), "n": tp + tn + fp + fn}


def weighted_rates(rows: list[dict], field: str) -> dict:
    """Population estimate using the stratum weights of the T5 sample."""
    s = Counter()
    for r in rows:
        g, p = r["gold"] == LABELS[0], r[field] == LABELS[0]
        s["tp" if g and p else "fn" if g else "fp" if p else "tn"] += r["weight"]
    return {k: v for k, v in rates({k: v for k, v in s.items()}).items() if k != "n"}


def drug_bootstrap(rows: list[dict], field: str, n_boot: int = 2000, seed: int = 0) -> dict:
    """95% intervals by resampling drugs (items from one drug are not independent)."""
    by = defaultdict(list)
    for r in rows:
        by[r["drug"]].append(r)
    drugs = sorted(by)
    rng = random.Random(seed)
    stats = defaultdict(list)
    for _ in range(n_boot):
        sample = [r for d in (rng.choice(drugs) for _ in drugs) for r in by[d]]
        for k, v in rates(confusion(sample, field)).items():
            if k != "n" and v is not None:
                stats[k].append(v)
    out = {}
    for k, vs in stats.items():
        vs.sort()
        out[k] = [vs[int(0.025 * len(vs))], vs[int(0.975 * len(vs)) - 1]]
    return out


def score(rows: list[dict]) -> dict:
    out = {}
    for field in ("label", "baseline"):
        cm = confusion(rows, field)
        out[field] = {"confusion": cm, **rates(cm), "ci95_drug_bootstrap": drug_bootstrap(rows, field),
                      "weighted": weighted_rates(rows, field),
                      "by_stratum": {s: rates(confusion([r for r in rows if r["stratum"] == s], field))
                                     for s in sorted({r["stratum"] for r in rows})}}
    out["parse_failures"] = sum(not r["parsed"] for r in rows)
    out["explanations_kept"] = sum(r["explanation"] is not None for r in rows)
    out["explanation_problems"] = dict(Counter(p.split()[0] for r in rows for p in r["explanation_problems"]))
    out["baseline_theta"] = THETA
    return out


# ---------------------------------------------------------------- main

def run(items: list[dict], backend, lex: set[str], log=None) -> list[dict]:
    rows = []
    for i, it in enumerate(items):
        raw = backend.generate(build_prompt(it))
        rows.append(judge_item(it, raw, lex))
        if log:
            log(f"{i + 1}/{len(items)} {it['item_id']} -> {rows[-1]['label']}")
    return rows


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", choices=("t5", "dev"), default="t5")
    ap.add_argument("--model")
    ap.add_argument("--adapter-path")
    ap.add_argument("--name", help="run name for output files")
    ap.add_argument("--backend", choices=("mlx", "mock"), default="mlx")
    ap.add_argument("--max-tokens", type=int, default=160)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out-dir", type=Path, default=JUDGE_DIR)
    a = ap.parse_args(argv)

    items = load_t5() if a.split == "t5" else load_dev()
    if a.limit:
        items = items[: a.limit]
    if a.dry_run:
        print("SYSTEM:", SYSTEM, "\n")
        for it in items[:3]:
            print(build_prompt(it), "\n---")
        print(f"{len(items)} items; no model loaded.")
        return
    if a.backend == "mlx" and not a.model:
        ap.error("--model is required for the mlx backend")
    backend = MockBackend(items) if a.backend == "mock" else MLXBackend(a.model, a.adapter_path, a.max_tokens)
    t0 = time.time()
    rows = run(items, backend, lexicon(), log=lambda s: print(s, file=sys.stderr))
    name = a.name or (Path(a.model).name if a.model else a.backend)
    summary = {"split": a.split, "name": name, "model": a.model, "adapter_path": a.adapter_path,
               "seconds": round(time.time() - t0, 1), **score(rows)}
    a.out_dir.mkdir(parents=True, exist_ok=True)
    with open(a.out_dir / f"{a.split}_{name}.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    (a.out_dir / f"{a.split}_{name}_summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: summary[k] for k in ("label", "baseline")}, indent=1)[:3000])


if __name__ == "__main__":
    main()
