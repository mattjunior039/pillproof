"""Writes an annotation workbook (.xlsx, opens in Google Sheets) and one CSV per tab."""

import csv
import re
from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .tasks import BLOCKED, RULE, Task

DUE = "2026-11-23"
BASE = ["item_id", "task", "annotator"]
REF_TAB = "Decline labels"
MAX_CELL = 32000  # Excel's limit is 32,767 characters


def columns(task: Task) -> list[str]:
    return BASE + [c for c, _ in task.show] + [m.name for m in task.marks]


def _clean(v):
    if isinstance(v, str):
        v = ILLEGAL_CHARACTERS_RE.sub("", v)
        if len(v) > MAX_CELL:
            v = v[:MAX_CELL] + " …[cut]"
    return v


def _fill(color: str) -> PatternFill:
    return PatternFill("solid", start_color=color, end_color=color)


def _darker(color: str) -> str:
    return "".join(f"{int(int(color[i:i + 2], 16) * 0.8):02X}" for i in (0, 2, 4))


def _header(ws, headers: list[str], widths: list[int], color: str) -> None:
    ws.append(headers)
    for i, w in enumerate(widths, 1):
        c = ws.cell(row=1, column=i)
        c.font, c.fill = Font(bold=True), _fill(color)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "B2"


def _rows(ws, rows: list[list]) -> None:
    top = Alignment(wrap_text=True, vertical="top")
    for r in rows:
        ws.append([_clean(v) for v in r])
        for c in ws[ws.max_row]:
            c.alignment = top


def _dropdown(ws, col: int, n: int, choices: list[str], title: str, strict: bool = True) -> None:
    if n == 0 or not choices:
        return
    choices = [c.replace(",", " ").replace('"', "") for c in choices]
    dv = DataValidation(type="list", formula1='"' + ",".join(choices) + '"', allow_blank=True,
                        showErrorMessage=strict, errorTitle=title, error="Pick a value from the list.")
    letter = get_column_letter(col)
    dv.add(f"{letter}2:{letter}{n + 1}")
    ws.add_data_validation(dv)


def task_sheet(wb: Workbook, task: Task, items: list[dict], annotators: list[str]) -> None:
    cols = columns(task)
    bad = [c for c in cols if BLOCKED.search(c)]
    if bad:
        raise ValueError(f"{task.key}: columns {bad} must not be shown to reviewers")
    ws = wb.create_sheet(task.tab)
    ws.sheet_properties.tabColor = task.color
    widths = [10, 9, 14] + [w for _, w in task.show] + [m.width for m in task.marks]
    _header(ws, cols, widths, task.color)
    first_mark = len(BASE) + len(task.show) + 1
    for j in range(first_mark, len(cols) + 1):
        ws.cell(row=1, column=j).fill = _fill(_darker(task.color))
    _rows(ws, [[it.get(c, "") for c in cols] for it in items])
    for i in range(2, len(items) + 2):
        for j in range(first_mark, len(cols) + 1):
            ws.cell(row=i, column=j).fill = _fill(task.color)
    _dropdown(ws, 3, len(items), annotators, "annotator", strict=False)  # new names allowed
    for j, m in enumerate(task.marks, first_mark):
        _dropdown(ws, j, len(items), m.choices, m.name)


def _done_formula(task: Task, n: int, who: str) -> str:
    col = get_column_letter(columns(task).index(task.primary) + 1)
    rng = f"'{task.tab}'!${col}$2:${col}${n + 1}"
    if who == "all":
        return f"=COUNTA({rng})"
    return f"=COUNTIFS('{task.tab}'!$C$2:$C${n + 1},A{{row}},{rng},\"<>\")"


