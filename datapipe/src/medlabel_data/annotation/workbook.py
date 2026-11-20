"""Writes the annotation workbook (.xlsx for Google Sheets) and one CSV per tab.

Every tab starts with a one-line "What to do" row; the header is on row 2 (row 3 on the testers
tab) and is frozen. Only plain list dropdowns and classic functions (COUNTA, COUNTIFS, INDEX,
MATCH) are used, so the file keeps working after it is opened as a Google Sheet.
"""

import csv
import re
from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter as col_letter
from openpyxl.worksheet.datavalidation import DataValidation

from . import usability as U
from .tasks import (
    BLOCKED,
    COLORS,
    REF_TAB,
    RULE,
    SECOND_TAB,
    SECOND_WHAT,
    Task,
    second_text,
)

DUE = "2026-11-23"
SIZE = 12
NAME_ROWS = 30
MAX_CELL = 32000  # Excel's limit is 32,767 characters
SECOND_COLS = [("item_id", 11), ("drug", 14), ("item", 70), ("name", 14), ("answer", 18), ("only_formatting", 14),
               ("notes", 35), ("task", 9)]
TOP = Alignment(wrap_text=True, vertical="top")


def columns(task: Task) -> list[tuple[str, int]]:
    return ([("item_id", 11)] + task.show + [("name", 14)] + [(m.name, m.width) for m in task.marks]
            + [("task", 9)])


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


def _check(cols: list[str], where: str) -> None:
    bad = [c for c in cols if BLOCKED.search(c) and c != "sus_score"]
    if bad:
        raise ValueError(f"{where}: columns {bad} must not be shown to reviewers")


def _sheet(wb: Workbook, title: str, color: str, what: str, cols: list[tuple[str, int]], rows: list[dict],
           inputs: set[str], pre: str = "", pre_height: int = 0):
    """A tab: What-to-do row, optional text block, frozen header, data. Returns (sheet, header row)."""
    _check([c for c, _ in cols], title)
    ws = wb.create_sheet(title)
    ws.sheet_properties.tabColor = color
    n = len(cols)
    blocks = [(what, 50, Font(bold=True, size=SIZE))] + ([(pre, pre_height, Font(size=SIZE))] if pre else [])
    for r, (text, height, font) in enumerate(blocks, 1):
        c = ws.cell(row=r, column=1, value=("What to do: " if r == 1 else "") + text)
        c.font, c.alignment, c.fill = font, TOP, _fill(color)
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=max(n, 2))
        ws.row_dimensions[r].height = height
    h = len(blocks) + 1
    for j, (name, width) in enumerate(cols, 1):
        c = ws.cell(row=h, column=j, value=name)
        c.font, c.alignment = Font(bold=True, size=SIZE), TOP
        c.fill = _fill(_darker(color) if name in inputs else COLORS["info"])
        ws.column_dimensions[col_letter(j)].width = width
    for i, r in enumerate(rows, h + 1):
        for j, (name, _) in enumerate(cols, 1):
            v = _clean(r.get(name, ""))
            c = ws.cell(row=i, column=j, value=v if v != "" else None)
            c.font, c.alignment = Font(size=SIZE), TOP
            if name in inputs:
                c.fill = _fill(color)
            if isinstance(v, str) and v.startswith("https://") and " " not in v:
                c.hyperlink, c.font = v, Font(size=SIZE, color="1155CC", underline="single")
    ws.freeze_panes = f"A{h + 1}"
    return ws, h


def _dropdown(ws, col: int, r1: int, r2: int, choices: list[str] | None) -> None:
    if r2 < r1 or not choices:
        return
    choices = [c.replace(",", " ").replace('"', "") for c in choices]
    dv = DataValidation(type="list", formula1='"' + ",".join(choices) + '"', allow_blank=True,
                        showErrorMessage=True, errorTitle="Not in the list", error="Pick a value from the list.")
    dv.add(f"{col_letter(col)}{r1}:{col_letter(col)}{r2}")
    ws.add_data_validation(dv)


