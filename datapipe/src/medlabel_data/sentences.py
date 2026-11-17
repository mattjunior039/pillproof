"""Rule-based sentence splitter for FDA label text.

Deliberately simple and deterministic so the browser app can port it to
JavaScript and get identical sentence numbers. The rules, in order:

1. Replace non-breaking and other unicode spaces with a plain space.
2. Treat every line break as a hard boundary. Inline bullet characters
   ("•", "●", "▪", "◦") also start a new unit.
3. Inside a unit, collapse runs of whitespace to one space and trim.
4. Split after ".", "!" or "?" (optionally followed by closing quotes,
   parentheses or brackets) when whitespace follows and the next character
   is an uppercase letter, digit, opening quote/paren/bracket, or a bullet
   dash. A space before the period (" .", common in FDARxBench) is allowed.
5. Do not split when the word before the period is a known abbreviation
   (see ABBREVIATIONS), a single letter (initials, "U.S."; but not a unit
   after a degree sign, as in "25°C."), or a bare 1-2
   digit number that opens the unit or follows "(", ":", ";" or "." (list markers
   such as "1.").
6. Drop units that are empty or contain no letter or digit.

OTC mode (``otc=True``) is for openFDA Drug Facts text, where list items and
warning headings arrive run together on one line ("...while using this product
Stomach bleeding warning : This product contains an NSAID..."). It is off by
default, so prescription labels split exactly as before. It adds:

7. Rule 4 also splits when the next character is a lowercase letter
   ("...ask a doctor. children under 12 years...").
8. Before rule 4, a unit is cut in front of a Drug Facts item start when the
   previous character is a letter, digit, ")" or "]" (no punctuation already):
   a capitalized heading of up to five words ending in ":" ("Stomach bleeding
   warning :"), a capitalized starter word (If, When, Do, Ask, Stop, Keep,
   Store, Take, Use, Read, Children, Adults, Other, Each), or a standard
   lowercase item opener (OTC_OPENERS; after ":" only when the sentence so far is
   longer than 6 words, i.e. a lead-in, not "under 12 years: ask"). Lowercase
   openers are not cut after a linking word (NO_CUT_AFTER: "if you have"),
   except a repeated "you" ("applies to you you have asthma").

Golden examples live in tests/fixtures/sentence_cases.json; a JavaScript
port should pass the same cases.
"""

import re

ABBREVIATIONS = {
    "e.g", "i.e", "vs", "approx", "dr", "mr", "mrs", "ms", "no", "nos", "fig", "figs",
    "inc", "ltd", "co", "corp", "st", "jr", "sr", "ca", "cf", "al", "min", "max",
    "hr", "hrs", "resp", "incl", "ref", "refs", "vol", "pp", "sec", "eq", "approx",
    "mfd", "dist", "tab", "tabs", "cap", "caps", "oz", "fl", "wt",
}

