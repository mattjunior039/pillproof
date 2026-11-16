"""Rewrite train/valid ANSWER lines in plain language with a large model (disclosed).

Only answerable rows of train and valid are rewritten; T1 (test.jsonl), T2 and T3 never are.
SENTENCES numbers are never changed. A rewrite is accepted only if it passes:
  1. the app's number check: every number, unit and drug name in it appears in the cited
     sentences or the drug line (text.restatement_problems);
  2. preservation: every number, unit and drug name in the original line is still present;
  3. no added advice (doctor/pharmacist/emergency etc. not in the cited sentences);
  4. format: one non-empty line.
A failed rewrite is retried once with the problems listed; if it fails again the original
line is kept. Rows whose original line already fails check 1 (about 1%, e.g. a drug class
named only in the reference answer) are skipped and kept as they are. Responses are cached, so re-runs are free and resumable.

Usage (from datapipe/):
  python -m medlabel_data.fdarx.rewrite --sample 50   # pilot: cost, pass rate, side-by-side sheet
  python -m medlabel_data.fdarx.rewrite --all         # every train/valid answerable row
  python -m medlabel_data.fdarx.rewrite --write       # BUILD/fdarx/mlx_plain/{train,valid,test}.jsonl

The API key is read from ANTHROPIC_API_KEY or ~/waicy-work/.env and is never written anywhere.
"""

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import statistics
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import textstat

from .. import paths, text
from .build import OUT_DIR as MLX

MODEL = "claude-sonnet-5-5"
PRICE_IN, PRICE_OUT = 2.0, 10.0  # USD per million tokens (Anthropic list price, Nov 2026)
PROMPT_VERSION = "v2"
OUT = paths.BUILD / "fdarx" / "rewrite"
CACHE = OUT / "cache.jsonl"
PLAIN = paths.BUILD / "fdarx" / "mlx_plain"
SPLITS = ("train", "valid")

SYSTEM = """You rewrite short answers about a medicine so an older adult can easily understand them.

Rules:
- Restate only the facts in the original answer, and keep all of them. The label sentences are there only to help you understand the original answer; do not add other facts from them.
- Do not add explanations, background, reasons, advice or warnings that are not in the original answer. Never add things like "talk to your doctor".
- You may swap a hard medical word for everyday words with the same meaning (for example "low blood pressure" for "hypotension"), or put the everyday words first and the medical word after in parentheses.
- Write every number exactly as the original answer writes it (keep "2" as "2" and "two" as "two"), with the same unit (for example "10 mg", "24 hours", "25°C").
- Keep every drug name exactly as written.
- Aim for a 6th to 8th grade reading level: short sentences of about 15 words or fewer, and common words.
- Write on a single line. No lists, line breaks, quotation marks, labels or preamble.

Reply with only the rewritten answer."""

ADVICE = re.compile(r"\b(doctor|physician|pharmacist|nurse|health ?care provider|provider|consult|911|emergency|"
                    r"poison|seek|call)s?\b", re.I)


def _key() -> str:
    k = os.environ.get("ANTHROPIC_API_KEY")
    env = Path("~/waicy-work/.env").expanduser()
    if not k and env.exists():
        for line in env.read_text().splitlines():
            if line.strip().startswith("ANTHROPIC_API_KEY="):
                k = line.split("=", 1)[1].strip().strip("'\"")
    if not k:
        raise SystemExit("No API key: set ANTHROPIC_API_KEY or put ANTHROPIC_API_KEY=... in ~/waicy-work/.env")
    return k


# Single-word label names that are store brands or ordinary words, not drug names.
_NOT_DRUGS = {"allergy", "childrens", "counteract", "dragon", "equaline", "equate", "healthmart", "heather",
              "hy-vee", "julie", "meijer", "sunmark", "topcare", "camila"}


def lexicon() -> set[str]:
    """FDARxBench active ingredients plus single-word brand names (lowercase)."""
    info = json.loads((paths.BUILD / "fdarx" / "label_ingredients.json").read_text())
    lex = set()
    for v in info.values():
        lex.update(i.lower() for i in v["ingredients"])
        name = (v.get("drug_name") or "").lower().strip()
        if re.fullmatch(r"[a-z][a-z-]{3,}", name) and name not in _NOT_DRUGS:
            lex.add(name)
    return {x for x in lex if len(x) >= 4}


_SENT = re.compile(r"^\[(\d+)\] (.*)$", re.M)


def parse_row(row: dict) -> dict:
    user = row["messages"][1]["content"]
    target = row["messages"][2]["content"]
    sent_line, ans_line = target.split("\n", 1)
    nums = [int(n) for n in sent_line.removeprefix("SENTENCES:").split(",")]
    sents = {int(n): s for n, s in _SENT.findall(user)}
    drug = user.split("\n", 1)[0].removeprefix("Drug:").strip()
    return {
        "qid": row["qid"], "drug": drug, "question": row["question"], "sentences_line": sent_line,
        "nums": nums, "cited": [sents[n] for n in nums], "original": ans_line.removeprefix("ANSWER:").strip(),
    }


