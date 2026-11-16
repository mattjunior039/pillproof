"""Build MLX-LM chat-format training/eval files from aligned FDARxBench items.

See docs/output-format.md for the prompt and target format. Summary:

* Each example shows the drug name, a few label passages with globally numbered
  sentences, and the question. The assistant replies either
      SENTENCES: 3, 5
      ANSWER: <restatement>
  or exactly
      NOT IN LABEL
* Answerable examples: the passages holding the aligned sentences ("gold") plus
  hard-negative distractor passages from the same label (BM25 on the question).
  Long passages are windowed around the relevant sentences. Order is shuffled.
* Decline examples (built by code, plan section 6): take an answerable item, remove
  every passage of the label that covers the answer (any passage that contains a
  selected sentence, shares the gold section heading, or whose words cover >= 40% of
  the answer), and show the top BM25 passages that remain. Dropped if the answer is
  still supported anywhere in the rest of the label (support.py: loose synonym-aware
  alignment plus a numbers/units/drug-names check); otherwise kept only if a greedy
  alignment over the shown passages covers < 50% of the answer. Dropped items are
  replaced from the remaining answerable items of the same split.
* FDARxBench's templated "refusal" items are not used for training (they follow an
  artificial template); they are kept in the T1 test file as a separate category.
* Section weighting: items whose gold passages are all from patient-relevant sections
  ("core") are always kept; items with mixed sections are kept with p=0.7 and technical
  items (clinical pharmacology, clinical studies, ...) with p=0.4 in train.

Outputs (BUILD/fdarx/mlx/):
  train.jsonl, valid.jsonl, test.jsonl     {"messages": [system, user, assistant]}
  train_meta.jsonl, valid_meta.jsonl, test_meta.jsonl   same + metadata (one line each)
  build_report.json
"""

import json
import math
import random
import re
from collections import Counter

from .. import paths, sections
from ..text import content_tokens, norm_ws
from . import support
from .align import OUT as ALIGNED, Label, _labels, align_answer, answer_tokens, kept

OUT_DIR = paths.BUILD / "fdarx" / "mlx"
SEED = 7

SYSTEM = (
    "You answer questions about a medicine using only the numbered sentences from its FDA label. "
    "If the sentences answer the question, reply in two lines:\n"
    "SENTENCES: <numbers of the sentences that answer it, separated by commas>\n"
    "ANSWER: <a short, plain restatement that uses only facts from those sentences>\n"
    "If the sentences do not answer the question, reply with exactly:\n"
    "NOT IN LABEL"
)
DECLINE = "NOT IN LABEL"

MAX_PASSAGES = 5
MAX_PROMPT_CHARS = 5000  # passages only; ~1,300-1,500 tokens
MAX_PASSAGE_CHARS = 1600
DISTRACTOR_CHARS = 900
WINDOW = 2  # sentences of context kept on each side of the answer sentences
DECLINE_SHARE = 0.30  # share of decline examples in train/valid
COVER_REMOVE = 0.4
DECLINE_MAX_COVER = 0.5
TIER_KEEP = {"core": 1.0, "mixed": 0.7, "technical": 0.4}


# ---------- retrieval (BM25 over the passages of one label) ----------

class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.2, b: float = 0.75):
        self.docs = [Counter(d) for d in docs]
        self.len = [len(d) for d in docs]
        self.avg = (sum(self.len) / len(docs)) if docs else 1.0
        df = Counter(t for d in self.docs for t in d)
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.k1, self.b = k1, b

    def scores(self, query: list[str]) -> list[float]:
        out = []
        for d, ln in zip(self.docs, self.len):
            s = 0.0
            for t in set(query):
                f = d.get(t)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * ln / self.avg))
            out.append(s)
        return out


_bm25_cache: dict[str, BM25] = {}


def bm25_for(lab: Label) -> BM25:
    if lab.set_id not in _bm25_cache:
        _bm25_cache[lab.set_id] = BM25([content_tokens(c) for c in lab.chunks])
    return _bm25_cache[lab.set_id]


