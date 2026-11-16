"""Split FDARxBench labels into train/dev/test with no shared active ingredient.

Labels and ingredients form a bipartite graph; each connected component (labels that
share any ingredient, transitively) goes wholly into one split. Components are visited
in a seeded random order and each goes to the split furthest below its target share of
QA items. Combination products therefore pull all their ingredients' labels together
(e.g. every acetaminophen/aspirin/caffeine OTC label lands in one split).

Output: BUILD/fdarx/split.json
  {"seed", "targets", "labels": {set_id: split}, "ingredients": {ingredient: split}, "stats": {...}}
"""

import json
import random
from collections import Counter, defaultdict

from .. import paths
from .ingredients import OUT as INGREDIENTS

OUT = paths.BUILD / "fdarx" / "split.json"
TARGETS = {"train": 0.70, "dev": 0.10, "test": 0.20}
SEED = 2026


def components(label_ings: dict[str, list[str]]) -> list[list[str]]:
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for sid, ings in label_ings.items():
        find("L:" + sid)
        for i in ings:
            parent[find("L:" + sid)] = find("I:" + i)
    groups: dict[str, list[str]] = defaultdict(list)
    for sid in label_ings:
        groups[find("L:" + sid)].append(sid)
    return [sorted(g) for g in groups.values()]


def assign(comps: list[list[str]], weight: dict[str, int], targets=TARGETS, seed=SEED) -> dict[str, str]:
    comps = sorted(comps)
    random.Random(seed).shuffle(comps)
    total = sum(weight.get(s, 0) for c in comps for s in c) or 1
    filled = Counter()
    out = {}
    for c in comps:
        w = sum(weight.get(s, 0) for s in c)
        split = max(targets, key=lambda k: targets[k] - filled[k] / total)
        filled[split] += w
        for s in c:
            out[s] = split
    return out


def main() -> None:
    info = json.loads(INGREDIENTS.read_text())
    label_ings = {s: v["ingredients"] for s, v in info.items() if v["ingredients"]}
    excluded = sorted(set(info) - set(label_ings))
    qcount = Counter(json.loads(l)["set_id"] for l in open(paths.FDARX_QA))
    comps = components(label_ings)
    lab_split = assign(comps, qcount)

    ing_split: dict[str, str] = {}
    for s, ings in label_ings.items():
        for i in ings:
            assert ing_split.setdefault(i, lab_split[s]) == lab_split[s], f"ingredient overlap: {i}"

    items = Counter()
    for s, sp in lab_split.items():
        items[sp] += qcount[s]
    stats = {
        sp: {
            "labels": sum(1 for v in lab_split.values() if v == sp),
            "ingredients": sum(1 for v in ing_split.values() if v == sp),
            "components": sum(1 for c in comps if lab_split[c[0]] == sp),
            "qa_items": items[sp],
        }
        for sp in TARGETS
    }
    stats["excluded_labels"] = excluded
    OUT.write_text(json.dumps(
        {"seed": SEED, "targets": TARGETS, "labels": lab_split, "ingredients": ing_split, "stats": stats},
        indent=1, ensure_ascii=False,
    ))
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
