"""Split the annotation work between people: one workbook each, balanced and drug-stratified,
with a share of items double-assigned to measure agreement.

    uv run python -m medlabel_data.annotation.split --annotators "Ana,Ben,Cy" [--pharmacist "Dr Lee"]

Algorithm (per task, seed 2026 by default): items are grouped by drug (drugs sorted), and shuffled
within each drug with random.Random(f"{seed}:{task}:{drug}"). Walking that order, each item goes to
the least-loaded annotator (ties broken by a seeded per-task order), so every person gets a similar
number of items and a similar mix of drugs. The double-marked set is a systematic sample of that
order (k = share * N rounded half up, positions floor(i * N / k)), so doubles are spread over drugs;
each double gets a second, different, least-loaded annotator. Each person sees the row only in
their own file and never sees the other mark.
"""

import argparse
import csv
import json
import random
from collections import defaultdict
from pathlib import Path

from . import workbook
from .tasks import BY_KEY, OUT, TASKS, Task, decline_label_rows

SEED = 2026


def assign(items: list[dict], annotators: list[str], seed: int = SEED, double: float = 0.0,
           key: str = "") -> dict[str, list[str]]:
    """item_id -> annotators (one, or two for double-marked items)."""
    if not annotators:
        raise ValueError("no annotators")
    by_drug = defaultdict(list)
    for it in items:
        by_drug[it.get("drug", "")].append(it["item_id"])
    order = []
    for drug in sorted(by_drug):
        ids = sorted(by_drug[drug])
        random.Random(f"{seed}:{key}:{drug}").shuffle(ids)
        order += ids
    n = len(order)
    k = int(double * n + 0.5) if len(annotators) > 1 else 0
    doubles = {order[i * n // k] for i in range(k)} if k else set()
    tie = list(annotators)
    random.Random(f"{seed}:{key}:order").shuffle(tie)
    rank = {a: i for i, a in enumerate(tie)}
    load = dict.fromkeys(annotators, 0)
    out = {}
    for iid in order:
        first = min(annotators, key=lambda a: (load[a], rank[a]))
        load[first] += 1
        out[iid] = [first]
        if iid in doubles:
            second = min((a for a in annotators if a != first), key=lambda a: (load[a], rank[a]))
            load[second] += 1
            out[iid].append(second)
    return out


def make_plan(items: dict[str, list[dict]], tasks: list[Task], annotators: list[str], pharmacist: str | None,
              seed: int = SEED, double: dict[str, float] | None = None) -> list[dict]:
    """Rows of (item_id, task, annotator, double)."""
    rows = []
    for t in tasks:
        if not items.get(t.key):
            continue
        if not t.split:
            if pharmacist:
                rows += [{"item_id": it["item_id"], "task": t.key, "annotator": pharmacist, "double": 0}
                         for it in items[t.key]]
            continue
        share = (double or {}).get(t.key, t.double)
        for iid, who in assign(items[t.key], annotators, seed, share, t.key).items():
            rows += [{"item_id": iid, "task": t.key, "annotator": a, "double": int(len(who) > 1)} for a in who]
    return rows


def summary(plan: list[dict], tasks: list[Task], who: str | None = None) -> list[dict]:
    out = []
    for t in tasks:
        for a in dict.fromkeys(p["annotator"] for p in plan if p["task"] == t.key):
            if who and a != who:
                continue
            mine = [p for p in plan if p["task"] == t.key and p["annotator"] == a]
            out.append({"annotator": a, "task": t.key, "item_ids": [p["item_id"] for p in mine],
                        "double": sum(p["double"] for p in mine)})
    return out


def write_person(path: Path, name: str, tasks: list[Task], items: dict[str, list[dict]], plan: list[dict],
                 due: str = workbook.DUE, with_labels: bool = True) -> int:
    mine = {(p["task"], p["item_id"]) for p in plan if p["annotator"] == name}
    rows = {t.key: [{**it, "annotator": name} for it in items.get(t.key, []) if (t.key, it["item_id"]) in mine]
            for t in tasks}
    ref = decline_label_rows(rows.get("decline", [])) if with_labels and rows.get("decline") else None
    workbook.write(path, tasks, rows, [name], summary(plan, tasks, name), ref, due=due)
    return len(mine)


def safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name.strip())


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--annotators", required=True, help='comma-separated names, e.g. "Ana,Ben,Cy"')
    ap.add_argument("--pharmacist", default="Pharmacist", help="name for the expert-only tab ('' to leave it out)")
    ap.add_argument("--tasks", default=",".join(t.key for t in TASKS if t.split),
                    help="tasks to split (default: all except pharmacist)")
    ap.add_argument("--double", default="", help="override double shares, e.g. 'T5=0.2,T3=0.15'")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--due", default=workbook.DUE)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    names = [n.strip() for n in a.annotators.split(",") if n.strip()]
    if len(set(names)) != len(names):
        raise SystemExit("annotator names must be unique")
    if a.pharmacist in names:
        raise SystemExit("the pharmacist must not also be a regular annotator")
    keys = [k.strip() for k in a.tasks.split(",") if k.strip()]
    unknown = [k for k in keys if k not in BY_KEY]
    if unknown:
        raise SystemExit(f"unknown tasks {unknown}; choose from {list(BY_KEY)}")
    double = {k: float(v) for k, v in (kv.split("=") for kv in a.double.split(",") if kv)}
    tasks = [t for t in TASKS if t.key in keys or (not t.split and a.pharmacist)]
    items = {t.key: t.load() for t in tasks}
    plan = make_plan(items, tasks, names, a.pharmacist or None, a.seed, double)

    split_dir = a.out / "split"
    split_dir.mkdir(parents=True, exist_ok=True)
    for old in split_dir.glob("annotation_*.xlsx"):
        old.unlink()
    with open(split_dir / "assignments.csv", "w", newline="") as f:
        w = csv.DictWriter(f, ["item_id", "task", "annotator", "double"])
        w.writeheader()
        w.writerows(plan)
    (split_dir / "plan.json").write_text(json.dumps(
        {"seed": a.seed, "annotators": names, "pharmacist": a.pharmacist, "tasks": keys,
         "double": {t.key: double.get(t.key, t.double) for t in tasks if t.split}, "due": a.due}, indent=2) + "\n")
    people = names + ([a.pharmacist] if a.pharmacist else [])
    for name in people:
        n = write_person(split_dir / f"annotation_{safe(name)}.xlsx", name, tasks, items, plan, a.due)
        print(f"{name}: {n} items -> {split_dir / f'annotation_{safe(name)}.xlsx'}")

    all_items = {t.key: t.load() for t in TASKS}
    workbook.write(a.out / "annotation_master.xlsx", TASKS, all_items, people,
                   summary(plan, TASKS), decline_label_rows(all_items["decline"]), a.out / "csv", a.due)
    for t in tasks:
        if t.split:
            d = sum(p["double"] for p in plan if p["task"] == t.key) // 2
            print(f"{t.key}: {len(items[t.key])} items, {d} double-marked")
    print(f"plan -> {split_dir / 'assignments.csv'}; master -> {a.out / 'annotation_master.xlsx'}")


if __name__ == "__main__":
    main()
