"""Merge completed annotation files back into the original sheets.

    uv run python -m medlabel_data.annotation.merge ~/waicy-work/data/build/annotation/split [--dry-run]

Reads per-person workbooks, the master downloaded back from Google Sheets (.xlsx), or its tab CSVs
(files or folders; folders are not searched recursively). Every tab whose header has item_id and
task is read. Marks go into the source sheet of each task (t5_sheet.csv, t3_draft.csv, ...) with
an `annotator` column; a second annotator of a double-marked item goes into `annotator_2` and
`<mark>_2`. Existing marks are never overwritten: any disagreement with a filled cell aborts the
whole merge with nothing written. Blank and invalid marks are reported. Agreement (Cohen's kappa)
is computed over double-marked items, and pharmacist vs T5.
"""

import argparse
import csv
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

from openpyxl import load_workbook

from .tasks import BY_KEY, OUT, Task, read_csv


@dataclass
class Result:
    marks: dict = field(default_factory=dict)       # (task, item_id, annotator) -> {mark: value}
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    blanks: Counter = field(default_factory=Counter)  # (task, annotator) -> rows with no marks


def _norm(s) -> str:
    return " ".join(str(s).replace("_", " ").split()).casefold()


def _tables(path: Path):
    """Yields (source name, header, rows) for every table in a file."""
    if path.suffix.lower() == ".xlsx":
        wb = load_workbook(path, read_only=True, data_only=True)
        for ws in wb.worksheets:
            it = ws.iter_rows(values_only=True)
            header = next(it, None)
            if header:
                header = ["" if h is None else str(h).strip() for h in header]
                yield f"{path.name}:{ws.title}", header, [["" if v is None else v for v in r] for r in it]
        wb.close()
    elif path.suffix.lower() == ".csv":
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
        if rows:
            yield path.name, [h.strip() for h in rows[0]], rows[1:]


def _cell(row: list, col: dict[str, int], c: str) -> str:
    i = col.get(c)
    return "" if i is None or i >= len(row) or row[i] is None else str(row[i]).strip()


def _files(inputs: list[Path]) -> list[Path]:
    out = []
    for p in inputs:
        p = p.expanduser()
        if p.is_dir():
            out += sorted(q for q in p.iterdir() if q.suffix.lower() in (".xlsx", ".csv") and not q.name.startswith(("~", ".")))
        elif p.exists():
            out.append(p)
        else:
            raise SystemExit(f"not found: {p}")
    return out


def read_marks(inputs: list[Path], tasks: dict[str, Task] = BY_KEY, default_annotator: str = "") -> Result:
    res = Result()
    known = {k: {t.id_fn(r) for r in read_csv(t.source)} for k, t in tasks.items()}
    seen_from = {}
    for path in _files(inputs):
        for src, header, rows in _tables(path):
            if "item_id" not in header or "task" not in header:
                continue
            col = {h: i for i, h in enumerate(header)}
            for n, row in enumerate(rows, 2):
                get = partial(_cell, row, col)
                key, iid = get("task"), get("item_id")
                if not key and not iid:
                    continue
                t = tasks.get(key)
                where = f"{src} row {n}"
                if t is None:
                    res.warnings.append(f"{where}: unknown task '{key}', skipped")
                    continue
                if iid not in known[key]:
                    res.warnings.append(f"{where}: unknown item_id '{iid}' for {key}, skipped")
                    continue
                vals = {}
                for m in t.marks:
                    v = get(m.name)
                    if v and m.choices:
                        match = [c for c in m.choices if _norm(c) == _norm(v)]
                        if not match:
                            res.warnings.append(f"{where} {iid}: invalid {m.name} '{v}' (allowed: "
                                                f"{', '.join(m.choices)}), ignored")
                            continue
                        v = match[0]
                    if v:
                        vals[m.name] = v
                who = get("annotator") or default_annotator
                if not vals:
                    res.blanks[(key, who or "?")] += 1
                    continue
                if not who:
                    res.warnings.append(f"{where} {iid}: marks but no annotator name, skipped "
                                        "(fill 'annotator' or pass --default-annotator)")
                    continue
                if t.primary not in vals:
                    res.warnings.append(f"{where} {iid}: {t.primary} is blank but other columns are filled")
                k = (key, iid, who)
                if k in res.marks and res.marks[k] != vals:
                    res.errors.append(f"{iid} ({key}, {who}): different marks in {seen_from[k]} and {where}")
                    continue
                res.marks[k] = vals
                seen_from[k] = where
    for (key, who), n in sorted(res.blanks.items()):
        res.warnings.append(f"{key}, {who}: {n} row(s) left blank")
    return res


def _slot_cols(t: Task, s: int) -> tuple[str, list[str]]:
    suf = "" if s == 1 else f"_{s}"
    return "annotator" + suf, [m.name + suf for m in t.marks]


