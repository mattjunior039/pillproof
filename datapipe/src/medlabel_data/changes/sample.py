"""Draw the development sample (for Gate 3 and the baseline threshold) and the T5 marking sheet.

    cd datapipe && uv run python -m medlabel_data.changes.sample dev   # development sample
    cd datapipe && uv run python -m medlabel_data.changes.sample t5    # T5 + pharmacist sheets

Both draw from sentence-level candidates (altered, added, removed) outside format-conversion
pairs (old format -> PLR rewrites, see docs/label-changes.md). The development sample is a
simple random sample; I mark it myself, and it is kept out of T5. T5 is spread across drugs and
change types; the user marks it before any model sees it. The sheets show no baseline label and
no similarity score, and items are in random order.
"""

import csv
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

from ..paths import REPO
from .build import OUT, SENTENCE_KINDS

DEV_N = 80
DEV_SEED = 20261121
T5_N = 150
T5_SEED = 5
PHARM_N = 30
PHARM_SEED = 30
PAIR_CAP = 3  # at most this many T5 items from one version pair of one drug, while others remain
DEV_MARKS = REPO / "datapipe" / "eval" / "changes_dev_marks.csv"
T5_DIR = OUT / "t5"

SHEET_COLS = ["t5_id", "drug", "section", "change_type", "old_sentence", "new_sentence",
              "closest_sentence_other_version", "mark", "only_formatting", "notes"]
MARK_HELP = ('mark: write "meaning changed" or "reworded". For a changed sentence, "reworded" means '
             'the old and new sentence say the same thing. For an added or removed sentence, '
             '"reworded" means the same information is still in the other version (for example in '
             'the closest sentence shown); "meaning changed" means information was really added or '
             'taken away. only_formatting: write "y" if nothing but formatting differs (punctuation, '
             'bullets, numbering, spacing, a heading glued on). notes: optional.')


def load_candidates() -> list[dict]:
    with open(OUT / "candidates.jsonl") as f:
        return [json.loads(line) for line in f]


def pool(cands: list[dict]) -> list[dict]:
    return [c for c in cands if c["kind"] in SENTENCE_KINDS and not c["format_conversion"]]


def stratum(c: dict) -> str:
    if c["kind"] == "altered":
        return "altered_close" if c["similarity"] >= 0.85 else "altered_far"
    return c["kind"]


def dev_sample() -> None:
    p = pool(load_candidates())
    rng = random.Random(DEV_SEED)
    picked = rng.sample(p, DEV_N)
    DEV_MARKS.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if DEV_MARKS.exists():
        with open(DEV_MARKS) as f:
            existing = {r["id"]: r for r in csv.DictReader(f)}
    cols = ["id", "drug", "from_version", "to_version", "section", "kind", "similarity",
            "old_text", "new_text", "closest_text", "dev_mark", "dev_note"]
    with open(DEV_MARKS, "w", newline="") as f:
        w = csv.DictWriter(f, cols)
        w.writeheader()
        for c in picked:
            row = {k: c.get(k) for k in cols if k in c}
            row["dev_mark"] = existing.get(c["id"], {}).get("dev_mark", "")
            row["dev_note"] = existing.get(c["id"], {}).get("dev_note", "")
            w.writerow(row)
    print(f"dev sample of {len(picked)} from {len(p)} -> {DEV_MARKS}")


def dev_ids() -> set[str]:
    with open(DEV_MARKS) as f:
        return {r["id"] for r in csv.DictReader(f)}


def t5_sample(cands: list[dict], exclude: set[str]) -> list[dict]:
    """Round-robin over drugs; inside a drug, round-robin over strata (altered_close,
    altered_far, added, removed), random order inside a stratum, at most PAIR_CAP items per
    version pair until a drug runs out of other pairs."""
    rng = random.Random(T5_SEED)
    by_drug: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for c in pool(cands):
        if c["id"] not in exclude:
            by_drug[c["drug"]][stratum(c)].append(c)
    for strata in by_drug.values():
        for lst in strata.values():
            rng.shuffle(lst)
    order = {d: [s for s in ("altered_close", "altered_far", "added", "removed") if strata.get(s)]
             for d, strata in by_drug.items()}
    turn = Counter()
    per_pair = Counter()
    picked: list[dict] = []
    drugs = sorted(by_drug)
    while len(picked) < T5_N and any(any(by_drug[d].values()) for d in drugs):
        for d in drugs:
            if len(picked) >= T5_N:
                break
            strata = by_drug[d]
            live = [s for s in order[d] if strata[s]]
            if not live:
                continue
            s = live[turn[d] % len(live)]
            turn[d] += 1
            lst = strata[s]
            idx = next((i for i, c in enumerate(lst)
                        if per_pair[(d, c["from_version"], c["to_version"])] < PAIR_CAP), 0)
            c = lst.pop(idx)
            per_pair[(d, c["from_version"], c["to_version"])] += 1
            picked.append(c)
    return picked


