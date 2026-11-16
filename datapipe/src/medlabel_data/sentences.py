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


def _split_unit(unit: str) -> list[str]:
    out, start = [], 0
    for m in _BOUNDARY.finditer(unit):
        if _is_protected(unit[: m.start()], m.group(1)):
            continue
        end = m.end(2)
        out.append(unit[start:end].strip())
        start = m.end()
    out.append(unit[start:].strip())
    return out


def split_sentences(text: str) -> list[str]:
    """Split label text into sentences (see module docstring for the rules)."""
    text = _SPACES.sub(" ", text or "")
    sentences: list[str] = []
    for line in text.split("\n"):
        for unit in _BULLETS.split(line):
            unit = _WS.sub(" ", unit).strip()
            if not unit:
                continue
            for s in _split_unit(unit):
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
