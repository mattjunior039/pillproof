"""Spot-check sheet for decline items that survive the support check (train + valid only).

Writes BUILD/fdarx/audit/:
  decline_check_50.md    one block per item: question, the answer that was removed, the
                         removed section headings, and the closest sentences the support
                         check found in the rest of the label (it found too little to call
                         the answer supported)
  decline_check_50.csv   same items; fill in
                         verdict = not_in_label | answerable_elsewhere | partly | bad_question
                         where_found = section heading(s) if answerable elsewhere
  decline_check_labels/NN_<qid>.txt   the full label with the removed passages marked, for Ctrl-F

Never reads the test split.
"""

import csv
import json
import random

from .. import paths
from .align import OUT as ALIGNED, _labels
from .audit import AUDIT_DIR, PLAIN_DIR
from .rewrite import lexicon
from .support import supported_elsewhere

N = 50
SEED = 50


def main() -> None:
    pool = []
    for name in ("train", "valid"):
        pool += [dict(json.loads(l), split=name) for l in open(PLAIN_DIR / f"{name}_meta.jsonl")
                 if json.loads(l)["kind"] == "decline"]
    sample = random.Random(SEED).sample(pool, N)
    want = {("dev" if r["split"] == "valid" else "train", r["qid"]) for r in sample}
    recs = {}
    for line in open(ALIGNED):
        r = json.loads(line)
        if (r["split"], r["qid"]) in want:
            recs[(r["split"], r["qid"])] = r
    labs, lex = _labels(), lexicon()
    lab_dir = AUDIT_DIR / "decline_check_labels"
    lab_dir.mkdir(parents=True, exist_ok=True)
    md = ["# Decline spot-check (50 random remaining decline items, train + valid)", "",
          "Each item was turned into a decline by removing the label passages that hold its answer.",
          "The support check then found no clear support for the answer in the rest of the label.",
          "Your job: is the question really **not answerable** from the rest of the label?",
          "Open the label file for the item (removed passages are marked) and search it.", "",
          "Verdicts for `decline_check_50.csv`: `not_in_label` (correct decline), `answerable_elsewhere`",
          "(the rest of the label answers it; put the section in `where_found`), `partly` (part of the",
          "answer is there), `bad_question`.", ""]
    with open(AUDIT_DIR / "decline_check_50.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["n", "split", "qid", "drug", "question", "removed_answer", "check_coverage",
                    "label_file", "verdict", "where_found", "notes"])
        for i, r in enumerate(sample, 1):
            sp = "dev" if r["split"] == "valid" else "train"
            rec, lab = recs[(sp, r["qid"])], labs[r["set_id"]]
            removed = set(r["removed"])
            res = supported_elsewhere(rec, lab, removed, lex)
            fname = f"{i:02d}_{r['qid']}.txt"
            body = [f"{lab.drug_name}  (set_id {r['set_id']})", ""]
            for c, (head, sents) in enumerate(lab.passages):
                mark = "  [REMOVED - held the answer]" if c in removed else ""
                body += [f"=== {head or '(no heading)'}{mark}", *sents, ""]
            (lab_dir / fname).write_text("\n".join(body))
            w.writerow([i, r["split"], r["qid"], r["drug_name"], r["question"], r["reference_answer"],
                        res["coverage"], f"decline_check_labels/{fname}", "", "", ""])
            heads = sorted({lab.passages[c][0] or "(no heading)" for c in removed})
            md += [f"## {i}. {r['drug_name']} ({r['split']}, {r['task']}, {r['qid']})", "",
                   f"**Question:** {r['question']}", "",
                   f"**Answer that was removed:** {r['reference_answer']}", "",
                   f"**Removed sections:** {'; '.join(heads)}", "",
                   f"**Closest remaining sentences (check coverage {res['coverage']:.2f}"
                   + (f"; missing: {', '.join(res['key_fact_problems'])}" if res["key_fact_problems"] else "")
                   + "):**"]
            md += [f"- *{lab.passages[c][0] or '(no heading)'}:* {lab.passages[c][1][s]}"
                   for c, s in res["sentences"]] or ["- (none)"]
            md += ["", f"Full label: `decline_check_labels/{fname}`", ""]
    (AUDIT_DIR / "decline_check_50.md").write_text("\n".join(md))
    print(AUDIT_DIR / "decline_check_50.md", {s: sum(r["split"] == s for r in sample) for s in ("train", "valid")})


if __name__ == "__main__":
    main()