def _sheet_row(t5_id: str, c: dict) -> dict:
    return {
        "t5_id": t5_id, "drug": c["drug"], "section": f'{c["group_name"]}: {c["section"]}',
        "change_type": {"altered": "sentence changed", "added": "sentence added",
                        "removed": "sentence removed"}[c["kind"]],
        "old_sentence": c["old_text"], "new_sentence": c["new_text"],
        "closest_sentence_other_version": c["closest_text"] or "" if c["kind"] != "altered" else "",
        "mark": "", "only_formatting": "", "notes": "",
    }


def _write_sheet(path: Path, rows: list[dict], title: str, extra_cols: list[str] = ()) -> None:
    cols = SHEET_COLS + list(extra_cols)
    with open(path.with_suffix(".csv"), "w", newline="") as f:
        w = csv.DictWriter(f, cols)
        w.writeheader()
        for r in rows:
            w.writerow({**{k: "" for k in extra_cols}, **r})
    lines = [f"# {title}", "", MARK_HELP, "",
             "Fill in the marks in the CSV file next to this one. This Markdown copy is for reading.", ""]
    for r in rows:
        lines += [f"## {r['t5_id']} | {r['drug']} | {r['section']} | {r['change_type']}", ""]
        if r["old_sentence"]:
            lines.append(f"- **Old:** {r['old_sentence']}")
        if r["new_sentence"]:
            lines.append(f"- **New:** {r['new_sentence']}")
        if r["closest_sentence_other_version"]:
            side = "old" if r["change_type"] == "sentence added" else "new"
            lines.append(f"- *Closest sentence in the {side} version:* {r['closest_sentence_other_version']}")
        lines += ["- Mark: ______________________", ""]
    path.with_suffix(".md").write_text("\n".join(lines))


def write_t5() -> None:
    cands = load_candidates()
    picked = t5_sample(cands, dev_ids())
    rng = random.Random(T5_SEED + 1)
    rng.shuffle(picked)
    pop = Counter((c["drug"], stratum(c)) for c in pool(cands))
    got = Counter((c["drug"], stratum(c)) for c in picked)
    T5_DIR.mkdir(parents=True, exist_ok=True)
    rows, key = [], []
    for i, c in enumerate(picked, 1):
        tid = f"T5-{i:03d}"
        rows.append(_sheet_row(tid, c))
        st = (c["drug"], stratum(c))
        key.append({"t5_id": tid, "id": c["id"], "drug": c["drug"], "stratum": st[1],
                    "weight": round(pop[st] / got[st], 4)})
    if (T5_DIR / "t5_sheet.csv").exists():
        sys.exit(f"{T5_DIR / 't5_sheet.csv'} exists; refusing to overwrite a marking sheet")
    _write_sheet(T5_DIR / "t5_sheet", rows, "T5 label-change marking sheet")
    with open(T5_DIR / "t5_key_hidden.jsonl", "w") as f:
        for k in key:
            f.write(json.dumps(k) + "\n")
    # pharmacist subset: spread across drugs, random within drug
    rng = random.Random(PHARM_SEED)
    by_drug = defaultdict(list)
    for r in rows:
        by_drug[r["drug"]].append(r)
    for lst in by_drug.values():
        rng.shuffle(lst)
    pharm: list[dict] = []
    while len(pharm) < PHARM_N and any(by_drug.values()):
        for d in sorted(by_drug):
            if by_drug[d] and len(pharm) < PHARM_N:
                pharm.append(by_drug[d].pop())
    pharm.sort(key=lambda r: r["t5_id"])
    _write_sheet(T5_DIR / "pharmacist_sheet", pharm,
                 "Pharmacist check: label-change pairs (subset of T5)",
                 ["plain_language_line", "plain_language_accurate"])
    print(f"T5: {len(rows)} items over {len(by_drug)} drugs -> {T5_DIR}")
    print("per drug:", dict(sorted(Counter(r["drug"] for r in rows).items())))
    print("per type:", dict(Counter(stratum(c) for c in picked)))
    print(f"pharmacist subset: {len(pharm)} items, drugs {dict(Counter(r['drug'] for r in pharm))}")


if __name__ == "__main__":
    {"dev": dev_sample, "t5": write_t5}[sys.argv[1]]()
