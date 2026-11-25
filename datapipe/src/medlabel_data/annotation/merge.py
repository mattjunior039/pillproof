"""Merge the completed annotation workbook back into the original sheets.

    uv run python -m medlabel_data.annotation.merge annotation_master_done.xlsx [--dry-run]

Reads the shared file downloaded back from Google Sheets (.xlsx), its tab CSVs, or per-person files
from `split` (files or folders; folders are not searched recursively). Every table whose header
(found in the first 10 rows) has item_id and task is read. Marks on the task tabs go into each
task's source sheet (t5_sheet.csv, t3_draft.csv, pharmacist_sheet.csv, ...) as `annotator` plus the
mark columns; marks on the Second check tab go into `annotator_2` and `<mark>_2`. Tester sessions go
to usability.csv. Existing marks are never overwritten: any disagreement with a filled cell aborts
the whole merge with nothing written. Blank rows and invalid values are reported. Agreement (Cohen's
kappa) is computed for first vs second marks, and pharmacist vs T5.

Names are cleaned (spaces collapsed) and can be fixed with `--alias Jhon=John`. A tab where
nobody typed a name can get one with `--default-annotator pharmacist="pharmacist (licensed)"`
(a bare `--default-annotator NAME` applies to every task).
"""

import argparse
import csv
import datetime as dt
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

from openpyxl import load_workbook

from . import usability as U
from .tasks import BY_KEY, OUT, Task, read_csv

USABILITY_COLS = ["item_id"] + U.INPUTS + ["sus_score"]
MIN_KAPPA_N = 20  # below this, the report says the sample is too small instead of leaning on kappa


@dataclass
class Result:
    marks: dict = field(default_factory=dict)        # (task, item_id, slot) -> {"annotator": name, mark: value}
    sessions: dict = field(default_factory=dict)     # usability item_id -> {column: value}
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    blanks: Counter = field(default_factory=Counter)  # (task, slot) -> rows with no marks


def _norm(s) -> str:
    return " ".join(str(s).replace("_", " ").split()).casefold()


def _value(v) -> str:
    if v is None:
        return ""
    if isinstance(v, dt.datetime):
        return v.date().isoformat() if v.time() == dt.time() else v.isoformat(sep=" ")
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _tables(path: Path):
    """Yields (source name, header, first data row number, rows) for every table with item_id and task."""
    if path.suffix.lower() == ".xlsx":
        wb = load_workbook(path, read_only=True, data_only=True)
        sheets = [(f"{path.name}:{ws.title}", [[_value(v) for v in r] for r in ws.iter_rows(values_only=True)])
                  for ws in wb.worksheets]
        wb.close()
    elif path.suffix.lower() == ".csv":
        with open(path, newline="", encoding="utf-8-sig") as f:
            sheets = [(path.name, [[v.strip() for v in r] for r in csv.reader(f)])]
    else:
        return
    for src, rows in sheets:
        for i, r in enumerate(rows[:10]):
            if "item_id" in r and "task" in r:
                yield src, r, i + 2, rows[i + 1:]
                break


def _files(inputs: list[Path]) -> list[Path]:
    out = []
    for p in inputs:
        p = p.expanduser()
        if p.is_dir():
            out += sorted(q for q in p.iterdir()
                          if q.suffix.lower() in (".xlsx", ".csv") and not q.name.startswith(("~", ".")))
        elif p.exists():
            out.append(p)
        else:
            raise SystemExit(f"not found: {p}")
    return out


def _cell(row: list[str], col: dict[str, int], c: str) -> str:
    i = col.get(c)
    return "" if i is None or i >= len(row) else row[i]


def _choice(v: str, choices: list[str]) -> str | None:
    return next((c for c in choices if _norm(c) == _norm(v)), None)


def _defaults(default_annotator: str | dict[str, str]) -> dict[str, str]:
    """'' -> {}; 'Name' -> {'*': 'Name'}; {'pharmacist': 'X'} as is."""
    if isinstance(default_annotator, dict):
        return default_annotator
    return {"*": default_annotator} if default_annotator else {}


def clean_name(name: str, aliases: dict[str, str] | None = None) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    for old, new in (aliases or {}).items():
        if name.casefold() == old.strip().casefold():
            return new
    return name