def user_prompt(p: dict, feedback: list[str] | None = None) -> str:
    cited = "\n".join(f"- {s}" for s in p["cited"])
    msg = (f"Drug: {p['drug']}\nQuestion: {p['question']}\n\nLabel sentences:\n{cited}\n\n"
           f"Original answer: {p['original']}")
    if feedback:
        msg += ("\n\nYour previous rewrite had these problems: " + "; ".join(feedback)
                + ". Fix them and keep every number, unit and drug name from the original answer.")
    return msg


def problems(rewrite: str, p: dict, lex: set[str]) -> list[str]:
    if not rewrite or "\n" in rewrite.strip() or rewrite.upper().startswith(("SENTENCES", "ANSWER")):
        return ["not a single line"]
    source = p["drug"] + "\n" + "\n".join(p["cited"])
    probs = [f"{x} is not in the label sentences" for x in text.restatement_problems(rewrite, source, lex)]
    orig = p["original"]
    probs += [f"missing number {n}" for n in sorted(text.numbers(orig) - text.numbers(rewrite))]
    probs += [f"missing unit {u}" for u in sorted(text.units(orig) - text.units(rewrite))]
    low = rewrite.lower()
    probs += [f"missing drug name {d}" for d in sorted(text.drug_terms(orig, lex)) if d not in low]
    src_low = source.lower() + " " + orig.lower()
    probs += [f"added advice ('{m}')" for m in {m.lower() for m in ADVICE.findall(rewrite)} if m not in src_low]
    if len(rewrite) > 2.5 * len(orig) + 150:
        probs.append("much longer than the original; restate only its facts")
    return probs


class Client:
    def __init__(self):
        import anthropic
        self.api = anthropic.Anthropic(api_key=_key(), max_retries=8)
        self.lock = threading.Lock()
        self.cache = {}
        OUT.mkdir(parents=True, exist_ok=True)
        if CACHE.exists():
            for line in open(CACHE):
                r = json.loads(line)
                self.cache[r["key"]] = r

    def ask(self, prompt: str) -> dict:
        key = hashlib.sha256(f"{MODEL}|{PROMPT_VERSION}|{SYSTEM}|{prompt}".encode()).hexdigest()
        if key in self.cache:
            return {**self.cache[key], "cached": True}
        resp = self.api.messages.create(model=MODEL, max_tokens=400, system=SYSTEM,
                                        messages=[{"role": "user", "content": prompt}])
        out = "".join(b.text for b in resp.content if b.type == "text").strip()
        rec = {"key": key, "text": out, "in": resp.usage.input_tokens, "out": resp.usage.output_tokens}
        with self.lock:
            self.cache[key] = rec
            with open(CACHE, "a") as f:
                f.write(json.dumps(rec) + "\n")
        return {**rec, "cached": False}


def rewrite_one(client: Client, p: dict, lex: set[str]) -> dict:
    usage = {"in": 0, "out": 0}
    if problems(p["original"], p, lex):  # the reference itself fails the app check; no rewrite can pass
        return {"qid": p["qid"], "status": "skipped_original_fails_check", "plain": None, "attempts": [],
                "new_usage": usage}
    feedback = None
    attempts = []
    for attempt in (1, 2):
        r = client.ask(user_prompt(p, feedback))
        if not r["cached"]:
            usage["in"] += r["in"]
            usage["out"] += r["out"]
        cand = re.sub(r"\s+", " ", r["text"]).strip()
        probs = problems(r["text"].strip(), p, lex)
        attempts.append({"text": cand, "problems": probs, "tokens_in": r["in"], "tokens_out": r["out"]})
        if not probs:
            return {"qid": p["qid"], "status": f"pass_try{attempt}", "plain": cand, "attempts": attempts,
                    "new_usage": usage}
        feedback = probs
    return {"qid": p["qid"], "status": "kept_original", "plain": None, "attempts": attempts, "new_usage": usage}


def load_rows(split: str) -> list[dict]:
    return [r for r in map(json.loads, open(MLX / f"{split}_meta.jsonl")) if r["kind"] == "answerable"]


