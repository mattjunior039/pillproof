"""Gate-2-style automatic grading of T3 app runs (docs/final-eval.md, "T3 automatic grade").

    python3 train/scripts/final/t3_grade.py        # -> final/grades/t3_auto.json (+ t3_auto_rows.jsonl)

The app builds its own prompt (core/retrieval.js), so the T3 gold sentences (t3_draft.csv
gold_text, written against the full label) are matched to the numbered prompt sentences:
a prompt sentence is gold if, after lower-casing and dropping punctuation, one contains the
other or their content-token Jaccard is >= 0.7. Then grade_dev.grade_item is used unchanged:
  ans_tokens = answer_tokens(reference_answer) (Gate 2 rule); if the gold sentences cover none
               of them, the gold sentences' own content tokens are used
  gold_cov   = share of ans_tokens the gold sentences cover
  expect     = decline if answerable=no; answerable if the gold sentences in the prompt cover
               >= 50% of what all gold sentences cover; otherwise miss (retrieval lost it)
B is graded without checks (what the bare model said), C with checks (what the app shows).
Items the app's topic gate settles without the model ("the label does not mention X") count as a
correct decline if T3 marks them unanswerable, else as a false decline.
D (passage-only) is scored as "a gold sentence is among the quotes shown".
"""
from __future__ import annotations

import csv
import json
import re

from common import BUILD, FINAL, drug_boot, jl, paired_boot, rate, wjl
from grade_dev import grade_item, prompt_sentences
from medlabel_data.fdarx.align import answer_tokens
from medlabel_data.text import content_tokens

RUNS = {  # run name -> (file, field, mode)
    "B2b_phone": ("t3_B2b_phone", "first", "nochecks"),
    "B2b_desktop": ("t3_B2b_desktop", "first", "nochecks"),
    "B08_phone": ("t3_B08_phone", "first", "nochecks"),
    "C2b_phone": ("t3_C2b_phone", "first", "checks"),
    "C2b_desktop": ("t3_CF2b_desktop", "first", "checks"),
    "C08_phone": ("t3_CF08_phone", "first", "checks"),
}
_P = re.compile(r"[^a-z0-9 ]+")


def _n(s: str) -> str:
    return " ".join(_P.sub(" ", s.lower()).split())


def same(a: str, b: str) -> bool:
    na, nb = _n(a), _n(b)
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    ta, tb = set(content_tokens(a)), set(content_tokens(b))
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= 0.7


def gold_list(r: dict) -> list[str]:
    if not r["gold_text"].strip():
        return []
    return [re.sub(r"^\[\d+\]\s*", "", g.strip()) for g in r["gold_text"].split(" | ") if g.strip()]


def t3_refs() -> dict:
    return {r["t3_id"]: r for r in csv.DictReader(open(BUILD / "t3" / "t3_draft.csv"))}


def build_p(ref: dict, call: dict) -> dict:
    user = call["user"]
    m = re.match(r"Drug: (.*)", user)
    drug = m.group(1).strip() if m else ref["drug"]
    sents = prompt_sentences(user)
    gold = gold_list(ref)
    p = {"user": user, "drug": drug, "gold_texts": [], "gold_nums": [], "ans_tokens": [], "gold_cov": 0.0}
    if ref["answerable"] != "yes":
        p["expect"] = "decline"
        return p
    excuse = set(content_tokens(ref["drug"])) | set(content_tokens(ref["brand"])) | set(content_tokens(drug))
    ans = answer_tokens(ref["reference_answer"], ref["question"], excuse)
    gtok = set().union(*(set(content_tokens(g)) for g in gold)) if gold else set()
    if not (ans & gtok):
        ans = gtok - set(content_tokens(ref["question"])) - excuse or gtok
    gold_cov = len(ans & gtok) / len(ans) if ans else 0.0
    nums = sorted(n for n, (s, _) in sents.items() if any(same(s, g) for g in gold))
    pcov_tok = set()
    for n in nums:
        s, h = sents[n]
        pcov_tok |= (set(content_tokens(s)) | set(content_tokens(h))) & ans
    pcov = len(pcov_tok) / len(ans) if ans else 0.0
    p.update(gold_texts=[sents[n][0] for n in nums], gold_nums=nums, ans_tokens=sorted(ans), gold_cov=gold_cov,
             expect="answerable" if nums and gold_cov and pcov >= 0.5 * gold_cov else "miss", prompt_cov=round(pcov, 3))
    return p