def read_marks(inputs: list[Path], tasks: dict[str, Task] = BY_KEY, default_annotator: str | dict[str, str] = "",
               aliases: dict[str, str] | None = None) -> Result:
    res = Result()
    defaults = _defaults(default_annotator)
    known = {k: {t.id_fn(r) for r in read_csv(t.source)} for k, t in tasks.items()}
    seen_from = {}
    for path in _files(inputs):
        for src, header, first, rows in _tables(path):
            col = {h: i for i, h in enumerate(header) if h}
            second = "answer" in col
            for n, row in enumerate(rows, first):
                get = partial(_cell, row, col)
                key, iid = get("task"), get("item_id")
                if not key and not iid:
                    continue
                where = f"{src} row {n}"
                if key == "usability":
                    _session(res, iid, {c: get(c) for c in U.INPUTS}, where, seen_from)
                    continue
                t = tasks.get(key)
                if t is None:
                    res.warnings.append(f"{where}: unknown task '{key}', skipped")
                    continue
                if iid not in known[key]:
                    res.warnings.append(f"{where}: unknown item_id '{iid}' for {key}, skipped")
                    continue
                slot = 2 if second else 1
                fields = t.second_map() if second else {m.name: m.name for m in t.marks}
                vals = {}
                for c, mark in fields.items():
                    v, m = get(c), t.mark(mark)
                    if v and m.choices:
                        ok = _choice(v, m.choices)
                        if ok is None:
                            res.warnings.append(f"{where} {iid}: invalid {c} '{v}' (allowed: {', '.join(m.choices)}),"
                                                " ignored")
                            continue
                        v = ok
                    if v:
                        vals[mark] = v
                if not vals:
                    res.blanks[(key, slot)] += 1
                    continue
                who = clean_name(get("name") or get("annotator"), aliases) or defaults.get(key, defaults.get("*", ""))
                if not who:
                    res.warnings.append(f"{where} {iid}: marks but no name, skipped (type a name in the 'name' "
                                        "column or pass --default-annotator)")
                    continue
                if t.primary not in vals:
                    res.warnings.append(f"{where} {iid}: {'answer' if second else t.primary} is blank but other "
                                        "columns are filled")
                vals = {"annotator": who, **vals}
                k = (key, iid, slot)
                if k in res.marks and res.marks[k] != vals:
                    res.errors.append(f"{iid} ({key}, {'second' if second else 'first'} mark): different marks in "
                                      f"{seen_from[k]} and {where}")
                    continue
                res.marks[k] = vals
                seen_from[k] = where
    for (key, slot), n in sorted(res.blanks.items()):
        res.warnings.append(f"{key}{' (Second check)' if slot == 2 else ''}: {n} row(s) left blank")
    return res


def _session(res: Result, iid: str, vals: dict, where: str, seen_from: dict) -> None:
    if not any(v for c, v in vals.items() if c != "name"):
        return
    if iid not in U.IDS:
        res.warnings.append(f"{where}: unknown usability row '{iid}', skipped")
        return
    for c, choices in U.CHOICES.items():
        if vals[c]:
            ok = _choice(vals[c], choices)
            if ok is None:
                res.warnings.append(f"{where} {iid}: invalid {c} '{vals[c]}' (allowed: {', '.join(choices)}), ignored")
            vals[c] = ok or ""
    if not vals["tester"]:
        res.warnings.append(f"{where} {iid}: session has answers but no tester name or code")
    missing = [f"sus_{i}" for i in range(1, 11) if not vals[f"sus_{i}"]]
    if 0 < len(missing) < 10:
        res.warnings.append(f"{where} {iid}: SUS incomplete ({', '.join(missing)} blank), no score")
    vals["sus_score"] = U.sus_score(vals)
    k = ("usability", iid)
    if iid in res.sessions and res.sessions[iid] != vals:
        res.errors.append(f"{iid} (usability): different answers in {seen_from[k]} and {where}")
        return
    res.sessions[iid] = vals
    seen_from[k] = where


def _same(c: str, a: str, b: str) -> bool:
    return a.casefold() == b.casefold() if c.startswith("annotator") else a == b