def apply(res: Result, tasks: dict[str, Task] = BY_KEY) -> dict[Path, tuple[list[str], list[dict]]]:
    """Places marks into the source sheets (in memory). Adds errors for any conflict."""
    out = {}
    by_task = defaultdict(list)
    for (key, iid, who), vals in sorted(res.marks.items()):
        by_task[key].append((iid, who, vals))
    for key, marks in by_task.items():
        t = tasks[key]
        with open(t.source, newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            cols, rows = list(r.fieldnames), list(r)
        by_id = {t.id_fn(row): row for row in rows}
        for iid, who, vals in marks:
            row = by_id[iid]
            slot = None
            for s in (1, 2):
                a, _ = _slot_cols(t, s)
                if row.get(a, "") == who:
                    slot = s
                    break
            if slot is None:
                for s in (1, 2):
                    a, ms = _slot_cols(t, s)
                    filled = any(row.get(c, "") for c in ms)
                    if not row.get(a, "") and not filled:
                        slot = s
                        break
                    if not row.get(a, "") and all(row.get(c, "") in ("", vals.get(m.name, ""))
                                                  for m, c in zip(t.marks, ms)):
                        res.warnings.append(f"{iid} ({key}): existing unattributed marks match {who}'s; "
                                            f"attributed to {who}")
                        slot = s
                        break
                    if not row.get(a, ""):
                        res.warnings.append(f"{iid} ({key}): has unattributed marks that differ from {who}'s; "
                                            "they are kept as a separate mark")
            if slot is None:
                res.errors.append(f"{iid} ({key}): no free slot for {who} (already marked by "
                                  f"{row.get('annotator') or '?'} and {row.get('annotator_2') or '?'})")
                continue
            a, ms = _slot_cols(t, slot)
            for c in [a] + ms:
                if c not in cols:
                    cols.append(c)
                    for rr in rows:
                        rr.setdefault(c, "")
            for m, c in zip(t.marks, ms):
                new, old = vals.get(m.name, ""), row.get(c, "")
                if new and old and new != old:
                    res.errors.append(f"{iid} ({key}, {who}): {c} is already '{old}' in {t.source.name}, "
                                      f"refusing to overwrite with '{new}'")
                elif new:
                    row[c] = new
            row[a] = who
        out[t.source] = (cols, rows)
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


def agreement(sheets: dict[Path, tuple[list[str], list[dict]]], tasks: dict[str, Task] = BY_KEY) -> list[dict]:
    def rows_of(t):
        if t.source in sheets:
            return sheets[t.source][1]
        return read_csv(t.source) if t.source.exists() else []
    out = []
    for key, t in tasks.items():
        p2 = t.primary + "_2"
        pairs = [(r[t.primary], r[p2]) for r in rows_of(t) if r.get(t.primary) and r.get(p2)]
        if pairs:
            out.append({"what": f"{key}: double-marked", "pairs": pairs})
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
    per = Counter((k, w) for k, _, w in res.marks)
    lines = ["# Annotation merge report", "", ("DRY RUN, nothing written." if dry else
             "ABORTED, nothing written." if res.errors else "Written: " + ", ".join(str(p) for p in wrote)), "",
             "## Marks read", "", "| task | annotator | marked | blank |", "|---|---|---|---|"]
    for k, w in sorted(set(per) | set(res.blanks)):
        lines.append(f"| {k} | {w} | {per[(k, w)]} | {res.blanks[(k, w)]} |")
    lines += ["", "## Agreement", "", "| comparison | n | % agree | Cohen's kappa |", "|---|---|---|---|"]
    lines += [f"| {a['what']} | {a['n']} | {f(a['agree'] * 100 if a['agree'] is not None else None)} | "
              f"{f(a['kappa'])} |" for a in agree] or ["| (no double-marked items yet) | | | |"]
    lines += ["", "Kappa pools all pairs of a task (first vs second mark), whoever the two annotators were.", ""]
    for title, xs in (("Errors", res.errors), ("Warnings", res.warnings)):
        if xs:
            lines += [f"## {title} ({len(xs)})", ""] + [f"- {x}" for x in xs] + [""]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("inputs", nargs="+", type=Path, help="completed .xlsx/.csv files or folders")
    ap.add_argument("--dry-run", action="store_true", help="check and report, write nothing")
    ap.add_argument("--default-annotator", default="", help="name for rows whose annotator cell is empty")
    ap.add_argument("--report", type=Path, default=OUT / "merge_report.md")
    a = ap.parse_args(argv)
    res = read_marks(a.inputs, default_annotator=a.default_annotator)
    sheets = apply(res)
    plan = OUT / "split" / "assignments.csv"
    if plan.exists():
        planned = {(r["task"], r["item_id"], r["annotator"]) for r in read_csv(plan)}
        for k in res.marks:
            if k not in planned:
                res.warnings.append(f"{k[1]} ({k[0]}): marked by {k[2]}, who was not assigned it")
    wrote = []
    if not res.errors and not a.dry_run:
        for path, (cols, rows) in sheets.items():
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, cols)
                w.writeheader()
                w.writerows(rows)
            wrote.append(path)
    text = report(res, agreement(sheets), wrote, a.dry_run)
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(text)
    print(text)
    print(f"report -> {a.report}")
    return 1 if res.errors else 0


if __name__ == "__main__":
    sys.exit(main())
