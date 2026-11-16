"""Hybrid retrieval over one drug label: BM25 keyword search plus embedding similarity.

Pure logic with a JS twin (core/retrieval.js, golden test core/fixtures/retrieval_cases.json).
Embeddings are computed elsewhere (label sentences offline, the question at run time) and
passed in as one cosine similarity per sentence, so both languages score identically.

Units are sentences from split_passage (the same numbering the model was trained on). A
sentence's score mixes, after min-max scaling over the label:
  * BM25 of its words plus its section heading's words (sentence index),
  * BM25 of its whole passage (passage index, as in fdarx/build.py),
  * cosine similarity of its embedding to the question's.
Sentences are taken best-first as seeds; each brings `context` neighbours on each side
from its own passage. Selection stops when the next seed doesn't fit `budget` characters
of rendered label text (see select(); docs/gate2.md has the token calibration). Blocks are rendered in
order of their best seed, sentences in label order, exactly like fdarx/build.render.
"""

import math
from collections import Counter

from .text import content_tokens

DEFAULTS = {"w_sent": 0.3, "w_pass": 0.3, "w_emb": 0.4, "context": 1, "budget": 1500, "max_seeds": 12}
PHONE = {**DEFAULTS, "budget": 1600, "max_seeds": 12}  # ~520 prompt tokens p50, <=600 p90 (0.8B, ctx 2048)
DESKTOP = {**DEFAULTS, "budget": 3500, "max_seeds": 30}  # ~970 prompt tokens p50 (2B)
SENT_COST = 6
HEAD_COST = 12


class BM25:
    """Okapi BM25. Query terms are summed in sorted order so JS and Python agree bit-for-bit."""

    def __init__(self, docs: list[list[str]], k1: float = 1.2, b: float = 0.75):
        self.docs = [Counter(d) for d in docs]
        self.len = [len(d) for d in docs]
        self.avg = (sum(self.len) / len(docs)) if docs and sum(self.len) else 1.0
        df = Counter(t for d in self.docs for t in d)
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.k1, self.b = k1, b

    def scores(self, query: list[str]) -> list[float]:
        terms = sorted(set(query))
        out = []
        for d, ln in zip(self.docs, self.len):
            s = 0.0
            for t in terms:
                f = d.get(t)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * ln / self.avg))
            out.append(s)
        return out


def _scale(xs: list[float]) -> list[float]:
    if not xs:
        return []
    lo, hi = min(xs), max(xs)
    return [(x - lo) / (hi - lo) if hi > lo else 0.0 for x in xs]


class LabelIndex:
    """Sentence and passage BM25 for one label. `passages` is [(heading, [sentences])]."""

    def __init__(self, passages: list[tuple[str, list[str]]]):
        self.passages = passages
        self.units = [(c, s) for c, (_, sents) in enumerate(passages) for s in range(len(sents))]
        self.sent_bm25 = BM25([content_tokens(passages[c][0] + "\n" + passages[c][1][s]) for c, s in self.units])
        self.pass_bm25 = BM25([content_tokens(h + "\n" + "\n".join(ss)) for h, ss in passages])


def scores(index: LabelIndex, question: str, sims: list[float] | None, params: dict,
           exclude: set[int] = frozenset()) -> list[float]:
    """Combined score per unit (aligned with index.units); excluded passages get -1."""
    q = content_tokens(question)
    keep = [i for i, (c, _) in enumerate(index.units) if c not in exclude]
    sb = index.sent_bm25.scores(q)
    pb = index.pass_bm25.scores(q)
    sb_k = _scale([sb[i] for i in keep])
    pb_k = _scale([pb[index.units[i][0]] for i in keep])
    em_k = _scale([sims[i] for i in keep]) if sims is not None else [0.0] * len(keep)
    w_s, w_p, w_e = params["w_sent"], params["w_pass"], params["w_emb"] if sims is not None else 0.0
    out = [-1.0] * len(index.units)
    for j, i in enumerate(keep):
        out[i] = w_s * sb_k[j] + w_p * pb_k[j] + w_e * em_k[j]
    return out


def select(index: LabelIndex, unit_scores: list[float], params: dict) -> list[tuple[int, list[int]]]:
    """Blocks [(passage, [sentence ids])] chosen best-first under the character budget.

    Cost is the rendered size: each sentence costs len + SENT_COST ("[n] " and newline), each
    new passage len(heading) + HEAD_COST ("[Section: ...]" line and blank line).
    """
    order = sorted((i for i, x in enumerate(unit_scores) if x >= 0), key=lambda i: (-unit_scores[i], i))
    chosen: dict[int, set[int]] = {}
    first: dict[int, int] = {}
    used, seeds = 0, 0
    for i in order:
        if seeds >= params["max_seeds"]:
            break
        c, s = index.units[i]
        have = chosen.get(c, set())
        if s in have:  # already shown as context
            continue
        sents = index.passages[c][1]
        k = params["context"]
        head = 0 if c in chosen else len(index.passages[c][0]) + HEAD_COST
        add = [j for j in range(max(0, s - k), min(len(sents), s + k + 1)) if j not in have]
        cost = head + sum(len(sents[j]) + SENT_COST for j in add)
        if used + cost > params["budget"]:
            add, cost = [s], head + len(sents[s]) + SENT_COST  # fall back to the seed alone
            if used + cost > params["budget"]:
                break
        chosen.setdefault(c, set()).update(add)
        first.setdefault(c, seeds)
        used += cost
        seeds += 1
    return [(c, sorted(chosen[c])) for c in sorted(chosen, key=lambda c: first[c])]


def render(passages: list[tuple[str, list[str]]], blocks: list[tuple[int, list[int]]], drug: str,
           question: str) -> tuple[str, dict[tuple[int, int], int]]:
    """Same text as fdarx/build.render. Returns (user_text, {(passage, sentence): number})."""
    n, lines, numbering = 1, [], {}
    for chunk, sent_ids in blocks:
        head = passages[chunk][0]
        lines.append(f"[Section: {head}]" if head else "[Section]")
        for s in sent_ids:
            lines.append(f"[{n}] {passages[chunk][1][s]}")
            numbering[(chunk, s)] = n
            n += 1
        lines.append("")
    user = f"Drug: {drug}\n\nLabel sentences:\n" + "\n".join(lines) + f"\nQuestion: {question}"
    return user, numbering


def retrieve(index: LabelIndex, drug: str, question: str, sims: list[float] | None = None,
             params: dict | None = None, exclude: set[int] = frozenset()):
    """Returns (user_text, numbering, blocks)."""
    p = {**DEFAULTS, **(params or {})}
    blocks = select(index, scores(index, question, sims, p, exclude), p)
    user, numbering = render(index.passages, blocks, drug, question)
    return user, numbering, blocks
