"""Build the shared annotation workbook: one file for the markers, the pharmacist and the testers,
plus one CSV per tab.

    uv run python -m medlabel_data.annotation.build

Upload annotation_master.xlsx to Google Drive and open it as a Google Sheet (docs/annotation.md).
The Second check tab holds the seeded double-marked share of T5, T3 and T6 (split.double_set).
"""

import argparse
from pathlib import Path

from . import usability, workbook
from .split import SEED, double_set
from .tasks import OUT, TASKS, ref_rows


def build(out: Path = OUT, due: str = workbook.DUE, seed: int = SEED) -> dict:
    items = {t.key: t.load() for t in TASKS}
    ids = {t.key: double_set(items[t.key], seed, t.double, t.key) for t in TASKS if t.double}
    second = workbook.second_rows(TASKS, items, ids)
    ref = ref_rows([it for t in TASKS for it in items[t.key]])
    workbook.write(out / "annotation_master.xlsx", TASKS, items, second, usability.N_ROWS, ref, out / "csv", due)
    return {"items": {t.tab: len(items[t.key]) for t in TASKS}, "second": {k: len(v) for k, v in ids.items()},
            "usability": usability.N_ROWS, "reference_lines": len(ref)}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--due", default=workbook.DUE)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    s = build(a.out, a.due, a.seed)
    for tab, n in s["items"].items():
        print(f"{tab}: {n}")
    print(f"Second check: {sum(s['second'].values())} {s['second']}")
    print(f"Testers – usability: {s['usability']} empty sessions; reference lines: {s['reference_lines']}")
    print(f"-> {a.out / 'annotation_master.xlsx'} and {a.out / 'csv'}/")


if __name__ == "__main__":
    main()