def _put(row: dict, cols: list[str], rows: list[dict], vals: dict, label: str, res: Result) -> None:
    """Fill empty cells; refuse (error) where a filled cell differs."""
    for c, new in vals.items():
        if c not in cols:
            cols.append(c)
            for r in rows:
                r.setdefault(c, "")
        old = row.get(c) or ""
        if new and old and not _same(c, old, new):
            res.errors.append(f"{label}: {c} is already '{old}', refusing to overwrite with '{new}'")
        elif new and not old:
            row[c] = new


def apply(res: Result, tasks: dict[str, Task] = BY_KEY,
          usability_csv: Path = U.CSV) -> dict[Path, tuple[list[str], list[dict]]]:
    """Places marks into the source sheets and usability.csv (in memory). Adds errors for any conflict."""
    out = {}
    for key in dict.fromkeys(k for k, _, _ in sorted(res.marks)):
        t = tasks[key]
        with open(t.source, newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            cols, rows = list(r.fieldnames), list(r)
        by_id = {t.id_fn(row): row for row in rows}
        for (k, iid, slot), vals in sorted(res.marks.items()):
            if k != key:
                continue
            suf = "" if slot == 1 else "_2"
            _put(by_id[iid], cols, rows, {c + suf: v for c, v in vals.items()}, f"{iid} ({key}) in {t.source.name}",
                 res)
        out[t.source] = (cols, rows)
    if res.sessions:
        rows = read_csv(usability_csv) if usability_csv.exists() else []
        cols = list(rows[0]) if rows else list(USABILITY_COLS)
        by_id = {r["item_id"]: r for r in rows}
        for iid, vals in sorted(res.sessions.items()):
            if iid not in by_id:
                by_id[iid] = {"item_id": iid}
                rows.append(by_id[iid])
            _put(by_id[iid], cols, rows, vals, f"{iid} in {usability_csv.name}", res)
        for r in rows:
            for c in cols:
                r.setdefault(c, "")
        out[usability_csv] = (cols, sorted(rows, key=lambda r: r["item_id"]))
    return out


def kappa(pairs: list[tuple[str, str]]) -> tuple[float | None, float | None, int]:
    """Cohen's kappa, percent agreement, n."""
    n = len(pairs)
    if not n:
        return None, None, 0
    po = sum(a == b for a, b in pairs) / n
    c1, c2 = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(c1[k] * c2[k] for k in c1.keys() | c2.keys()) / n ** 2
    return (None if pe == 1 else (po - pe) / (1 - pe)), po, n


def agreement(sheets: dict[Path, tuple[list[str], list[dict]]], tasks: dict[str, Task] = BY_KEY,
              warnings: list[str] | None = None) -> list[dict]:
    def rows_of(t):
        if t.source in sheets:
            return sheets[t.source][1]
        return read_csv(t.source) if t.source.exists() else []
    out = []
    for key, t in tasks.items():
        p, p2 = t.primary, t.primary + "_2"
        pairs, same = [], 0
        for r in rows_of(t):
            if not (r.get(p) and r.get(p2)):
                continue
            if (r.get("annotator") or "").casefold() == (r.get("annotator_2") or "").casefold():
                if warnings is not None:
                    warnings.append(f"{t.id_fn(r)} ({key}): first and second mark are both by "
                                    f"{r.get('annotator')}; left out of kappa")
                same += 1
                continue
            pairs.append((r[p], r[p2]))
        if pairs or same:
            out.append({"what": f"{key}: first vs Second check", "pairs": pairs, "same_person": same})
    if "pharmacist" in tasks and "T5" in tasks:
        t5 = {r["t5_id"]: r.get("mark", "") for r in rows_of(tasks["T5"])}
        pairs = [(r["mark"], t5[r["t5_id"]]) for r in rows_of(tasks["pharmacist"])
                 if r.get("mark") and t5.get(r["t5_id"])]
        if pairs:
            out.append({"what": "pharmacist vs T5 (first mark)", "pairs": pairs})
    for a in out:
        a["kappa"], a["agree"], a["n"] = kappa(a.pop("pairs"))
    return out


def report(res: Result, agree: list[dict], wrote: list[Path], dry: bool) -> str:
    f = lambda x: "n/a" if x is None else f"{x:.2f}"
    per = Counter((k, s, v["annotator"]) for (k, _, s), v in res.marks.items())
    lines = ["# Annotation merge report", "", ("DRY RUN, nothing written." if dry else
             "ABORTED, nothing written." if res.errors else "Written: " + ", ".join(str(p) for p in wrote)), "",
             "## Marks read", "", "| task | mark | name | rows marked |", "|---|---|---|---|"]
    for k, s, w in sorted(per):
        lines.append(f"| {k} | {'first' if s == 1 else 'second check'} | {w} | {per[(k, s, w)]} |")
    for (k, s), n in sorted(res.blanks.items()):
        lines.append(f"| {k} | {'first' if s == 1 else 'second check'} | (blank) | {n} |")
    lines += ["", "## Agreement", "",
              "| comparison | n (different people) | % agree | Cohen's kappa | same person, left out |",
              "|---|---|---|---|---|"]
    lines += [f"| {a['what']} | {a['n']} | {f(a['agree'] * 100 if a['agree'] is not None else None)} | "
              f"{f(a['kappa']) if a['n'] >= MIN_KAPPA_N else f'too few (n < {MIN_KAPPA_N}); ' + f(a['kappa'])} | "
              f"{a.get('same_person', 0)} |" for a in agree] or ["| (no double-marked items yet) | | | | |"]
    lines += ["", ("Kappa pools all pairs of a task (first vs second mark), whoever the two people were; pairs "
              "marked twice by the same person are left out and counted in the last column. With fewer than "
              f"{MIN_KAPPA_N} pairs kappa is shown for reference only."), ""]
    scores = [float(v["sus_score"]) for v in res.sessions.values() if v.get("sus_score")]
    lines += ["## Usability sessions", "", f"{len(res.sessions)} session(s) read; "
              + (f"mean SUS {sum(scores) / len(scores):.1f} (n = {len(scores)})." if scores else "no complete SUS."), ""]
    for title, xs in (("Errors", res.errors), ("Warnings", res.warnings)):
        if xs:
            lines += [f"## {title} ({len(xs)})", ""] + [f"- {x}" for x in xs] + [""]
    return "\n".join(lines)


def merge(inputs: list[Path], tasks: dict[str, Task] = BY_KEY, usability_csv: Path = U.CSV,
          default_annotator: str | dict[str, str] = "", dry_run: bool = False,
          aliases: dict[str, str] | None = None) -> tuple[Result, str]:
    res = read_marks(inputs, tasks, default_annotator, aliases)
    sheets = apply(res, tasks, usability_csv)
    agree = agreement(sheets, tasks, res.warnings)
    wrote = []
    if not res.errors and not dry_run:
        for path, (cols, rows) in sheets.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, cols)
                w.writeheader()
                w.writerows(rows)
            wrote.append(path)
    return res, report(res, agree, wrote, dry_run)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("inputs", nargs="+", type=Path, help="completed .xlsx/.csv files or folders")
    ap.add_argument("--dry-run", action="store_true", help="check and report, write nothing")
    ap.add_argument("--default-annotator", action="append", default=[], metavar="[TASK=]NAME",
                    help="name for marked rows whose name cell is empty, for one task (TASK=NAME) or all (NAME)")
    ap.add_argument("--alias", action="append", default=[], metavar="TYPED=NAME",
                    help="fix a mistyped name, e.g. Jhon=John (case-insensitive, repeatable)")
    ap.add_argument("--usability", type=Path, default=U.CSV, help="where tester sessions go")
    ap.add_argument("--report", type=Path, default=OUT / "merge_report.md")
    a = ap.parse_args(argv)
    defaults, aliases = {}, {}
    for d in a.default_annotator:
        k, _, v = d.partition("=")
        if v and k in BY_KEY:
            defaults[k] = v
        else:
            defaults["*"] = d
    for x in a.alias:
        old, sep, new = x.partition("=")
        if not sep or not old.strip() or not new.strip():
            ap.error(f"--alias needs TYPED=NAME, got '{x}'")
        aliases[old.strip()] = new.strip()
    res, text = merge(a.inputs, BY_KEY, a.usability, defaults, a.dry_run, aliases)
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(text)
    print(text)
    print(f"report -> {a.report}")
    return 1 if res.errors else 0


if __name__ == "__main__":
    sys.exit(main())
