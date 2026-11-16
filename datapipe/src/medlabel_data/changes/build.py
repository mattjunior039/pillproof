"""Run the label-change alignment for every T3/T5 drug and write the candidate list.

    cd datapipe && uv run python -m medlabel_data.changes.build

Writes to <data>/build/changes/:
    candidates.jsonl  one line per candidate (sentence change or whole-section event)
    pairs.jsonl       one line per consecutive version pair with alignment counts
    drugs.json        per-drug summary: versions, history depth, counts
"""

import hashlib
import json
from collections import Counter

from ..paths import BUILD
from .align import align_versions
from .baseline import baseline_label
from .extract import GROUPS, drug_list, load_drug

OUT = BUILD / "changes"
SENTENCE_KINDS = ("altered", "added", "removed")


def cand_id(drug: str, va: int, vb: int, kind: str, old: str, new: str, where: str = "") -> str:
    h = hashlib.sha1(f"{drug}|{va}|{vb}|{kind}|{old}|{new}|{where}".encode()).hexdigest()
    return f"c{h[:10]}"


def drug_records(d: dict) -> tuple[list[dict], list[dict], dict]:
    man, versions = load_drug(d["ingredient"])
    res = man.get("resolved", {})
    cands, pairs = [], []
    for a, b in zip(versions, versions[1:]):
        r = align_versions(a, b)
        pairs.append({"drug": d["ingredient"], "from_version": a.version, "to_version": b.version,
                      "from_published": a.published, "to_published": b.published,
                      "format_conversion": r.format_conversion, **dict(r.stats)})
        for c in r.candidates:
            units = c.new or c.old
            rec = {
                "id": cand_id(d["ingredient"], a.version, b.version, c.kind, c.old_text, c.new_text,
                              f"{c.group}:{units[0].pos}"),
                "drug": d["ingredient"],
                "brand": d.get("brand"),
                "set_id": man["set_id"],
                "from_version": a.version, "to_version": b.version,
                "from_published": a.published, "to_published": b.published,
                "to_effective": b.effective,
                "format_conversion": r.format_conversion,
                "group": c.group, "group_name": GROUPS[c.group],
                "section": units[0].section,
                "kind": c.kind,
                "old_text": c.old_text, "new_text": c.new_text,
                "closest_text": c.closest.text if c.closest else None,
                "similarity": round(c.similarity, 4),
                "n_sentences": len(units),
            }
            if c.kind in SENTENCE_KINDS:
                rec["baseline"] = baseline_label(c.similarity)
            cands.append(rec)
    kinds = Counter(c["kind"] for c in cands)
    summary = {
        "drug": d["ingredient"], "brand": d.get("brand"), "set_id": man["set_id"],
        "label_title": res.get("brand_name"), "manufacturer": res.get("manufacturer"),
        "n_versions": len(versions),
        "earliest": {"version": versions[0].version, "published": versions[0].published,
                     "format": versions[0].fmt} if versions else None,
        "latest": {"version": versions[-1].version, "published": versions[-1].published,
                   "effective": versions[-1].effective, "format": versions[-1].fmt} if versions else None,
        "n_pairs": len(pairs),
        "n_pairs_changed": sum(1 for p in pairs if any(p.get(k) for k in (*SENTENCE_KINDS, "section_added", "section_removed"))),
        "format_conversions": [[p["from_version"], p["to_version"]] for p in pairs if p["format_conversion"]],
        "candidates": dict(kinds),
        "candidates_outside_conversions": dict(Counter(c["kind"] for c in cands if not c["format_conversion"])),
        "baseline_meaning_changed": sum(1 for c in cands if c.get("baseline") == "meaning changed"
                                        and not c["format_conversion"]),
        "systematic_dropped": sum(p.get("systematic", 0) for p in pairs),
    }
    return cands, pairs, summary


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    all_c, all_p, summaries = [], [], []
    for d in drug_list():
        c, p, s = drug_records(d)
        all_c += c
        all_p += p
        summaries.append(s)
        print(f"{d['ingredient']:20} versions={s['n_versions']:3} changed_pairs={s['n_pairs_changed']:3} "
              f"candidates={len(c):4} {s['candidates']}")
    ids = [c["id"] for c in all_c]
    assert len(ids) == len(set(ids)), "candidate id collision"
    with open(OUT / "candidates.jsonl", "w") as f:
        for c in all_c:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    with open(OUT / "pairs.jsonl", "w") as f:
        for p in all_p:
            f.write(json.dumps(p) + "\n")
    (OUT / "drugs.json").write_text(json.dumps(summaries, indent=1, ensure_ascii=False))
    print(f"{len(all_c)} candidates -> {OUT}")
    print(dict(Counter(c["kind"] for c in all_c)))


if __name__ == "__main__":
    main()