def run(rows: list[tuple[str, dict]], tag: str, workers: int) -> dict:
    lex = lexicon()
    client = Client()
    parsed = [(sp, parse_row(r)) for sp, r in rows]
    with ThreadPoolExecutor(workers) as ex:
        results = list(ex.map(lambda x: rewrite_one(client, x[1], lex), parsed))
    by_status = {}
    for r in results:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    all_tokens_in = sum(a["tokens_in"] for r in results for a in r["attempts"])
    all_tokens_out = sum(a["tokens_out"] for r in results for a in r["attempts"])
    cost = (all_tokens_in * PRICE_IN + all_tokens_out * PRICE_OUT) / 1e6
    passed = [(p, r) for (_, p), r in zip(parsed, results) if r["plain"]]
    fk = lambda s: textstat.flesch_kincaid_grade(s)
    report = {
        "model": MODEL, "prompt_version": PROMPT_VERSION, "rows": len(results), "by_status": by_status,
        "pass_rate": round(len(passed) / max(len(results), 1), 3),
        "tokens_in": all_tokens_in, "tokens_out": all_tokens_out, "cost_usd": round(cost, 2),
        "cost_usd_this_invocation": round(sum(r["new_usage"]["in"] * PRICE_IN + r["new_usage"]["out"] * PRICE_OUT
                                              for r in results) / 1e6, 2),
        "fk_grade_median_original": round(statistics.median(fk(p["original"]) for p, _ in passed), 1) if passed else None,
        "fk_grade_median_plain": round(statistics.median(fk(r["plain"]) for _, r in passed), 1) if passed else None,
        # medical terms kept in parentheses after the everyday words inflate FK; this drops them
        "fk_grade_median_plain_no_parens": round(statistics.median(
            fk(re.sub(r"\s*\([^)]*\)", "", r["plain"])) for _, r in passed), 1) if passed else None,
        "first_try_problems": _problem_counts(results),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / f"{tag}_results.jsonl", "w") as f:
        for (sp, p), r in zip(parsed, results):
            f.write(json.dumps({"split": sp, **p, **{k: v for k, v in r.items() if k != "new_usage"}},
                               ensure_ascii=False) + "\n")
    (OUT / f"{tag}_report.json").write_text(json.dumps(report, indent=1))
    _sheet(OUT / f"{tag}_side_by_side.md", parsed, results)
    print(json.dumps(report, indent=1))
    return report


def _problem_counts(results: list[dict]) -> dict:
    c = {}
    for r in results:
        for pr in (r["attempts"][0]["problems"] if r["attempts"] else []):
            k = re.sub(r" [^ ]+$", "", pr) if not pr.startswith("added") else "added advice"
            k = re.sub(r"^(number|unit|drug) .* is not", r"\1 is not", k)
            c[k] = c.get(k, 0) + 1
    return dict(sorted(c.items(), key=lambda x: -x[1]))


def _sheet(path: Path, parsed, results) -> None:
    lines = ["# Plain-language rewrite: original vs rewrite", ""]
    for i, ((sp, p), r) in enumerate(zip(parsed, results), 1):
        lines += [f"## {i}. {p['drug']} ({sp}, {r['status']})", "", f"**Q:** {p['question']}", "",
                  "**Cited sentences:**", *[f"- {s}" for s in p["cited"]], "",
                  f"**Original:** {p['original']}", "",
                  f"**Plain:** {r['plain'] or '(kept original)'}"]
        for k, a in enumerate(r["attempts"], 1):
            if a["problems"]:
                lines.append(f"\n_Try {k} rejected ({'; '.join(a['problems'])}):_ {a['text']}")
        lines.append("")
    path.write_text("\n".join(lines))


def write() -> None:
    res = {}
    for line in open(OUT / "all_results.jsonl"):
        r = json.loads(line)
        res[r["qid"]] = r
    PLAIN.mkdir(parents=True, exist_ok=True)
    stats = {}
    for sp in SPLITS:
        n = {"rewritten": 0, "kept_original": 0, "not_answerable": 0}
        with open(PLAIN / f"{sp}.jsonl", "w") as fo, open(PLAIN / f"{sp}_meta.jsonl", "w") as fm:
            for row in map(json.loads, open(MLX / f"{sp}_meta.jsonl")):
                if row["kind"] == "answerable":
                    r = res[row["qid"]]
                    sent_line, ans_line = row["messages"][2]["content"].split("\n", 1)
                    row["answer_original"] = ans_line.removeprefix("ANSWER:").strip()
                    row["answer_plain"] = r["plain"]
                    row["rewrite_status"] = r["status"]
                    if r["plain"]:
                        row["messages"][2]["content"] = f"{sent_line}\nANSWER: {r['plain']}"
                        n["rewritten"] += 1
                    else:
                        n["kept_original"] += 1
                else:
                    n["not_answerable"] += 1
                fo.write(json.dumps({"messages": row["messages"]}, ensure_ascii=False) + "\n")
                fm.write(json.dumps(row, ensure_ascii=False) + "\n")
        stats[sp] = n
    for f in ("test.jsonl", "test_meta.jsonl"):  # T1 is never rewritten
        shutil.copy(MLX / f, PLAIN / f)
    (PLAIN / "write_report.json").write_text(json.dumps(stats, indent=1))
    print(json.dumps(stats, indent=1))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--sample", type=int)
    g.add_argument("--all", action="store_true")
    g.add_argument("--write", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args(argv)
    if a.write:
        return write()
    rows = [(sp, r) for sp in SPLITS for r in load_rows(sp)]
    if a.sample:
        rows = random.Random(a.seed).sample([x for x in rows if x[0] == "train"], a.sample)
        rep = run(rows, f"sample{a.sample}", a.workers)
        total = sum(1 for sp in SPLITS for _ in load_rows(sp))
        est = rep["cost_usd"] / max(rep["rows"], 1) * total
        print(f"Estimated full run: {total} rows, about ${est:.2f}")
    else:
        run(rows, "all", a.workers)


if __name__ == "__main__":
    main()
