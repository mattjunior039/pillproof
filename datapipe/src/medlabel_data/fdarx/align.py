"""Align each FDARxBench reference answer to numbered label sentences.

For every factual and multihop item:
1. Map its gold context(s) to label chunks (passages). Highlights items mark the gold
   context with has_answer; self-instruct items use all their contexts. If a highlights
   item has no marked context, all chunks of the label are candidates.
2. Split candidate passages into sentences (the first line of a chunk is a section heading
   when it looks like one; headings are not numbered).
3. Greedy cover: content tokens of the answer (stemmed, stopwords removed, drug-name
   tokens excused when the label sentences never contain them) are covered by picking the
   sentence that adds the most uncovered tokens, while it adds at least MIN_GAIN tokens.
   Afterwards, any answer number still missing is looked up in the remaining candidate
   sentences and that sentence is added.
4. Quality: coverage = covered / answer tokens, where answer tokens exclude question words,
   filler words and the drug name. The item is kept when coverage >= the task threshold
   (factual 0.8, multihop 0.9), no number in the answer is missing from the selected sentences (the same
   rule the app uses to block a restatement), and at most MAX_SENTENCES are selected.

Output: BUILD/fdarx/aligned.jsonl (one record per item, kept or not, with reasons) and
BUILD/fdarx/align_report.json (coverage distribution and counts at several thresholds).
"""

import json
import re
from collections import Counter
from functools import lru_cache

from .. import paths, sections
from ..sentences import split_sentences
from ..text import content_tokens, norm_ws, numbers, strip_xrefs
from .split import OUT as SPLIT

OUT = paths.BUILD / "fdarx" / "aligned.jsonl"
REPORT = paths.BUILD / "fdarx" / "align_report.json"
# Default keep thresholds. Multihop answers add more connective reasoning that the label
# does not state, so they need higher coverage.
THRESHOLD = 0.8
THRESHOLD_BY_TASK = {"factual": 0.8, "multihop": 0.9}
THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
MIN_GAIN = 2
MAX_SENTENCES = 12

# Answer-style connective words that carry no label content.
FILLER = set(content_tokens(
    "include includes including included like such well due potential potentially associated "
    "important importantly crucial essential ensure ensures lead leads occur occurs result results "
    "specifically particularly additionally also therefore however indicate indicates indicated "
    "related regarding noted note known considered consider overall significant significantly "
    "available"
))

_HEADING = re.compile(r"^(\d+(\.\d+)*\.?\s+)?[A-Za-z][^.:;]{0,100}$")


def split_passage(chunk: str) -> tuple[str, list[str]]:
    """Return (heading, sentences). Heading is '' when the first line is ordinary text."""
    lines = chunk.strip().split("\n")
    head = norm_ws(lines[0])
    if len(lines) > 1 and _HEADING.match(head) and len(head.split()) <= 12:
        return head, split_sentences("\n".join(lines[1:]))
    return "", split_sentences(chunk)


class Label:
    def __init__(self, rec: dict):
        self.set_id = rec["set_id"]
        self.drug_name = rec["drug_name"]
        self.chunks = rec["chunks"]
        self._norm = [norm_ws(c) for c in self.chunks]
        self.passages = [split_passage(c) for c in self.chunks]
        self.sent_tokens = [[set(content_tokens(s)) for s in sents] for _, sents in self.passages]
        self.head_tokens = [set(content_tokens(h)) for h, _ in self.passages]
        self.head_number = [m.group(0) if (m := re.match(r"\d+(\.\d+)*", h)) else "" for h, _ in self.passages]
        self.sent_numbers = [[numbers(s) for s in sents] for _, sents in self.passages]

    def find_chunks(self, text: str, hint: int | None) -> list[int]:
        t = norm_ws(text)
        if not t:
            return []
        if hint is not None and 0 <= hint < len(self._norm) and t in self._norm[hint]:
            return [hint]
        hits = [i for i, c in enumerate(self._norm) if t in c]
        if hits:
            return hits[:1]
        head = t[:120]
        hits = [i for i, c in enumerate(self._norm) if head in c]
        if hits:
            return hits[:1]
        return [i for i, c in enumerate(self._norm) if len(c) > 40 and c in t]

    def category(self, idx: int, title: str | None = None, code: str | None = None) -> str:
        return sections.classify_section(title or self.passages[idx][0], code)


@lru_cache(maxsize=None)
def _labels() -> dict[str, Label]:
    return {r["set_id"]: Label(r) for r in map(json.loads, open(paths.FDARX_LABELS))}


def gold_contexts(item: dict) -> list[dict]:
    ctx = item["context"]
    if item["source"] == "highlights":
        return [c for c in ctx if c.get("has_answer")]
    return ctx


def answer_tokens(answer: str, question: str, excuse: set[str]) -> set[str]:
    """Answer content tokens that the label must support.

    Question words, filler words and the drug's name are not counted: restating the question
    is not new content. If that leaves nothing, all answer tokens are used.
    """
    full = set(content_tokens(answer))
    ans = full - set(content_tokens(question)) - FILLER - excuse
    return ans or (full - FILLER) or full