def _hours(task: Task, n: int) -> str:
    lo, hi = (round(m * n / 60, 1) for m in task.minutes)
    per = f"{task.minutes[0]:g}" if task.minutes[0] == task.minutes[1] else f"{task.minutes[0]:g}–{task.minutes[1]:g}"
    whole = f"{lo:g} h" if lo == hi else f"{lo:g}–{hi:g} h"
    return f"about {per} min per row; whole tab about {whole}"


def write(path: Path, tasks: list[Task], main: dict[str, list[dict]], second: list[dict] | None = None,
          usability_rows: int = 0, ref: list[dict] | None = None, csv_dir: Path | None = None,
          due: str = DUE) -> None:
    """main: task key -> rows (a tab for each task with rows); second: Second check rows (item_id, task, drug,
    item, name); usability_rows: number of empty tester sessions; ref: label text lines."""
    tasks = [t for t in tasks if main.get(t.key)]
    by_key = {t.key: t for t in tasks}
    second = second or []
    progress = []  # (tab, who, done column, name column, first row, last row)
    wb = Workbook()

    ws = wb.active
    ws.title = "Start here"
    ws.sheet_properties.tabColor = "666666"
    ws.column_dimensions["A"].width = 28
    for col, w in zip("BCDE", (80, 55, 18, 30), strict=True):
        ws.column_dimensions[col].width = w
    roles = []
    if any(t.role == "markers" for t in tasks):
        roles.append("Markers: the five 'Markers –' tabs, then 'Second check'")
    if "pharmacist" in by_key:
        roles.append("Pharmacist: the 'Pharmacist' tab")
    if usability_rows:
        roles.append("Testers (the person running a test session): 'Testers – usability'")
    intro = ["MedLabel annotation — start here",
             "1. Pick the tab for your role. " + "; ".join(roles) + ".",
             "2. Type your first name in the Name column of every row you mark.",
             "3. " + RULE,
             ("4. Fill in only the coloured columns (dropdowns where there is a list). Don't change the grey columns or "
             "delete rows. Filtering and sorting are fine."),
             f"5. Please finish by {due}. The Progress tab counts what is done."]
    for i, line in enumerate(intro, 1):
        c = ws.cell(row=i, column=1, value=line)
        c.font = Font(bold=True, size=16 if i == 1 else SIZE, color="CC0000" if i == 4 else None)
        ws.merge_cells(start_row=i, start_column=1, end_row=i, end_column=5)
    hdr = len(intro) + 2
    for j, name in enumerate(["tab", "what to do", "examples", "who", "time"], 1):
        c = ws.cell(row=hdr, column=j, value=name)
        c.font, c.fill = Font(bold=True, size=SIZE), _fill(COLORS["info"])
    guide = [(t.tab, t.what, "• " + "\n• ".join(t.examples), t.role, _hours(t, len(main[t.key])), t.color)
             for t in tasks if t.role == "markers"]
    if second:
        mins = sum(by_key[s["task"]].minutes[1] for s in second) / 60
        guide.append((SECOND_TAB, SECOND_WHAT, "Same as the T5, T3 and T6 tabs.", "markers",
                      f"same per row as its tab; whole tab about {mins:.1f} h", COLORS["markers"]))
    guide += [(t.tab, t.what, "• " + "\n• ".join(t.examples), t.role, _hours(t, len(main[t.key])), t.color)
              for t in tasks if t.role != "markers"]
    if usability_rows:
        guide.append((U.TAB, U.WHAT, "One row per tester.", "testers", "20–30 min per session", COLORS["testers"]))
    if ref:
        guide.append((REF_TAB, ("Full label text for the training-audit and decline-check rows, one line per row. "
                      "Filter the item_id column to the item you are marking."), "", "markers", "", COLORS["info"]))
    for i, (tab, what, ex, who, time, color) in enumerate(guide, hdr + 1):
        for j, v in enumerate([tab, what, ex, who, time], 1):
            c = ws.cell(row=i, column=j, value=v)
            c.font, c.alignment = Font(size=SIZE, bold=j == 1), TOP
        ws.cell(row=i, column=1).fill = _fill(color)

    prog = wb.create_sheet("Progress")
    prog.sheet_properties.tabColor = "666666"

    for t in tasks:
        cols = columns(t)
        names = [c for c, _ in cols]
        inputs = {"name"} | {m.name for m in t.marks}
        ws, h = _sheet(wb, t.tab, t.color, t.what, cols, main[t.key], inputs)
        r1, r2 = h + 1, h + len(main[t.key])
        for m in t.marks:
            _dropdown(ws, names.index(m.name) + 1, r1, r2, m.choices)
        progress.append((t.tab, t.role, col_letter(names.index(t.primary) + 1), col_letter(names.index("name") + 1),
                         r1, r2))
        if second and (t.key == "decline" or (t.key == "audit" and "decline" not in by_key)):
            _second(wb, by_key, second, progress)
    if second and not any(p[0] == SECOND_TAB for p in progress):
        _second(wb, by_key, second, progress)

    if usability_rows:
        cols = [("item_id", 8)] + [(c, w) for c, _, w in U.COLUMNS] + [("task", 10)]
        names = [c for c, _ in cols]
        rows = [{"item_id": iid, "task": "usability"} for iid in U.IDS[:usability_rows]]
        ws, h = _sheet(wb, U.TAB, COLORS["testers"], U.WHAT, cols, rows, set(U.INPUTS), U.SCRIPT, 420)
        r1, r2 = h + 1, h + usability_rows
        for c, choices in U.CHOICES.items():
            _dropdown(ws, names.index(c) + 1, r1, r2, choices)
        for i in range(1, 11):
            ws.cell(row=h, column=names.index(f"sus_{i}") + 1).comment = Comment(f"{i}. {U.SUS[i - 1]}", "MedLabel")
        s = [col_letter(names.index(f"sus_{i}") + 1) for i in range(1, 11)]
        sc = names.index("sus_score") + 1
        for r in range(r1, r2 + 1):
            odd = "+".join(f"{c}{r}" for c in s[0::2])
            even = "+".join(f"{c}{r}" for c in s[1::2])
            ws.cell(row=r, column=sc, value=f'=IF(COUNTA({s[0]}{r}:{s[-1]}{r})<10,"",'
                                            f'(({odd})-5+25-({even}))*2.5)')
        progress.append((U.TAB, "testers", col_letter(names.index("tester") + 1), col_letter(names.index("name") + 1),
                         r1, r2))

    if ref:
        ws, h = _sheet(wb, REF_TAB, COLORS["info"], "Look up the full label text: filter item_id (Data → Create a "
                       "filter) to the item you are marking. Nothing to fill in.",
                       [("item_id", 11), ("line", 7), ("text", 120)], ref, set())
        ws.auto_filter.ref = f"A{h}:C{h + len(ref)}"
        for row in ws.iter_rows(min_row=h + 1):
            for c in row:
                c.font = Font(size=11)

    _progress(prog, progress)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    if csv_dir:
        _csvs(wb, csv_dir)


