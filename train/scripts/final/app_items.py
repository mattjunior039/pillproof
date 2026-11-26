"""Item files for the app-pipeline runs (app/eval/final_harness.ts) on T3, T2 and T6.

    python3 train/scripts/final/app_items.py   # -> final/{t3,t2,t6}/items_app.jsonl
The medicine is built from the label's own openFDA record (generic name, first RxCUI, route/form), as if
the user had added that product; the question goes straight to that medicine (router skipped).
"""
import csv
import json
import re
from pathlib import Path

B = Path("~/waicy-work/data/build").expanduser()
F = B / "final"


def med_from(rec: dict) -> dict:
    o = rec.get("openfda", {})
    g = (o.get("generic_name") or [""])[0].lower()
    g = re.sub(r"\([^)]*\)", "", g)
    parts = [p.strip() for p in re.split(r",|\band\b|/", g) if p.strip()]
    route = (o.get("route") or [""])[0]
    dfs = " ".join(rec.get("dosage_forms_and_strengths", []) + rec.get("description", [])).lower()
    if route == "ORAL":
        ci, ti = dfs.find("capsule"), dfs.find("tablet")
        kind = "Capsule" if ci >= 0 and (ti < 0 or ci < ti) else "Tablet"
        form = f"Oral {kind}"
    else:
        form = route.title()
    return {"ingredient": " / ".join(parts), "rxcui": (o.get("rxcui") or [""])[0], "form": form}


def write(name, rows):
    p = F / name / "items_app.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(name, len(rows))


def main():
    t3 = []
    for r in csv.DictReader(open(B / "t3" / "t3_draft.csv")):
        lf = B / "t3" / "labels" / f"{r['drug']}.openfda.json"
        rec = json.loads(lf.read_text())
        assert rec["set_id"] == r["set_id"], r["t3_id"]
        t3.append({"id": r["t3_id"], "question": r["question"], "label_file": str(lf), "drug": r["drug"], **med_from(rec)})
    write("t3", t3)

    t6 = []
    for r in csv.DictReader(open(B / "t6" / "t6_draft.csv")):
        if r["final_status"] not in ("keep", "edit"):
            continue
        lf = B / "t6" / "labels" / f"{r['drug']}.openfda.json"
        if not lf.exists():
            lf = B / "t3" / "labels" / f"{r['drug']}.openfda.json"
        rec = json.loads(lf.read_text())
        assert rec["set_id"].startswith(r["set_id"][:8]), r["t6_id"]
        t6.append({"id": r["t6_id"], "question": r["question"], "label_file": str(lf), "drug": r["drug"], **med_from(rec)})
    write("t6", t6)

    t2 = []
    for r in map(json.loads, open(F / "t2" / "items.jsonl")):
        lf = F / "t2" / "labels" / f"{r['set_id']}.json"
        rec = json.loads(lf.read_text())
        m = med_from(rec)
        if not m["ingredient"]:  # ~half the MedicationQA labels have no openfda block: use the question's drug name
            m["ingredient"] = re.sub(r"\b(er|xr|sr|cr|\d+\s*mg)\b", "", r["focus_drug"].lower()).strip()
            m["form"] = m["form"] or "Oral Tablet"
        t2.append({"id": r["id"], "question": r["question"], "label_file": str(lf), "drug": r["focus_drug"], **m})
    write("t2", t2)


if __name__ == "__main__":
    main()
