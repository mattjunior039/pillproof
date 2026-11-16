"""Draw a 100-item random audit sample from the training file for hand checking.

Writes BUILD/fdarx/audit/ (copy it anywhere to fill in):
  audit_100.md   one block per item: question, the sentences the target cites (or, for
                 declines, every sentence shown), the target output, and the original
                 FDARxBench reference answer
  audit_100.csv  same ids with empty columns to fill in:
                 verdict = ok | wrong_sentences | wrong_answer | should_decline |
                           should_answer | bad_question
                 notes = free text
The proportion of answerable to decline items follows the training file.
"""

import csv
import json
import random
import re

from .. import paths
from .build import OUT_DIR

AUDIT_DIR = paths.BUILD / "fdarx" / "audit"
N = 100
SEED = 100


def _sentences(user: str) -> dict[int, str]:
    return {int(m.group(1)): m.group(2) for m in re.finditer(r"^\[(\d+)\] (.*)$", user, re.M)}


def main() -> None:
    rows = [json.loads(l) for l in open(OUT_DIR / "train_meta.jsonl")]
    sample = random.Random(SEED).sample(rows, N)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    md = ["# FDARxBench training audit (100 random items)", "",
          "For each item, decide whether the target output is right **given only the sentences shown**.",
          "Record a verdict in `audit_100.csv`: `ok`, `wrong_sentences` (cited sentences do not support the",
          "answer or miss part of it), `wrong_answer` (restatement adds or changes facts),",
          "`should_decline` (shown sentences do not answer it), `should_answer` (a decline item whose",
          "sentences do answer it), or `bad_question` (question/answer mismatch or nonsense).", ""]
    with open(AUDIT_DIR / "audit_100.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["n", "qid", "kind", "task", "drug", "question", "target", "verdict", "notes"])
        for i, r in enumerate(sample, 1):
            user, target = r["messages"][1]["content"], r["messages"][2]["content"]
            sents = _sentences(user)
            w.writerow([i, r["qid"], r["kind"], r["task"], r["drug_name"], r["question"], target, "", ""])
            md += [f"## {i}. {r['drug_name']} — {r['kind']} ({r['task']}, {r['qid']})", "",
                   f"**Question:** {r['question']}", ""]
            if r["kind"] == "answerable":
                md.append("**Cited sentences:**")
                md += [f"- [{n}] {sents[n]}" for n in r["answer_sentences"]]
                md += ["", "**Target:**", "", "```", target, "```", "",
                       f"**FDARxBench reference:** {r['reference_answer']}", "",
                       "<details><summary>All sentences shown to the model</summary>", "", "```", user, "```",
                       "", "</details>", ""]
            else:
                md += ["**Target:** `NOT IN LABEL`", "",
                       f"**Answer that was removed:** {r['reference_answer']}", "",
                       "**Sentences shown (should not contain the answer):**", "", "```", user, "```", ""]
    (AUDIT_DIR / "audit_100.md").write_text("\n".join(md))
    kinds = {k: sum(r["kind"] == k for r in sample) for k in ("answerable", "decline")}
    print(AUDIT_DIR, kinds)


if __name__ == "__main__":
    main()
