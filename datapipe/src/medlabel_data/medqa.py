"""Prepare MedicationQA (MedInfo 2019, CC BY 4.0) as test set T2. Never used for training.

Each row has a consumer question, the focus drug, a question type, a reference answer,
the section title of the source, and the source URL. Only answers from DailyMed
(dailymed.nlm.nih.gov, ~290 of 690) come from an FDA label; those form the main T2 set.
For them the SPL set id is parsed from the URL, and openFDA is asked whether that set id is
still a current label, so the evaluator can fetch the matching label.

Output: BUILD/medqa/t2_all.jsonl (all rows) and BUILD/medqa/t2_dailymed.jsonl, plus
BUILD/medqa/report.json.
"""

import json
import re
from collections import Counter
from urllib.parse import parse_qs, urlparse

import openpyxl

from . import labels, paths
from .sections import classify_section

OUT_DIR = paths.BUILD / "medqa"
_SETID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


def _clean(v) -> str:
    return "" if v is None else str(v).strip()


def read_rows() -> list[dict]:
    ws = openpyxl.load_workbook(paths.MEDQA_XLSX, read_only=True).worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    hdr = [_clean(h) for h in rows[0]]
    out = []
    for i, r in enumerate(rows[1:], 1):
        d = dict(zip(hdr, map(_clean, r)))
        if not d.get("Question"):
            continue
        url = d.get("URL", "")
        host = urlparse(url).netloc.lower() if "//" in url else ""
        set_id = None
        if "dailymed" in host:
            q = parse_qs(urlparse(url).query)
            cand = (q.get("setid") or q.get("setId") or [""])[0] or url
            m = _SETID.search(cand)
            set_id = m.group(0).lower() if m else None
        section = d.get("Section Title", "")
        out.append({
            "id": f"medqa-{i:04d}", "question": d["Question"], "focus_drug": d.get("Focus (Drug)", ""),
            "question_type": d.get("Question Type", ""), "reference_answer": d.get("Answer", ""),
            "section_title": section,
            "section_category": classify_section(section) if section and section != "NA" else None,
            "url": url, "source_host": host, "from_dailymed": "dailymed" in host, "set_id": set_id,
        })
    return out


def main() -> None:
    rows = read_rows()
    set_ids = sorted({r["set_id"] for r in rows if r["set_id"]})
    current = labels.openfda_by_set_ids(set_ids)
    for r in rows:
        rec = current.get(r["set_id"]) if r["set_id"] else None
        r["set_id_current_in_openfda"] = bool(rec)
        r["label_version"] = rec.get("version") if rec else None
        r["label_effective_time"] = rec.get("effective_time") if rec else None
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dm = [r for r in rows if r["from_dailymed"]]
    for name, data in (("t2_all.jsonl", rows), ("t2_dailymed.jsonl", dm)):
        with open(OUT_DIR / name, "w") as f:
            for r in data:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    report = {
        "rows": len(rows),
        "from_dailymed": len(dm),
        "dailymed_with_set_id": sum(1 for r in dm if r["set_id"]),
        "dailymed_unique_set_ids": len({r["set_id"] for r in dm if r["set_id"]}),
        "dailymed_set_id_current_in_openfda": sum(r["set_id_current_in_openfda"] for r in dm),
        "dailymed_question_types": Counter(r["question_type"] for r in dm).most_common(),
        "dailymed_section_categories": Counter(r["section_category"] for r in dm).most_common(),
        "source_hosts": Counter(r["source_host"] or "none" for r in rows).most_common(12),
    }
    (OUT_DIR / "report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