def compress(ids: list[str]) -> str:
    """'T5-001, T5-002, T5-003, T5-007' -> 'T5-001–T5-003, T5-007'."""
    def num(s):
        m = re.match(r"(.*?)(\d+)$", s)
        return (m.group(1), int(m.group(2)), len(m.group(2))) if m else (s, None, 0)
    out, run = [], []
    for s in sorted(ids, key=lambda s: (num(s)[0], num(s)[1] or 0)):
        p, n, _ = num(s)
        if run and n is not None and num(run[-1])[0] == p and num(run[-1])[1] == n - 1:
            run.append(s)
            continue
        if run:
            out.append(run[0] if len(run) == 1 else f"{run[0]}–{run[-1]}")
        run = [s]
    if run:
        out.append(run[0] if len(run) == 1 else f"{run[0]}–{run[-1]}")
    return ", ".join(out)


def write(path: Path, tasks: list[Task], items: dict[str, list[dict]], annotators: list[str],
          plan: list[dict] | None = None, ref_rows: list[dict] | None = None, csv_dir: Path | None = None,
          due: str = DUE) -> None:
    """items: task key -> rows (only tasks with rows get a tab). plan: [{annotator, task, item_ids, double}];
    None gives one 'all' row per task."""
    tasks = [t for t in tasks if items.get(t.key)]
    wb = Workbook()
    ws = wb.active
    ws.title = "Start here"
    ws.sheet_properties.tabColor = "666666"
    _header(ws, ["tab", "what to do", "example 1", "example 2", "time per item"], [18, 90, 50, 50, 12], "DDDDDD")
    _rows(ws, [["RULE", RULE + f" Due {due}. Fill only the shaded columns; don't edit item_id, task or the item text. "
                "Pick your name in 'annotator' if it is empty.", "", "", ""]])
    ws["A2"].font = ws["B2"].font = Font(bold=True, color="CC0000")
    _rows(ws, [[t.tab, t.what, *t.examples, t.minutes] for t in tasks])
    for i, t in enumerate(tasks, 3):
        ws.cell(row=i, column=1).fill = _fill(t.color)

    ws = wb.create_sheet("Assignments")
    ws.sheet_properties.tabColor = "666666"
    _header(ws, ["annotator", "task", "tab", "items", "n_items", "double_marked", "due", "done", "remaining"],
            [16, 10, 18, 60, 9, 13, 11, 8, 10], "DDDDDD")
    by_key = {t.key: t for t in tasks}
    plan = plan if plan is not None else [{"annotator": "all", "task": t.key,
                                           "item_ids": [it["item_id"] for it in items[t.key]], "double": 0}
                                          for t in tasks]
    arows = []
    for i, p in enumerate([p for p in plan if p["task"] in by_key], 2):
        t = by_key[p["task"]]
        done = _done_formula(t, len(items[t.key]), p["annotator"]).replace("{row}", str(i))
        arows.append([p["annotator"], t.key, t.tab, compress(p["item_ids"]), len(p["item_ids"]), p["double"], due,
                      done, f"=E{i}-H{i}"])
    _rows(ws, arows)
    for i, r in enumerate(arows, 2):
        ws.cell(row=i, column=3).fill = _fill(by_key[r[1]].color)

    for t in tasks:
        task_sheet(wb, t, items[t.key], annotators)
    if ref_rows:
        ws = wb.create_sheet(REF_TAB)
        ws.sheet_properties.tabColor = by_key["decline"].color if "decline" in by_key else "999999"
        _header(ws, ["item_id", "line", "text"], [10, 7, 140], "EEEEEE")
        _rows(ws, [[r["item_id"], r["line"], r["text"]] for r in ref_rows])
        ws.auto_filter.ref = f"A1:C{len(ref_rows) + 1}"
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)

    if csv_dir:
        csv_dir.mkdir(parents=True, exist_ok=True)
        for old in csv_dir.glob("*.csv"):
            old.unlink()
        for k, sheet in enumerate(wb.worksheets, 1):
            name = re.sub(r"[^a-z0-9]+", "_", sheet.title.lower()).strip("_")
            with open(csv_dir / f"{k:02d}_{name}.csv", "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerows([["" if c is None else c for c in row]
                                         for row in sheet.iter_rows(values_only=True)])
