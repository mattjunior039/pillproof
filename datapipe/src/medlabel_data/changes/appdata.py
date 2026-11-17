"""Build the small label-change file shipped with the app.

    cd datapipe && uv run python -m medlabel_data.changes.appdata

Reads the change build (~/waicy-work/data/build/changes) and writes app/data/label_changes.json.
Per drug: how far back the compared history goes, and dated changes in the safety sections with
the old sentence beside the new one, copied from the labels by code. Only changes the current
judge labels "meaning changed" are listed (today the text-similarity baseline; later the
fine-tuned model). Pairs where the whole label moved to the newer FDA format are one event, not
sentence lists. Every change carries the same note, and nothing is phrased as a reason to stop
a medicine. plain_language stays null until a checked model sentence is filled in.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import date

from ..paths import REPO
from .build import OUT
from .judge import SAFETY_NOTE

APP_JSON = REPO / "app" / "data" / "label_changes.json"
FULL_JSON = OUT / "label_changes_full.json"
RECENT_UPDATES = 3
PER_UPDATE = 25
FORMAT_EVENT = ("The whole label was rewritten in the newer FDA label format in this version, so "
                "sentence-by-sentence changes are not listed for it.")


def _change(c: dict) -> dict:
    out = {
        "id": c["id"],
        "date": c["to_published"],
        "effective": c["to_effective"],
        "from_version": c["from_version"],
        "to_version": c["to_version"],
        "section_group": c["group_name"],
        "section": c["section"],
        "kind": c["kind"],
        "old": c["old_text"] or None,
        "new": c["new_text"] or None,
        "plain_language": None,
        "judged_by": "baseline" if c["kind"] in ("altered", "added", "removed") else "section event",
        "note": SAFETY_NOTE,
    }
    if c["kind"].startswith("section_"):
        out["n_sentences"] = c["n_sentences"]
    return out


GROUP_ORDER = ["boxed", "contra", "warnings", "interactions", "patient"]
KIND_ORDER = ["section_added", "section_removed", "altered", "added", "removed"]
_TRADEMARK = re.compile(r"\b(registered )?trademarks? (of|owned by)\b|\bare trademarks\b", re.I)


def build(recent_updates: int = RECENT_UPDATES, per_update: int = PER_UPDATE) -> tuple[dict, dict]:
    """Return (app file, full file). The app file lists sentence pairs only for recent updates."""
    drugs = json.loads((OUT / "drugs.json").read_text())
    pairs = {(p["drug"], p["from_version"], p["to_version"]): p
             for p in map(json.loads, open(OUT / "pairs.jsonl"))}
    by_update = defaultdict(list)
    for line in open(OUT / "candidates.jsonl"):
        c = json.loads(line)
        if c["format_conversion"]:
            continue
        if _TRADEMARK.search((c["old_text"] or "") + " " + (c["new_text"] or "")):
            continue
        if c["kind"].startswith("section_") or c.get("baseline") == "meaning changed":
            by_update[(c["drug"], c["from_version"], c["to_version"])].append(c)

    def rank(c: dict) -> tuple:
        g = GROUP_ORDER.index(c["group"]) if c["group"] in GROUP_ORDER else len(GROUP_ORDER)
        return (g, KIND_ORDER.index(c["kind"]), c["id"])

    head = {"generated": date.today().isoformat(),
            "source": "DailyMed SPL label versions; method in docs/label-changes.md",
            "note": SAFETY_NOTE}
    app = {**head, "listing": f"sentence pairs for the {recent_updates} most recent updates per drug, "
                              f"at most {per_update} per update; older updates are counted only",
           "drugs": {}}
    full = {**head, "drugs": {}}
    for d in drugs:
        updates = []
        for (drug, fv, tv), cs in by_update.items():
            if drug != d["drug"]:
                continue
            p = pairs[(drug, fv, tv)]
            cs.sort(key=rank)
            updates.append({"date": p["to_published"], "effective": cs[0]["to_effective"],
                            "from_version": fv, "to_version": tv, "kind": "changes",
                            "n_changes": len(cs),
                            "by_section": dict(Counter(c["group_name"] for c in cs)),
                            "changes": [_change(c) for c in cs]})
        for fv, tv in d["format_conversions"]:
            p = pairs[(d["drug"], fv, tv)]
            updates.append({"date": p["to_published"], "from_version": fv, "to_version": tv,
                            "kind": "format_rewrite", "text": FORMAT_EVENT, "note": SAFETY_NOTE})
        updates.sort(key=lambda u: (u["date"], u["to_version"]), reverse=True)
        meta = {"brand": d["brand"], "set_id": d["set_id"], "manufacturer": d["manufacturer"],
                "n_versions": d["n_versions"],
                "history_from": {"version": d["earliest"]["version"], "date": d["earliest"]["published"]},
                "latest": {"version": d["latest"]["version"], "date": d["latest"]["published"]},
                "n_changes": sum(u.get("n_changes", 0) for u in updates)}
        full["drugs"][d["drug"]] = {**meta, "updates": updates}
        short, seen = [], 0
        for u in updates:
            u = dict(u)
            if u["kind"] == "changes":
                seen += 1
                u["changes"] = u["changes"][:per_update] if seen <= recent_updates else []
                u["n_listed"] = len(u["changes"])
            short.append(u)
        app["drugs"][d["drug"]] = {**meta, "updates": short}
    return app, full


def main() -> None:
    app, full = build()
    APP_JSON.parent.mkdir(parents=True, exist_ok=True)
    APP_JSON.write_text(json.dumps(app, ensure_ascii=False, separators=(",", ":")))
    FULL_JSON.write_text(json.dumps(full, ensure_ascii=False, separators=(",", ":")))
    n = sum(v["n_changes"] for v in app["drugs"].values())
    listed = sum(u.get("n_listed", 0) for v in app["drugs"].values() for u in v["updates"])
    print(f"{n} changes over {len(app['drugs'])} drugs, {listed} listed -> {APP_JSON} "
          f"({APP_JSON.stat().st_size // 1024} KB); full list -> {FULL_JSON}")


if __name__ == "__main__":
    main()
