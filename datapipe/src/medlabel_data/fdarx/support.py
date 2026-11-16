"""Is a decline item's reference answer supported anywhere else in the label?

Decline items are built by removing the passages that cover the answer
(build.covering_chunks). The answer is often repeated elsewhere, most often in
the Medication Guide / patient information (lay wording) or in a second copy of
a section (e.g. "2.6 Renal Impairment" and "8.6 Renal Impairment"). Such items
teach the model to decline answerable questions, so build.py drops them.

The check is deliberately loose (we would rather lose a good decline item than
keep an answerable one):

* candidate sentences: every sentence of the label outside the removed passages;
* words are canonicalised with a small clinical <-> lay synonym map
  ("geriatric"/"older" -> elderly, "renal" -> kidney, ...);
* greedy alignment with gain >= 1 new answer word per sentence, at most
  MAX_SENTENCES sentences; coverage = share of answer words covered
  (headings of the chosen passages count too);
* supported if coverage >= THRESHOLD and every number, unit and drug name of the
  reference answer appears in the chosen sentences or anywhere in the remaining
  label (or in the drug name).

Pure code, no model: it is applied identically to train, dev and test.
"""

from ..text import content_tokens, numbers, restatement_problems, stem, units
from .align import Label, answer_tokens

THRESHOLD = 0.5
MAX_SENTENCES = 4
MIN_GAIN = 1

_SYN_GROUPS = {
    "elderly": "geriatric older elderly",
    "kidney": "renal kidney",
    "liver": "hepatic liver",
    "child": "pediatric children child",
    "ejaculate": "ejaculatory ejaculation ejaculate",
    "pregnancy": "pregnant pregnancy",
    "baby": "fetal fetus unborn",
    "lactation": "breastfeeding breastfed nursing lactation",
    "allergy": "hypersensitivity allergic allergy",
    "stop": "discontinue discontinued stop stopping",
    "take": "administer administered take taken",
    "doctor": "physician doctor provider",
    "dose": "dosage dose doses dosing",
    "side": "adverse",
    "heart": "cardiac heart",
    "stomach": "gastrointestinal stomach",
    "itch": "pruritus itching",
    "sleepy": "somnolence drowsiness",
    "dizzy": "dizziness dizzy",
    "vomit": "vomiting vomit",
    "suicid": "suicidality suicidal suicide",
}
SYN: dict[str, str] = {}
for _canon, _words in _SYN_GROUPS.items():
    for _w in _words.split():
        SYN[stem(_w)] = _canon
        for _t in content_tokens(_w):
            SYN[_t] = _canon


def canon(tokens) -> set[str]:
    return {SYN.get(t, t) for t in tokens}


def remaining(lab: Label, removed: set[int]) -> list[tuple[int, int]]:
    return [(c, s) for c in range(len(lab.passages)) if c not in removed for s in range(len(lab.passages[c][1]))]


def loose_align(ans: set[str], cands: list[tuple[int, int]], lab: Label,
                max_sentences: int = MAX_SENTENCES, min_gain: int = MIN_GAIN):
    """Greedy set cover over canonical tokens. Returns (chosen, coverage)."""
    A = canon(ans)
    if not A:
        return [], 0.0
    toks = {cs: canon(lab.sent_tokens[cs[0]][cs[1]]) & A for cs in cands}
    covered: set[str] = set()
    chosen: list[tuple[int, int]] = []
    while len(chosen) < max_sentences:
        best, gain = None, 0
        for cs in cands:
            if cs in chosen:
                continue
            g = len(toks[cs] - covered)
            if g > gain:
                best, gain = cs, g
        if best is None or gain < min_gain:
            break
        chosen.append(best)
        covered |= toks[best]
    for c, _ in chosen:
        covered |= canon(lab.head_tokens[c]) & A
    return chosen, len(covered) / len(A)


def key_fact_problems(target: str, drug: str, lab: Label, cands: list[tuple[int, int]],
                      chosen: list[tuple[int, int]], lexicon: set[str]) -> list[str]:
    """Numbers/units/drug names of the answer not found in the chosen sentences nor elsewhere in cands."""
    text = lambda cs: lab.passages[cs[0]][1][cs[1]]
    src = "\n".join([drug or "", lab.drug_name or ""] + [text(cs) for cs in chosen])
    probs = restatement_problems(target, src, lexicon)
    if not probs:
        return []
    extra = []
    for p in probs:
        kind, val = p.split(" ", 1)
        for cs in cands:
            t = text(cs)
            if ((kind == "number" and val in numbers(t)) or (kind == "unit" and val in units(t))
                    or (kind == "drug" and val in t.lower())):
                extra.append(text(cs))
                break
    return restatement_problems(target, src + "\n" + "\n".join(extra), lexicon) if extra else probs


def supported_elsewhere(rec: dict, lab: Label, removed: set[int], lexicon: set[str]) -> dict:
    """Check the reference answer against all sentences outside `removed`."""
    drug = rec.get("drug_name") or ""
    excuse = set(content_tokens(drug)) | set(content_tokens(lab.drug_name or ""))
    ans = answer_tokens(rec["target"], rec["question"], excuse)
    cands = remaining(lab, removed)
    chosen, cov = loose_align(ans, cands, lab)
    probs = key_fact_problems(rec["target"], drug, lab, cands, chosen, lexicon)
    return {"supported": bool(chosen) and cov >= THRESHOLD and not probs,
            "coverage": round(cov, 3), "key_fact_problems": probs, "sentences": chosen}
