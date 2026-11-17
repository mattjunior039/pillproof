"""Line up the safety sentences of two consecutive label versions and list the candidates.

For each version pair, inside each safety group:

1. **Same text.** Sentences with equal comparison keys (normalize.py) are matched, as a
   multiset, regardless of position. Moving a sentence to another subsection, renumbering
   subsections and reformatting are therefore not changes.
2. **Moved between groups.** Leftover sentences whose key appears unmatched in another group
   of the other version are matched as moves (for example Drug Interactions text that moved
   from PRECAUTIONS into WARNINGS).
3. **Split or merged.** A leftover sentence whose key equals the joined keys of 2-6
   consecutive sentences on the other side (a sentence split into a bullet list, or two
   sentences joined) is matched. Then, among leftovers only, a sentence is matched to a run
   of 2-4 consecutive leftovers on the other side if their joined text is nearly identical
   (token similarity >= SPLIT_SIM); this is recorded as an altered pair with the run joined.
4. **Closest sentence.** Remaining old and new sentences are paired greedily by token
   similarity (difflib ratio on key tokens), best first, if similarity >= PAIR_MIN. These are
   *altered* candidates.
5. Unpaired new sentences are *added*; unpaired old sentences are *removed*. Each keeps its
   closest sentence on the other side of the same group as context. An added or removed
   sentence whose key equals a sentence on the other side (a statement repeated, or a repeat
   dropped) is counted as *repeat* and not listed.
6. **Label-wide edits.** An altered pair is dropped when every edit in it is a benign word
   substitution made in at least SYSTEMATIC_MIN sentences of the same version pair (for example
   "tramadol hydrochloride" -> "tramadol hydrochloride tablets"). Edits that touch a number or
   a meaning word (MEANING_WORDS: negations, modals, quantities, comparisons) are never benign.
7. **Whole sections.** When at least BLOCK_MIN added sentences share one subsection title and
   make up at least BLOCK_SHARE of that subsection in the new version, they are collapsed into
   one *section_added* event (same for removed sentences and *section_removed*). A new
   patient leaflet or a new warning subsection is one event, not 120 candidates.

A pair whose versions differ in label format (old format vs. PLR format) is marked
`format_conversion`: the whole label was rewritten and reorganized.

Similarity is `difflib.SequenceMatcher(None, a_tokens, b_tokens).ratio()` on key tokens.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .extract import GROUPS, Unit, Version

PAIR_MIN = 0.5
SPLIT_SIM = 0.9
MAX_RUN = 6
BLOCK_MIN = 5
BLOCK_SHARE = 0.8


def sim(a: str, b: str) -> float:
    if a == b:
        return 1.0
    ta, tb = a.split(), b.split()
    if not ta or not tb:
        return 0.0
    return SequenceMatcher(None, ta, tb, autojunk=False).ratio()


@dataclass
class Candidate:
    group: str
    kind: str  # altered | added | removed
    old: list[Unit] = field(default_factory=list)
    new: list[Unit] = field(default_factory=list)
    similarity: float = 0.0  # between old and new (altered) or with the closest sentence
    closest: Unit | None = None  # for added/removed: closest sentence on the other side

    @property
    def old_text(self) -> str:
        return " ".join(u.text for u in self.old)

    @property
    def new_text(self) -> str:
        return " ".join(u.text for u in self.new)

    @property
    def old_key(self) -> str:
        return " ".join(u.key for u in self.old)

    @property
    def new_key(self) -> str:
        return " ".join(u.key for u in self.new)


@dataclass
class PairResult:
    old: Version
    new: Version
    candidates: list[Candidate]
    stats: Counter

    @property
    def format_conversion(self) -> bool:
        return self.old.fmt != self.new.fmt


def _exact(old: list[Unit], new: list[Unit], o_left: set, n_left: set) -> int:
    by_key: dict[str, list[int]] = defaultdict(list)
    for i in sorted(o_left):
        by_key[old[i].key].append(i)
    n = 0
    for j in sorted(n_left):
        lst = by_key.get(new[j].key)
        if lst:
            i = lst.pop(0)
            o_left.discard(i)
            n_left.discard(j)
            n += 1
    return n


def _runs(units: list[Unit], max_len: int) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for i in range(len(units)):
        key = units[i].key
        for k in range(2, max_len + 1):
            if i + k > len(units):
                break
            key = key + " " + units[i + k - 1].key
            out.setdefault(key, (i, k))
    return out


def _split_merge_exact(old, new, o_left, n_left) -> int:
    """A leftover sentence equal to a run of consecutive sentences on the other side."""
    n = 0
    for a, b, a_left, b_left in ((old, new, o_left, n_left), (new, old, n_left, o_left)):
        if not a_left:
            continue
        runs = _runs(b, MAX_RUN)
        for i in sorted(a_left):
            hit = runs.get(a[i].key)
            if hit and any(j in b_left for j in range(hit[0], hit[0] + hit[1])):
                a_left.discard(i)
                for j in range(hit[0], hit[0] + hit[1]):
                    b_left.discard(j)
                n += 1
    return n


def _leftover_runs(units: list[Unit], left: set) -> list[tuple[int, ...]]:
    idx = sorted(left)
    out = []
    for s in range(len(idx)):
        run = [idx[s]]
        for t in range(s + 1, min(s + 4, len(idx))):
            if idx[t] != run[-1] + 1:
                break
            run.append(idx[t])
            out.append(tuple(run))
    return out


def align_group(group: str, old: list[Unit], new: list[Unit], o_left: set, n_left: set) -> list[Candidate]:
    cands: list[Candidate] = []
    # near-identical split/merge among leftovers
    for a, b, a_left, b_left, a_is_old in ((old, new, o_left, n_left, True), (new, old, n_left, o_left, False)):
        for run in _leftover_runs(b, b_left):
            if not all(j in b_left for j in run):
                continue
            joined = " ".join(b[j].key for j in run)
            best, best_i = 0.0, None
            for i in a_left:
                s = sim(a[i].key, joined)
                if s > best:
                    best, best_i = s, i
            if best_i is not None and best >= SPLIT_SIM:
                a_left.discard(best_i)
                for j in run:
                    b_left.discard(j)
                ou, nu = ([a[best_i]], [b[j] for j in run]) if a_is_old else ([b[j] for j in run], [a[best_i]])
                cands.append(Candidate(group, "altered", ou, nu, best))
    # greedy closest pairs
    pairs = []
    for i in o_left:
        for j in n_left:
            s = sim(old[i].key, new[j].key)
            if s >= PAIR_MIN:
                pairs.append((s, i, j))
    pairs.sort(key=lambda x: (-x[0], x[1], x[2]))
    for s, i, j in pairs:
        if i in o_left and j in n_left:
            o_left.discard(i)
            n_left.discard(j)
            cands.append(Candidate(group, "altered", [old[i]], [new[j]], s))

    def closest(u: Unit, pool: list[Unit]) -> tuple[float, Unit | None]:
        best, bu = 0.0, None
        for v in pool:
            s = sim(u.key, v.key)
            if s > best:
                best, bu = s, v
        return best, bu

    # An added (removed) sentence identical to one still present on the other side is a
    # repeated (de-duplicated) statement, not new content; it is counted, not listed.
    for j in sorted(n_left):
        s, c = closest(new[j], old)
        cands.append(Candidate(group, "repeat" if s == 1.0 else "added", [], [new[j]], s, c))
    for i in sorted(o_left):
        s, c = closest(old[i], new)
        cands.append(Candidate(group, "repeat" if s == 1.0 else "removed", [old[i]], [], s, c))
    return cands


def align_versions(a: Version, b: Version) -> PairResult:
    stats: Counter = Counter()
    ga, gb = a.by_group(), b.by_group()
    left = {g: (set(range(len(ga[g]))), set(range(len(gb[g])))) for g in GROUPS}
    for g in GROUPS:
        stats["old_sentences"] += len(ga[g])
        stats["new_sentences"] += len(gb[g])
        stats["same_text"] += _exact(ga[g], gb[g], *left[g])
    # moves between groups
    for g in GROUPS:
        for h in GROUPS:
            if g != h:
                stats["moved"] += _exact(ga[g], gb[h], left[g][0], left[h][1])
    for g in GROUPS:
        stats["split_merge"] += _split_merge_exact(ga[g], gb[g], *left[g])
    cands: list[Candidate] = []
    for g in GROUPS:
        cands += align_group(g, ga[g], gb[g], *left[g])
    cands, n_sys = drop_systematic(cands)
    stats["systematic"] += n_sys
    stats["repeat"] += sum(1 for c in cands if c.kind == "repeat")
    cands = collapse_blocks([c for c in cands if c.kind != "repeat"], a, b)
    for c in cands:
        stats[c.kind] += 1
    return PairResult(a, b, cands, stats)


# Words whose insertion, deletion or replacement can change meaning. An edit touching one of
# them, or a number, is never treated as a systematic (label-wide) edit.
MEANING_WORDS = set("""
not no never nor none without avoid do dont don t cannot cant must should may can could might will
would only all any always every each some most more less fewer higher lower increase increased
increases increasing decrease decreased decreases decreasing reduce reduced reduces before after
stop stopping discontinue discontinued contraindicated recommended required unless except until
within lt gt le ge pm pct risk death fatal serious severe
""".split())
SYSTEMATIC_MIN = 3


def _edits(c: Candidate) -> list[tuple]:
    ta, tb = c.old_key.split(), c.new_key.split()
    out = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, ta, tb, autojunk=False).get_opcodes():
        if tag != "equal":
            out.append((tuple(ta[i1:i2]), tuple(tb[j1:j2])))
    return out


def _benign(edit: tuple) -> bool:
    toks = edit[0] + edit[1]
    return all(not t[0].isdigit() and t not in MEANING_WORDS for t in toks)


def drop_systematic(cands: list[Candidate]) -> tuple[list[Candidate], int]:
    """Drop altered pairs whose every edit is a label-wide substitution: the same benign edit
    (for example "tramadol hydrochloride" -> "tramadol hydrochloride tablets") made in at least
    SYSTEMATIC_MIN sentences of this version pair."""
    edits = {id(c): _edits(c) for c in cands if c.kind == "altered"}
    counts = Counter(e for es in edits.values() for e in set(es))
    keep, dropped = [], 0
    for c in cands:
        es = edits.get(id(c))
        if es and all(_benign(e) and counts[e] >= SYSTEMATIC_MIN for e in es):
            dropped += 1
            continue
        keep.append(c)
    return keep, dropped


def collapse_blocks(cands: list[Candidate], a: Version, b: Version) -> list[Candidate]:
    out = [c for c in cands if c.kind not in ("added", "removed")]
    for kind, ver, event in (("added", b, "section_added"), ("removed", a, "section_removed")):
        size = Counter((u.group, u.section) for u in ver.units)
        blocks: dict[tuple, list[Candidate]] = defaultdict(list)
        for c in cands:
            if c.kind == kind:
                u = (c.new or c.old)[0]
                blocks[(u.group, u.section)].append(c)
        for key, cs in blocks.items():
            if len(cs) >= BLOCK_MIN and len(cs) >= BLOCK_SHARE * size[key]:
                units = [c.new[0] if kind == "added" else c.old[0] for c in cs]
                if kind == "added":
                    out.append(Candidate(key[0], event, [], units))
                else:
                    out.append(Candidate(key[0], event, units, []))
            else:
                out += cs
    return out
