"""Build the master annotation workbook (all tasks, one tab each) and one CSV per tab.

    uv run python -m medlabel_data.annotation.build [--annotators "Ana,Ben"]

To give each person their own file, use `medlabel_data.annotation.split` instead (it also
rebuilds the master with the assignment plan).
"""

import argparse
import json
from pathlib import Path

from . import workbook
from .tasks import OUT, TASKS, decline_label_rows


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--annotators", default="", help="names for the annotator dropdown (default: from the last "
                                                       "split, else 'student')")
    ap.add_argument("--due", default=workbook.DUE)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    names = [n.strip() for n in a.annotators.split(",") if n.strip()]
    plan_file = a.out / "split" / "plan.json"
    if not names and plan_file.exists():
        p = json.loads(plan_file.read_text())
        names = p["annotators"] + ([p["pharmacist"]] if p.get("pharmacist") else [])
    names = names or ["student"]
    items = {t.key: t.load() for t in TASKS}
    workbook.write(a.out / "annotation_master.xlsx", TASKS, items, names, None,
                   decline_label_rows(items["decline"]), a.out / "csv", a.due)
    for t in TASKS:
        print(f"{t.tab}: {len(items[t.key])}")
    print(f"-> {a.out / 'annotation_master.xlsx'} and {a.out / 'csv'}/")


if __name__ == "__main__":
    main()