_SPACES = re.compile(r"[\u00a0\u2000-\u200b\u202f\u205f\u3000\t\r\f\v]")
_BULLETS = re.compile(r"\s*[•●▪◦]\s*")
_WS = re.compile(r" +")
# Candidate boundary: optional space, terminal punctuation, optional closers, whitespace,
# then a lookahead for a sentence-starting character.
_BOUNDARY = re.compile(r" ?([.!?])([\"'”’)\]]*) +(?=[A-Z0-9\"'“‘(\[\-–])")
_BOUNDARY_OTC = re.compile(r" ?([.!?])([\"'”’)\]]*) +(?=[A-Za-z0-9\"'“‘(\[\-–])")
OTC_OPENERS = (
    r"do not (?:take|exceed|use|give)|children under|adults and children|ask a doctor|stop use"
    r"|if pregnant|keep out of reach|store at|avoid excessive heat|read all"
    r"|each (?:tablet|capsule|caplet|softgel|pack|packet) contains|you (?:have|are taking)"
    r"|have (?:[0-9]|had|bloody|stomach pain)|[0-9]+ or more alcoholic|ringing in the ears|take (?:a blood|other drugs|more or)|are age [0-9]|feel faint"
    r"|vomit blood|pain gets worse|fever gets worse|redness or swelling|any new symptoms"
)
_OTC_ITEM = re.compile(
    r" (?=[A-Z][A-Za-z’'-]*(?: [A-Za-z’'()-]+){0,4} ?:(?= )"
    r"|(?:If|When|Do|Ask|Stop|Keep|Store|Take|Use|Read|Children|Adults|Other|Each)(?![A-Za-z0-9_])"
    r"|(?:" + OTC_OPENERS + r")(?![A-Za-z0-9_]))"
)
NO_CUT_AFTER = {
    "if", "when", "and", "or", "that", "who", "unless", "because", "whether", "while", "you",
    "to", "not", "the", "a", "an", "of", "with", "than", "may", "can", "should", "do", "does",
    "have", "has", "had", "are", "is", "be", "take", "taking",
}
_LAST_WORD = re.compile(r"([A-Za-z]+)$")
_WORD_BEFORE = re.compile(r"([A-Za-z0-9.]+)$")
_HAS_ALNUM = re.compile(r"[A-Za-z0-9]")


def _is_protected(prefix: str, punct: str) -> bool:
    if punct != ".":
        return False
    m = _WORD_BEFORE.search(prefix)
    if not m:
        return False
    word = m.group(1).rstrip(".").lower()
    if word in ABBREVIATIONS:
        return True
    before = prefix[: -len(m.group(1))].rstrip()
    last = word.rsplit(".", 1)[-1]
    if len(last) == 1 and last.isalpha() and not before.endswith("°"):
        return True
    if word.isdigit() and len(word) <= 2 and (not before or before[-1] in "(:;."):
        return True
    return False


def _otc_items(unit: str) -> list[str]:
    out, start = [], 0
    for m in _OTC_ITEM.finditer(unit):
        i = m.start()
        rest = unit[i + 1:]
        lower = bool(re.match(r"[a-z0-9]", rest))
        if i == 0:
            continue
        if unit[i - 1] == ":":
            # a long lead-in ("signs of stomach bleeding: feel faint"), not "under 12 years: ask"
            if not lower or len(re.split(r"[.!?] ", unit[start:i])[-1].split(" ")) <= 6:
                continue
        elif not re.match(r"[A-Za-z0-9)\]]", unit[i - 1]):
            continue
        w = _LAST_WORD.search(unit[:i])
        prev = w.group(1).lower() if w else ""
        if lower and prev in NO_CUT_AFTER and not (prev == "you" and rest.startswith("you ")):
            continue
        out.append(unit[start:i])
        start = i + 1
    out.append(unit[start:])
    return out


def _split_unit(unit: str, otc: bool = False) -> list[str]:
    out, start = [], 0
    for m in (_BOUNDARY_OTC if otc else _BOUNDARY).finditer(unit):
        if _is_protected(unit[: m.start()], m.group(1)):
            continue
        end = m.end(2)
        out.append(unit[start:end].strip())
        start = m.end()
    out.append(unit[start:].strip())
    return out


def split_sentences(text: str, otc: bool = False) -> list[str]:
    """Split label text into sentences (see module docstring for the rules)."""
    text = _SPACES.sub(" ", text or "")
    sentences: list[str] = []
    for line in text.split("\n"):
        for unit in _BULLETS.split(line):
            unit = _WS.sub(" ", unit).strip()
            if not unit:
                continue
            for item in _otc_items(unit) if otc else [unit]:
                for s in _split_unit(item.strip(), otc):
                    if _HAS_ALNUM.search(s):
                        sentences.append(s)
    return sentences


def number_sentences(passages: list[list[str]], start: int = 1) -> list[list[tuple[int, str]]]:
    """Give every sentence across passages a running number starting at `start`."""
    n, out = start, []
    for sents in passages:
        row = []
        for s in sents:
            row.append((n, s))
            n += 1
        out.append(row)
    return out
