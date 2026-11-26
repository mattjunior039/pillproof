"""v1.1 evaluation (docs/v1.1.md): AI-grade the T7 runs, the post-hoc v1.1 T3 runs and the T1 refusal replay, then summarise.

    datapipe/.venv/bin/python train/scripts/final/v11_grade.py grade      # Claude Sonnet 5.5, same rubric and cache as the final eval
    ~/waicy-work/envs/mlx/bin/python train/scripts/final/v11_grade.py summary   (no API calls; writes final/v11/summary.json)

The grader prompt and rubric are grade_ai.GSYSTEM / prompt_for, unchanged from the final evaluation. Its cache is keyed
on the prompt, so an answer shown identically by v1.0 and v1.1 gets the same grade.
"""
from __future__ import annotations

import csv
import json
import random
import re
import sys
from collections import Counter

from common import BUILD, FINAL, drug_boot, jl, paired_boot, rate, wjl

V11 = FINAL / "v11"
GR = V11 / "grades"
T1_REF = ("The FDA label does not contain the information needed to answer this question (FDARxBench refusal item; "
          "expected answer: 'Information not found!').")
# system -> (run file, how the answer is shown)
T7_RUNS = {"v10_F2b": "F", "v11_F2b": "F", "v10_F08": "F", "v11_F08": "F", "B2b_phone": "B", "B08_phone": "B", "D_phone": "D"}
T3_RUNS = {"v10_F2b": (FINAL / "app/t3_CF2b_desktop.jsonl", "F"), "v10_F08": (FINAL / "app/t3_CF08_phone.jsonl", "F"),
           "v11_F2b": (V11 / "t3_v11_F2b.jsonl", "F"), "v11_F08": (V11 / "t3_v11_F08.jsonl", "F")}


def t7_refs() -> dict[str, dict]:
    out = {}
    for r in csv.DictReader(open(BUILD / "t7/t7_items.csv")):
        gold = [re.sub(r"^\[\d+\]\s*", "", g).strip() for g in r["gold_text"].split(" | ") if g.strip()]
        out[r["t7_id"]] = {"drug": f"{r['brand']} ({r['drug']})" if r["brand"] else r["drug"], "question": r["question"],
                           "answerable": r["answerable"] == "yes", "reference": r["reference_answer"], "gold": gold,
                           "drug_key": r["drug"], "in_t3": r["in_t3"] == "yes"}
    return out


def t3_refs() -> dict[str, dict]:
    from grade_ai import refs
    R = refs("t3")
    D = {r["t3_id"]: r["drug"] for r in csv.DictReader(open(BUILD / "t3/t3_draft.csv"))}
    return {k: {**v, "drug_key": D[k]} for k, v in R.items()}


def shown(row: dict, how: str) -> str:
    from grade_ai import render_raw, with_source
    if how == "F":
        return with_source(row, row["shown_text"])
    if how == "B":
        c = row["label_calls"]
        return render_raw(c[0]["raw"], c[0]["user"]) if c else row["label_text"]
    return row["label_text"]


def answers() -> list[dict]:
    out = []
    for s, how in T7_RUNS.items():
        p = V11 / f"t7_{s}.jsonl"
        if p.exists():
            out += [{"set": "t7", "id": r["id"], "system": s, "text": shown(r, how)} for r in jl(p)]
    for s, (p, how) in T3_RUNS.items():
        if p.exists():
            out += [{"set": "t3", "id": r["id"], "system": s, "text": shown(r, how)} for r in jl(p)]
    p = V11 / "t1_refusal_replay.jsonl"
    if p.exists():
        for r in jl(p):
            if r["tier"] != "desktop":  # shown text is identical at both tiers (checked in summary)
                continue
            for v in ("v10", "v11"):
                out.append({"set": "t1r", "id": r["qid"], "system": v, "text": r[v]["text"]})
    return out


def all_refs() -> dict:
    R = {"t7": t7_refs(), "t3": t3_refs(), "t1r": {}}
    p = V11 / "t1_refusal_replay.jsonl"
    if p.exists():
        for r in jl(p):
            R["t1r"][r["qid"]] = {"drug": r["drug"], "question": r["question"], "answerable": False, "reference": T1_REF,
                                  "gold": [], "drug_key": r["drug"].lower()}
    return R