def ranked(lab: Label, question: str) -> list[int]:
    sc = bm25_for(lab).scores(content_tokens(question))
    return sorted(range(len(sc)), key=lambda i: (-sc[i], i))


# ---------- passage selection ----------

def window(lab: Label, chunk: int, focus: list[int], max_chars: int) -> list[int]:
    """Sentence indices of `chunk` to show: all if short, else a window around `focus`."""
    sents = lab.passages[chunk][1]
    idx = list(range(len(sents)))
    if sum(len(s) + 1 for s in sents) <= max_chars:
        return idx
    lo, hi = max(0, min(focus) - WINDOW), min(len(sents) - 1, max(focus) + WINDOW)
    keep = [i for i in idx if lo <= i <= hi]
    # Trim context (never the focus sentences) until it fits.
    while sum(len(sents[i]) + 1 for i in keep) > max_chars and len(keep) > len(focus):
        ends = [i for i in (keep[0], keep[-1]) if i not in focus]
        if not ends:
            break
        keep.remove(max(ends, key=lambda i: len(sents[i])))
    return keep


def best_sentence(lab: Label, chunk: int, question: str) -> int:
    q = set(content_tokens(question))
    toks = lab.sent_tokens[chunk]
    return max(range(len(toks)), key=lambda i: (len(toks[i] & q), -i)) if toks else 0


def covering_chunks(lab: Label, rec: dict, ans: set[str]) -> set[int]:
    """Passages that (may) hold the answer; removed for declines and never used as distractors."""
    out = set(rec["gold_chunks"])
    gold_text = {norm_ws(lab.passages[c][1][s]) for c, s in rec["sentences"]}
    gold_heads = {lab.passages[c][0] for c in rec["gold_chunks"] if lab.passages[c][0]}
    for i, (head, sents) in enumerate(lab.passages):
        if head and head in gold_heads:
            out.add(i)
            continue
        if any(norm_ws(s) in gold_text for s in sents):
            out.add(i)
            continue
        toks = set().union(*lab.sent_tokens[i]) if lab.sent_tokens[i] else set()
        if ans and len(toks & ans) / len(ans) >= COVER_REMOVE:
            out.add(i)
    return out


def render(lab: Label, blocks: list[tuple[int, list[int]]], drug: str, question: str):
    """Number sentences globally. Returns (user_text, {(chunk, sent): number}, chars)."""
    n, lines, numbering, chars = 1, [], {}, 0
    for chunk, sent_ids in blocks:
        head = lab.passages[chunk][0]
        lines.append(f"[Section: {head}]" if head else "[Section]")
        for s in sent_ids:
            text = lab.passages[chunk][1][s]
            lines.append(f"[{n}] {text}")
            numbering[(chunk, s)] = n
            chars += len(text)
            n += 1
        lines.append("")
    user = f"Drug: {drug}\n\nLabel sentences:\n" + "\n".join(lines) + f"\nQuestion: {question}"
    return user, numbering, chars


def add_distractors(lab: Label, question: str, exclude: set[int], blocks: list, budget: int,
                    rng: random.Random, n_max: int) -> None:
    used = sum(len(lab.passages[c][1][s]) for c, ids in blocks for s in ids)
    for c in ranked(lab, question):
        if len(blocks) >= n_max:
            break
        if c in exclude or not lab.passages[c][1] or any(c == b[0] for b in blocks):
            continue
        ids = window(lab, c, [best_sentence(lab, c, question)], DISTRACTOR_CHARS)
        size = sum(len(lab.passages[c][1][s]) for s in ids)
        if used + size > budget:
            continue
        blocks.append((c, ids))
        used += size


def clean_target(text: str) -> str:
    """One-line restatement: bullet lists become '; '-joined items."""
    lines = [re.sub(r"^[-•●*]\s*", "", l).strip() for l in text.split("\n")]
    lines = [l for l in lines if l]
    if len(lines) > 1:
        lines = [l.rstrip(";. ") for l in lines[:-1]] + [lines[-1].rstrip("; ")]
    out = re.sub(r"\s+", " ", "; ".join(lines)).strip()
    return re.sub(r"\s+([.;,])", r"\1", out)


