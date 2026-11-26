"""T5 (label-change judge) on the 149 marked pairs, through datapipe's changes.judge harness unchanged.

    ~/waicy-work/envs/mlx/bin/python train/scripts/final/t5_run.py --name base-2b
    ~/waicy-work/envs/mlx/bin/python train/scripts/final/t5_run.py --name tuned-2b --adapter
    python3 train/scripts/final/t5_run.py --score       # needs both runs; writes final/t5/summary.json
judge.load_t5() refuses while any row is unmarked; T5-085 has no mark, so this wrapper builds the same items
for the 149 marked rows (judge._item + norm_mark + the hidden key) and uses judge.run/score as they are.
Primary labels: Reviewer A's marks (mark). Checks: the pharmacist's 30 and Reviewer B's 24 second marks (mark_2).
"""
import argparse
import csv
import json

from common import ADAPTER, BASE, FINAL, drug_boot
from medlabel_data.changes import judge as J

OUT = FINAL / "t5"


def items(col="mark", sheet=J.T5_DIR / "t5_sheet.csv"):
    key = {k["t5_id"]: k for k in map(json.loads, open(J.T5_DIR / "t5_key_hidden.jsonl"))}
    cands = {c["id"]: c for c in map(json.loads, open(J.OUT / "candidates.jsonl"))}
    out = []
    for r in csv.DictReader(open(sheet, newline="")):
        g = J.norm_mark(r.get(col, ""))
        if g is None:
            continue
        k = key[r["t5_id"]]
        out.append({**J._item(cands[k["id"]]), "item_id": r["t5_id"], "gold": g, "stratum": k["stratum"], "weight": k["weight"]})
    return out


def gen(a):
    its = items()
    print(len(its), "marked items")
    be = J.MLXBackend(str(BASE["2b"]), str(ADAPTER["2b"]) if a.adapter else None, 160)
    rows = J.run(its, be, J.lexicon())
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / f"{a.name}.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    import mlx.core as mx
    print(a.name, "peak_gb", round(mx.get_peak_memory() / 1e9, 2))


def score():
    res = {}
    checks = {"reviewer_a": {r["item_id"]: r["gold"] for r in items()},
              "pharmacist": {r["item_id"]: r["gold"] for r in items(sheet=J.T5_DIR / "pharmacist_sheet.csv")},
              "reviewer_b": {r["item_id"]: r["gold"] for r in items(col="mark_2")}}
    runs = {n: [json.loads(l) for l in open(OUT / f"{n}.jsonl")] for n in ("base-2b", "tuned-2b")}
    methods = {"similarity_rule": (runs["base-2b"], "baseline"), "base-2b": (runs["base-2b"], "label"),
               "tuned-2b": (runs["tuned-2b"], "label")}
    for ref, gold in checks.items():
        res[ref] = {}
        for m, (rows, field) in methods.items():
            rs = [{**r, "gold": gold[r["item_id"]]} for r in rows if r["item_id"] in gold]
            cm = J.confusion(rs, field)
            pos = [r for r in rs if r["gold"] == J.LABELS[0]]
            neg = [r for r in rs if r["gold"] != J.LABELS[0]]
            flag = lambda x: x[field] == J.LABELS[0]  # noqa: E731
            res[ref][m] = {"n": len(rs), "n_meaning": len(pos), "n_reworded": len(neg), "confusion": cm,
                           **{k: v for k, v in J.rates(cm).items() if k != "n"},
                           "recall_ci": drug_boot(pos, lambda s: 100 * sum(map(flag, s)) / max(1, len(s))),
                           "false_flag_ci": drug_boot(neg, lambda s: 100 * sum(map(flag, s)) / max(1, len(s)))}
    # human agreement on the overlaps (Reviewer A vs the checks)
    agree = {}
    for ref in ("pharmacist", "reviewer_b"):
        ids = [i for i in checks[ref] if i in checks["reviewer_a"]]
        agree[ref] = {"n": len(ids), "agree": sum(checks[ref][i] == checks["reviewer_a"][i] for i in ids)}
    t = runs["tuned-2b"]
    res["human_agreement_with_reviewer_a"] = agree
    res["tuned_explanations"] = {"kept": sum(r["explanation"] is not None for r in t), "n": len(t),
                                 "parse_failures": sum(not r["parsed"] for r in t)}
    res["base_explanations"] = {"kept": sum(r["explanation"] is not None for r in runs["base-2b"]), "n": len(t)}
    (OUT / "summary.json").write_text(json.dumps(res, indent=1))
    for m in methods:
        a = res["reviewer_a"][m]
        print(f"{m:16s} recall {100*a['catch_rate']:.1f} {a['recall_ci']}  false-flag {100*a['false_flag_rate']:.1f} {a['false_flag_ci']}"
              f"  | pharm recall {res['pharmacist'][m]['catch_rate']} ff {res['pharmacist'][m]['false_flag_rate']}")
    print(agree, res["tuned_explanations"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--name")
    ap.add_argument("--adapter", action="store_true")
    ap.add_argument("--score", action="store_true")
    a = ap.parse_args()
    score() if a.score else gen(a)