def grade():
    from claude import Client
    from grade_ai import GMAX, GSYSTEM, VERDICTS, parse_json, prompt_for
    R = all_refs()
    tasks = answers()
    for t in tasks:
        t["prompt"] = prompt_for(R[t["set"]][t["id"]], t["text"], False)
    random.Random(7).shuffle(tasks)
    print(Counter((t["set"], t["system"]) for t in tasks))
    c = Client()
    c.batch([(GSYSTEM, t["prompt"], GMAX) for t in tasks], "v11-grade", out_per_item=160)
    GR.mkdir(parents=True, exist_ok=True)
    for s in ("t7", "t3", "t1r"):
        rows = []
        for t in (t for t in tasks if t["set"] == s):
            r = c.get(GSYSTEM, t["prompt"], GMAX)
            j = parse_json(r["text"]) if r else {}
            v = j.get("verdict")
            rows.append({"set": s, "id": t["id"], "system": t["system"], "verdict": v if v in VERDICTS["g"] else None,
                         "harm": j.get("harm"), "reason": j.get("reason"), "text": t["text"]})
        rows.sort(key=lambda r: (r["system"], r["id"]))
        if rows:
            wjl(GR / f"{s}.jsonl", rows)
            print(s, len(rows), "unparsed", sum(r["verdict"] is None for r in rows))
    print(f"spent ${c.spent():.2f}")


def good(r) -> bool:
    """Acceptable (summarize.good): correct, or an honest decline on an item the label does not answer."""
    return r["verdict"] == "correct" or (r["verdict"] == "declined" and r["answerable"] is False)


def stats(x: list[dict]) -> dict:
    c = Counter(r["verdict"] for r in x)
    a = [r for r in x if r["answerable"]]
    u = [r for r in x if r["answerable"] is False]
    return {"n": len(x), **{k: round(v / len(x), 4) for k, v in sorted(c.items())},
            "acceptable": rate(x, good), "acceptable_ci": drug_boot(x, lambda y: rate(y, good)),
            "wrong": rate(x, lambda r: r["verdict"] == "wrong"),
            "harm_serious_n": sum(r.get("harm") == "serious" for r in x), "harm_minor_n": sum(r.get("harm") == "minor" for r in x),
            "answerable_n": len(a), "answerable_correct": rate(a, lambda r: r["verdict"] == "correct"),
            "silent_n": len(u), "silent_acceptable": rate(u, good), "silent_wrong_n": sum(r["verdict"] == "wrong" for r in u),
            "silent_serious_n": sum(r.get("harm") == "serious" for r in u)}


def v10_kind(r: dict) -> str:
    hit = (r["backup"] or {}).get("hit")
    if hit:
        s = hit.get("source") or {}
        return "backup:" + str(s.get("kind") or s.get("type") or s.get("name") or "?")
    return ("backups-nothing:" if r["backup"] else "") + str(r["first"]["shown"].get("kind"))


def fired(v10: dict, v11: dict) -> dict:
    """How often v1.1 shows something different from v1.0, and whether the model replies were the same."""
    ids = sorted(set(v10) & set(v11))
    raw_same = sum([c.get("raw") for c in v10[i]["label_calls"]] == [c.get("raw") for c in v11[i]["label_calls"]] for i in ids)
    changed = [i for i in ids if v10[i]["shown_text"] != v11[i]["shown_text"]]
    rule = [i for i in changed if v11[i]["first"]["shown"].get("kind") == "passages" and v11[i]["first"]["shown"].get("why") == "declined"
            and v11[i]["backup"] is None]
    return {"n": len(ids), "model_replies_identical": raw_same, "display_changed": len(changed), "label_sentences_instead": len(rule),
            "v10_shown_when_rule_fired": dict(Counter(v10_kind(v10[i]) for i in rule)),
            "changed_ids": changed}