def align_answer(answer: str, cands: list[tuple[int, int]], lab: Label, ans: set[str]):
    """Greedy cover of answer tokens by candidate sentences (chunk, sent).

    A chosen sentence also covers words of its passage heading (e.g. "Lactation:").
    """
    covered: set[str] = set()
    chosen: list[tuple[int, int]] = []
    while len(chosen) < MAX_SENTENCES + 1:
        best, gain = None, 0
        for cs in cands:
            if cs in chosen:
                continue
            g = len((lab.sent_tokens[cs[0]][cs[1]] & ans) - covered)
            if g > gain:
                best, gain = cs, g
        if best is None or gain < min(MIN_GAIN, len(ans - covered)):
            break
        chosen.append(best)
        covered |= lab.sent_tokens[best[0]][best[1]] & ans
    for c, _ in chosen:
        covered |= lab.head_tokens[c] & ans
    ans_nums = numbers(answer)
    have = set().union(*(lab.sent_numbers[c][s] for c, s in chosen)) if chosen else set()
    for n in sorted(ans_nums - have):
        for cs in cands:
            if cs not in chosen and n in lab.sent_numbers[cs[0]][cs[1]]:
                chosen.append(cs)
                covered |= lab.sent_tokens[cs[0]][cs[1]] & ans
                have |= lab.sent_numbers[cs[0]][cs[1]]
                break
    coverage = len(covered) / len(ans) if ans else 0.0
    return sorted(chosen), coverage, sorted(ans_nums - have), len(ans)


def align_item(item: dict, lab: Label) -> dict:
    gold = gold_contexts(item)
    chunk_ids: list[int] = []
    unmapped = 0
    for c in gold:
        hits = lab.find_chunks(c["text"], c.get("doc_chunk_index"))
        unmapped += not hits
        chunk_ids += [h for h in hits if h not in chunk_ids]
    target = strip_xrefs(item["answer"])
    excuse = set(content_tokens(item.get("drug_name") or "")) | set(content_tokens(lab.drug_name))
    ans = answer_tokens(target, item["question"], excuse)

    def run(pool: list[int]):
        cands = [(c, s) for c in pool for s in range(len(lab.passages[c][1]))]
        return align_answer(target, cands, lab, ans)

    scope = "gold" if chunk_ids else "label"
    result = run(chunk_ids or list(range(len(lab.chunks))))
    # Highlights summarise whole sections; widen to every chunk of the cited sections.
    if item["source"] == "highlights" and (result[1] < THRESHOLD or result[2]):
        cited = [c for c in (item.get("citations") or []) if c]
        wide = sorted(set(chunk_ids) | {
            i for i, n in enumerate(lab.head_number)
            if n and any(n == c or n.startswith(c + ".") for c in cited)
        })
        if wide and wide != chunk_ids:
            alt = run(wide)
            if (not alt[2], alt[1]) > (not result[2], result[1]):
                result, chunk_ids, scope = alt, wide, "cited_sections"
    chosen, cov, missing_nums, n_tok = result

    cats = [sections.classify_section(c.get("section_title"), c.get("section_code")) for c in gold]
    if not gold:
        cats = [lab.category(c) for c, _ in chosen]
    reasons = []
    if not chosen:
        reasons.append("no_sentences")
    if n_tok == 0:
        reasons.append("empty_answer")
    if missing_nums:
        reasons.append("number_missing")
    if len(chosen) > MAX_SENTENCES:
        reasons.append("too_many_sentences")
    if scope == "label":
        reasons.append("no_gold_passage")
    return {
        "qid": item["qid"], "task": item["task"], "source": item["source"],
        "set_id": item["set_id"], "drug_name": item.get("drug_name") or lab.drug_name,
        "question": item["question"], "answer": item["answer"], "target": target,
        "question_type": item.get("question_type"),
        "gold_chunks": chunk_ids, "unmapped_contexts": unmapped, "scope": scope,
        "categories": cats, "patient_relevant": bool(cats) and all(sections.is_patient_relevant(c) for c in cats),
        "sentences": [list(cs) for cs in chosen],
        "coverage": round(cov, 4), "answer_tokens": n_tok, "missing_numbers": missing_nums,
        "hard_fail": reasons,
    }


def kept(rec: dict, threshold: float | None = None) -> bool:
    t = THRESHOLD_BY_TASK.get(rec["task"], THRESHOLD) if threshold is None else threshold
    return not rec["hard_fail"] and rec["coverage"] >= t


def main() -> None:
    labs = _labels()
    split = json.loads(SPLIT.read_text())["labels"]
    recs = []
    for line in open(paths.FDARX_QA):
        item = json.loads(line)
        if item["task"] == "refusal" or item["set_id"] not in split:
            continue
        rec = align_item(item, labs[item["set_id"]])
        rec["split"] = split[item["set_id"]]
        recs.append(rec)
    with open(OUT, "w") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    report: dict = {"items": len(recs), "threshold_by_task": THRESHOLD_BY_TASK, "min_gain": MIN_GAIN,
                    "max_sentences": MAX_SENTENCES}
    report["hard_fail"] = Counter(x for r in recs for x in r["hard_fail"])
    report["hard_fail_any"] = sum(1 for r in recs if r["hard_fail"])
    bins = Counter(min(int(r["coverage"] * 10), 10) / 10 for r in recs if not r["hard_fail"])
    report["coverage_hist_no_hard_fail"] = {f"{k:.1f}": bins[k] for k in sorted(bins)}
    report["kept_at_threshold"] = {
        str(t): {
            "all": sum(kept(r, t) for r in recs),
            **{f"{task}/{sp}": sum(kept(r, t) for r in recs if r["task"] == task and r["split"] == sp)
               for task in ("factual", "multihop") for sp in ("train", "dev", "test")},
        }
        for t in THRESHOLDS
    }
    k = [r for r in recs if kept(r)]
    report["kept"] = {
        "total": len(k),
        "by_task_source": Counter(f"{r['task']}/{r['source']}" for r in k),
        "by_scope": Counter(r["scope"] for r in k),
        "patient_relevant": sum(r["patient_relevant"] for r in k),
        "sentences_selected": Counter(len(r["sentences"]) for r in k),
    }
    REPORT.write_text(json.dumps(report, indent=1, default=dict))
    print(json.dumps(report, indent=1, default=dict))


if __name__ == "__main__":
    main()