def stats(rows: list[dict]) -> dict:
    ans = [r for r in rows if r["expect"] == "answerable"]
    dec = [r for r in rows if r["expect"] == "decline"]
    said = [r for r in rows if r["status"] == "answer"]
    ok = lambda r: r["out"] == "correct"  # noqa: E731
    return {
        "n": len(rows),
        "correct": rate(rows, ok), "correct_ci": drug_boot(rows, lambda s: rate(s, ok)),
        "wrong": rate(rows, lambda r: r["out"] in ("wrong", "wrong_answered", "invalid")),
        "wrong_ci": drug_boot(rows, lambda s: rate(s, lambda r: r["out"] in ("wrong", "wrong_answered", "invalid"))),
        "gate_no_model": sum(bool(r.get("no_call")) for r in rows),
        "answerable_n": len(ans), "answerable_correct": rate(ans, ok),
        "false_decline": rate(ans, lambda r: r["out"] == "false_decline"),
        "decline_n": len(dec), "decline_correct": rate(dec, ok),
        "miss_n": sum(r["expect"] == "miss" for r in rows),
        "invalid": rate(rows, lambda r: r["out"] == "invalid"),
        "block_rate": rate(said, lambda r: r["blocked"]),
    }


def main() -> None:
    refs = t3_refs()
    out, allrows = {}, {}
    for name, (fn, field, mode) in RUNS.items():
        f = FINAL / "app" / f"{fn}.jsonl"
        if not f.exists():
            print("missing", f)
            continue
        rows = []
        for x in jl(f):
            ref = refs[x["id"]]
            calls = x.get("label_calls") or []
            base = {"id": x["id"], "drug": ref["drug"], "topic": ref["topic"]}
            if not calls:
                # the app's topic gate answered "the label does not mention X" without calling the model
                exp = "decline" if ref["answerable"] != "yes" else "answerable"
                shown = (x.get(field) or {}).get("shown") or {}
                rows.append({**base, "expect": exp, "status": "gate_" + shown.get("kind", "none"), "blocked": False,
                             "out": "correct" if exp == "decline" else "false_decline", "no_call": True})
                continue
            p = build_p(ref, calls[0])
            g = grade_item(p, calls[0]["raw"])
            rows.append({**base, "expect": p["expect"], "status": g["status"], "blocked": g["blocked"],
                         "out": g[mode], "out_checks": g["checks"], "out_nochecks": g["nochecks"],
                         "select_ok": g["select_ok"], "gold_nums": p["gold_nums"], "prompt_cov": p.get("prompt_cov")})
        allrows[name] = rows
        out[name] = stats(rows)
    # D: is a gold sentence among the quotes shown?
    for tier in ("phone", "desktop"):
        f = FINAL / "app" / f"t3_D_{tier}.jsonl"
        if not f.exists():
            continue
        rows = []
        for x in jl(f):
            ref = refs[x["id"]]
            q = ((x["first"] or {}).get("shown") or {}).get("quotes") or []
            hit = any(same(qq["text"], g) for qq in q for g in gold_list(ref))
            rows.append({"id": x["id"], "drug": ref["drug"], "answerable": ref["answerable"] == "yes", "hit": hit,
                         "declined": not q})
        a = [r for r in rows if r["answerable"]]
        out[f"D_{tier}"] = {"n": len(rows), "answerable_n": len(a), "gold_hit": rate(a, lambda r: r["hit"]),
                            "gold_hit_ci": drug_boot(a, lambda s: rate(s, lambda r: r["hit"])),
                            "shows_nothing": rate(rows, lambda r: r["declined"])}
    ok = lambda s: rate(s, lambda r: r["out"] == "correct")  # noqa: E731
    diffs = {}
    for c, b in (("C2b_phone", "B2b_phone"), ("C08_phone", "B08_phone"), ("C2b_desktop", "B2b_desktop")):
        if c in allrows and b in allrows:
            A = {r["id"]: r for r in allrows[c]}
            B_ = {r["id"]: r for r in allrows[b]}
            ids = sorted(set(A) & set(B_))
            diffs[f"{c}-{b}"] = {"diff": round(ok([A[i] for i in ids]) - ok([B_[i] for i in ids]), 4),
                                 "ci": paired_boot([A[i] for i in ids], [B_[i] for i in ids], ok)}
    out["paired_correct_diff"] = diffs
    (FINAL / "grades").mkdir(parents=True, exist_ok=True)
    (FINAL / "grades" / "t3_auto.json").write_text(json.dumps(out, indent=1))
    wjl(FINAL / "grades" / "t3_auto_rows.jsonl", [{"run": k, **r} for k, rs in allrows.items() for r in rs])
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