def summary():
    R = all_refs()
    out = {}
    rows_by = {}
    for s in ("t7", "t3", "t1r"):
        f = GR / f"{s}.jsonl"
        if not f.exists():
            continue
        rows = [{**r, "drug": R[s][r["id"]]["drug_key"], "answerable": R[s][r["id"]]["answerable"]} for r in jl(f)]
        rows_by[s] = rows
        out[s] = {sy: {**stats([r for r in rows if r["system"] == sy and r["verdict"]]),
                       "unparsed": sum(1 for r in rows if r["system"] == sy and not r["verdict"])}
                  for sy in sorted({r["system"] for r in rows})}
    pairs = {"t7": [("v11_F2b", "v10_F2b"), ("v11_F08", "v10_F08"), ("v11_F2b", "B2b_phone"), ("v11_F08", "B08_phone"),
                    ("v11_F2b", "D_phone"), ("v10_F2b", "D_phone")],
             "t3": [("v11_F2b", "v10_F2b"), ("v11_F08", "v10_F08")], "t1r": [("v11", "v10")]}
    d = {}
    for s, ps in pairs.items():
        if s not in rows_by:
            continue
        for a, b in ps:
            A = {r["id"]: r for r in rows_by[s] if r["system"] == a and r["verdict"]}
            B = {r["id"]: r for r in rows_by[s] if r["system"] == b and r["verdict"]}
            ids = sorted(set(A) & set(B))
            if not ids:
                continue
            ra, rb = [A[i] for i in ids], [B[i] for i in ids]
            ser = lambda y: rate(y, lambda r: r.get("harm") == "serious")  # noqa: E731
            d[f"{s}:{a}-{b}"] = {"n": len(ids), "acceptable_diff": round(rate(ra, good) - rate(rb, good), 4),
                                 "acceptable_ci": paired_boot(ra, rb, lambda y: rate(y, good)),
                                 "serious_a": sum(r.get("harm") == "serious" for r in ra),
                                 "serious_b": sum(r.get("harm") == "serious" for r in rb),
                                 "serious_diff_ci": paired_boot(ra, rb, ser),
                                 "wrong_a": sum(r["verdict"] == "wrong" for r in ra), "wrong_b": sum(r["verdict"] == "wrong" for r in rb)}
    out["paired"] = d
    # new drugs only (not in T3), as a check on the "fresh" part of T7
    if "t7" in rows_by:
        new = [r for r in rows_by["t7"] if not R["t7"][r["id"]]["in_t3"]]
        out["t7_new_drugs"] = {sy: stats([r for r in new if r["system"] == sy and r["verdict"]]) for sy in sorted({r["system"] for r in new})}
    fire = {}
    for s, (a, b) in {"t7_2b": ("v10_F2b", "v11_F2b"), "t7_08": ("v10_F08", "v11_F08")}.items():
        pa, pb = V11 / f"t7_{a}.jsonl", V11 / f"t7_{b}.jsonl"
        if pa.exists() and pb.exists():
            fire[s] = fired({r["id"]: r for r in jl(pa)}, {r["id"]: r for r in jl(pb)})
    for s, (a, b) in {"t3_2b": ("v10_F2b", "v11_F2b"), "t3_08": ("v10_F08", "v11_F08")}.items():
        pa, pb = T3_RUNS[a][0], T3_RUNS[b][0]
        if pa.exists() and pb.exists():
            fire[s] = fired({r["id"]: r for r in jl(pa)}, {r["id"]: r for r in jl(pb)})
    p = V11 / "t1_refusal_replay.jsonl"
    if p.exists():
        rr = jl(p)
        by = {}
        for r in rr:
            by.setdefault(r["qid"], {})[r["tier"]] = r
        fire["t1_refusal"] = {"items": len(by), "tiers_identical": sum(x["desktop"]["v11"]["text"] == x["phone"]["v11"]["text"]
                                                                       and x["desktop"]["v10"]["text"] == x["phone"]["v10"]["text"] for x in by.values()),
                              **{t: {"changed": sum(r["changed"] for r in rr if r["tier"] == t)} for t in ("desktop", "phone")}}
    out["fired"] = fire
    wjl(V11 / "summary.jsonl", [out])
    (V11 / "summary.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "fired"}, indent=1)[:12000])
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "changed_ids"} for k, v in fire.items()}, indent=1))


if __name__ == "__main__":
    {"grade": grade, "summary": summary}[sys.argv[1]]()