def answerable_example(rec: dict, lab: Label, rng: random.Random):
    gold = sorted({c for c, _ in rec["sentences"]})
    blocks = []
    budget_each = max(600, min(MAX_PASSAGE_CHARS, MAX_PROMPT_CHARS // max(1, len(gold))))
    for c in gold:
        focus = [s for cc, s in rec["sentences"] if cc == c]
        blocks.append((c, window(lab, c, focus, budget_each)))
    ans = answer_tokens(rec["target"], rec["question"], set(content_tokens(rec["drug_name"])))
    exclude = covering_chunks(lab, rec, ans)
    n_dist = rng.choice([1, 2, 3, 3])
    add_distractors(lab, rec["question"], exclude, blocks, MAX_PROMPT_CHARS, rng, len(blocks) + n_dist)
    rng.shuffle(blocks)
    user, numbering, chars = render(lab, blocks, rec["drug_name"], rec["question"])
    nums = sorted(numbering[(c, s)] for c, s in map(tuple, rec["sentences"]))
    target = f"SENTENCES: {', '.join(map(str, nums))}\nANSWER: {clean_target(rec['target'])}"
    return user, target, {"passages": [b[0] for b in blocks], "answer_sentences": nums, "prompt_chars": chars}


def decline_removed(rec: dict, lab: Label) -> set[int]:
    ans = answer_tokens(rec["target"], rec["question"], set(content_tokens(rec["drug_name"])))
    return covering_chunks(lab, rec, ans)


def decline_example(rec: dict, lab: Label, rng: random.Random):
    ans = answer_tokens(rec["target"], rec["question"], set(content_tokens(rec["drug_name"])))
    exclude = covering_chunks(lab, rec, ans)
    blocks: list = []
    add_distractors(lab, rec["question"], exclude, blocks, MAX_PROMPT_CHARS, rng, rng.choice([2, 3, 4]))
    if not blocks:
        return None
    cands = [(c, s) for c, ids in blocks for s in ids]
    _, cov, _, _ = align_answer(rec["target"], cands, lab, ans)
    if cov >= DECLINE_MAX_COVER:
        return None
    rng.shuffle(blocks)
    user, _, chars = render(lab, blocks, rec["drug_name"], rec["question"])
    return user, DECLINE, {"passages": [b[0] for b in blocks], "removed": sorted(exclude),
                           "residual_coverage": round(cov, 3), "prompt_chars": chars}


def refusal_example(item: dict, lab: Label, rng: random.Random):
    blocks: list = []
    add_distractors(lab, item["question"], set(), blocks, MAX_PROMPT_CHARS, rng, 3)
    rng.shuffle(blocks)
    user, _, chars = render(lab, blocks, item.get("drug_name") or lab.drug_name, item["question"])
    return user, DECLINE, {"passages": [b[0] for b in blocks], "prompt_chars": chars}


def tier(rec: dict) -> str:
    cats = rec["categories"] or ["other"]
    pr = [sections.is_patient_relevant(c) for c in cats]
    return "core" if all(pr) else ("mixed" if any(pr) else "technical")


def main() -> None:
    rng = random.Random(SEED)
    labs = _labels()
    recs = [json.loads(l) for l in open(ALIGNED)]
    good = [r for r in recs if kept(r)]
    split_of = json.loads((paths.BUILD / "fdarx" / "split.json").read_text())["labels"]
    report: dict = {"aligned_kept": len(good), "settings": {
        "max_passages": MAX_PASSAGES, "max_prompt_chars": MAX_PROMPT_CHARS, "decline_share": DECLINE_SHARE,
        "cover_remove": COVER_REMOVE, "decline_max_cover": DECLINE_MAX_COVER, "tier_keep": TIER_KEEP,
        "seed": SEED, "support_check": {"threshold": support.THRESHOLD, "max_sentences": support.MAX_SENTENCES,
                                        "min_gain": support.MIN_GAIN, "synonym_groups": len(support._SYN_GROUPS)}}}
    out: dict[str, list] = {"train": [], "dev": [], "test": []}
    skipped = Counter()

    for r in good:
        sp, t = r["split"], tier(r)
        if sp == "train" and rng.random() > TIER_KEEP[t]:
            skipped[f"tier_{t}"] += 1
            continue
        lab = labs[r["set_id"]]
        user, target, meta = answerable_example(r, lab, rng)
        out[sp].append({"kind": "answerable", "tier": t, "rec": r, "user": user, "target": target, "meta": meta})

    from .rewrite import lexicon  # rewrite imports this module
    lex = lexicon()
    for sp in out:
        pos = [e for e in out[sp] if e["kind"] == "answerable"]
        n_dec = round(len(pos) * DECLINE_SHARE / (1 - DECLINE_SHARE)) if sp != "test" else len(pos) // 2
        report.setdefault("decline_target", {})[sp] = n_dec
        first = rng.sample(pos, min(n_dec * 2, len(pos)))
        seen = {id(e) for e in first}
        rest = [e for e in pos if id(e) not in seen]
        random.Random(f"{SEED}-{sp}-refill").shuffle(rest)  # own RNG: refills don't shift the main stream
        for e in first + rest:
            if sum(x["kind"] == "decline" for x in out[sp]) >= n_dec:
                break
            lab = labs[e["rec"]["set_id"]]
            if support.supported_elsewhere(e["rec"], lab, decline_removed(e["rec"], lab), lex)["supported"]:
                skipped[f"decline_{sp}_supported_elsewhere"] += 1
                continue
            ex = decline_example(e["rec"], lab, rng)
            if ex is None:
                skipped[f"decline_{sp}_rejected"] += 1
                continue
            user, target, meta = ex
            out[sp].append({"kind": "decline", "tier": e["tier"], "rec": e["rec"], "user": user,
                            "target": target, "meta": meta})

    # Original templated refusals: test only (T1 reporting category).
    for line in open(paths.FDARX_QA):
        item = json.loads(line)
        if item["task"] != "refusal" or split_of.get(item["set_id"]) != "test":
            continue
        user, target, meta = refusal_example(item, labs[item["set_id"]], rng)
        rec = {"qid": item["qid"], "task": "refusal", "source": item["source"], "set_id": item["set_id"],
               "drug_name": item.get("drug_name"), "question": item["question"], "answer": item["answer"],
               "split": "test", "categories": []}
        out["test"].append({"kind": "fdarx_refusal", "tier": "n/a", "rec": rec, "user": user,
                            "target": target, "meta": meta})

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    names = {"train": "train", "dev": "valid", "test": "test"}
    for sp, exs in out.items():
        rng.shuffle(exs)
        with open(OUT_DIR / f"{names[sp]}.jsonl", "w") as f, open(OUT_DIR / f"{names[sp]}_meta.jsonl", "w") as g:
            for e in exs:
                msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": e["user"]},
                        {"role": "assistant", "content": e["target"]}]
                f.write(json.dumps({"messages": msgs}, ensure_ascii=False) + "\n")
                r = e["rec"]
                g.write(json.dumps({
                    "messages": msgs, "kind": e["kind"], "tier": e["tier"], "qid": r["qid"], "task": r["task"],
                    "source": r["source"], "set_id": r["set_id"], "drug_name": r["drug_name"],
                    "question": r["question"], "reference_answer": r["answer"],
                    "categories": r.get("categories"), "coverage": r.get("coverage"), **e["meta"],
                }, ensure_ascii=False) + "\n")
        chars = sorted(len(e["user"]) for e in exs)
        report[sp] = {
            "examples": len(exs),
            "by_kind": Counter(e["kind"] for e in exs),
            "by_tier_answerable": Counter(e["tier"] for e in exs if e["kind"] == "answerable"),
            "by_task_answerable": Counter(e["rec"]["task"] for e in exs if e["kind"] == "answerable"),
            "user_chars_p50_p95_max": [chars[len(chars) // 2], chars[int(len(chars) * 0.95)], chars[-1]] if chars else None,
        }
    report["skipped"] = skipped
    (OUT_DIR / "build_report.json").write_text(json.dumps(report, indent=1, default=dict))
    print(json.dumps(report, indent=1, default=dict))


if __name__ == "__main__":
    main()