def _second(wb, by_key, second, progress) -> None:
    rows = sorted(second, key=lambda s: list(by_key).index(s["task"]))  # blocks by task, shuffled within
    ws, h = _sheet(wb, SECOND_TAB, COLORS["markers"], SECOND_WHAT, SECOND_COLS, rows,
                   {"name", "answer", "only_formatting", "notes"})
    names = [c for c, _ in SECOND_COLS]
    for key in dict.fromkeys(s["task"] for s in rows):
        idx = [i for i, s in enumerate(rows, h + 1) if s["task"] == key]
        t = by_key[key]
        _dropdown(ws, names.index("answer") + 1, idx[0], idx[-1], t.marks[0].choices)
        m = t.mark("only_formatting")
        _dropdown(ws, names.index("only_formatting") + 1, idx[0], idx[-1], m.choices if m else None)
    progress.append((SECOND_TAB, "markers", col_letter(names.index("answer") + 1), col_letter(names.index("name") + 1),
                     h + 1, h + len(rows)))


def _progress(ws, progress) -> None:
    """Rows done per tab, then marks per name. The name list is built with classic formulas from hidden helper
    columns that stack every Name cell (X) and number each first occurrence (Y)."""
    ws.cell(row=1, column=1, value="What to do: nothing — this tab counts rows done (a row is done when its main "
            "column is filled) and rows marked per name.").font = Font(bold=True, size=SIZE)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(progress) + 2)
    ws.row_dimensions[1].height = 34
    for j, h in enumerate(["tab", "who", "done", "total", "% done"], 1):
        c = ws.cell(row=2, column=j, value=h)
        c.font, c.fill = Font(bold=True, size=SIZE), _fill(COLORS["info"])
    ws.column_dimensions["A"].width = 28
    for k, (tab, who, done, _, r1, r2) in enumerate(progress, 3):
        ws.cell(row=k, column=1, value=tab).fill = _fill(COLORS[who])
        ws.cell(row=k, column=2, value=who)
        ws.cell(row=k, column=3, value=f"=COUNTA('{tab}'!${done}${r1}:${done}${r2})")
        ws.cell(row=k, column=4, value=f"=ROWS('{tab}'!$A${r1}:$A${r2})")
        ws.cell(row=k, column=5, value=f'=IF(D{k}=0,"",C{k}/D{k})').number_format = "0%"
    top = len(progress) + 4
    heads = ["name"] + [p[0].replace("Markers – ", "") for p in progress] + ["total"]
    for j, h in enumerate(heads, 1):
        c = ws.cell(row=top, column=j, value=h)
        c.font, c.fill, c.alignment = Font(bold=True, size=SIZE), _fill(COLORS["info"]), TOP
        if j > 1:
            ws.column_dimensions[col_letter(j)].width = max(ws.column_dimensions[col_letter(j)].width or 0, 13)
    ws.row_dimensions[top].height = 34

    helper = [f"=\"\"&'{tab}'!{name}{r}" for tab, _, _, name, r1, r2 in progress for r in range(r1, r2 + 1)]
    hx, hy = 24, 25  # X, Y
    ws.cell(row=2, column=hx, value="helper: all names")
    ws.cell(row=2, column=hy, value="helper: first time seen")
    last = 2 + len(helper)
    for i, f in enumerate(helper, 3):
        ws.cell(row=i, column=hx, value=f)
        ws.cell(row=i, column=hy, value=f'=IF(X{i}="","",IF(COUNTIF(X$3:X{i},X{i})=1,MAX(Y$2:Y{i - 1})+1,""))')
    ws.column_dimensions["X"].hidden = ws.column_dimensions["Y"].hidden = True
    for k in range(1, NAME_ROWS + 1):
        r = top + k
        ws.cell(row=r, column=1, value=f'=IFERROR(INDEX($X$3:$X${last},MATCH({k},$Y$3:$Y${last},0)),"")')
        for j, (tab, _, done, name, r1, r2) in enumerate(progress, 2):
            ws.cell(row=r, column=j, value=f"=IF($A{r}=\"\",\"\",COUNTIFS('{tab}'!${name}${r1}:${name}${r2},$A{r},"
                                           f"'{tab}'!${done}${r1}:${done}${r2},\"<>\"))")
        end = col_letter(len(progress) + 1)
        ws.cell(row=r, column=len(progress) + 2, value=f'=IF($A{r}="","",SUM(B{r}:{end}{r}))')
    ws.freeze_panes = "A3"


def _csvs(wb: Workbook, csv_dir: Path) -> None:
    csv_dir.mkdir(parents=True, exist_ok=True)
    for old in csv_dir.glob("*.csv"):
        old.unlink()
    for k, sheet in enumerate(wb.worksheets, 1):
        name = re.sub(r"[^a-z0-9]+", "_", sheet.title.lower()).strip("_")
        with open(csv_dir / f"{k:02d}_{name}.csv", "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows([["" if c is None else c for c in row] for row in sheet.iter_rows(values_only=True)])


def second_rows(tasks: list[Task], main: dict[str, list[dict]], ids: dict[str, list[str]]) -> list[dict]:
    """Second check rows for the given item ids per task, in the given order."""
    by_key = {t.key: t for t in tasks}
    out = []
    for key, order in ids.items():
        items = {it["item_id"]: it for it in main[key]}
        out += [{"item_id": i, "task": key, "drug": items[i].get("drug", ""), "name": items[i].get("name", ""),
                 "item": second_text(by_key[key], items[i])} for i in order]
    return out
