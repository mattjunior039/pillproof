"""Comparison keys for label sentences.

Two sentences whose keys are equal are treated as the same text: the difference is only
formatting. The key removes, in order:

1. Unicode variants (NFKC; "7½" = "7.5"), case, and trademark/footnote symbols
   (® ™ © * † ‡ § ¶).
2. Cross-references: "(5.2)", "( 5.1, 5.3 )", "[see Warnings and Precautions (5.1)]",
   "(see WARNINGS)", "(see PRECAUTIONS, Drug Interactions)", and the unclosed fragments the
   sentence splitter leaves when it cuts inside one ("[see Adverse Reactions (6", "(12.3 ").
3. Leading list markers (bullets, dashes, "1.", "2)", "(a)", "a.", "i."), also at the start
   of each table cell.
4. Table cell separators ("|") and all other punctuation, so a sentence broken across a
   list or table row, or a ";" that became ".", compares equal.
5. Hyphens and slashes inside words ("non-steroidal" = "nonsteroidal"), the word "per"
   ("%/year" = "% per year"), and a C or F right after a number ("20° to 25°C" = "20°C to 25°C").

Comparison symbols carry meaning and are kept as words: "<" lt, ">" gt, "≤" le, "≥" ge,
"±" pm, "%" pct. Numbers are normalized ("2.50" = "2.5", "1,000" = "1000").

`is_admin` marks boilerplate that is not safety content (revision dates, manufacturer and
distributor lines, addresses, phone numbers, web sites, "approved by the FDA" lines); those
sentences are left out of the comparison.
"""

import re
import unicodedata

from ..text import norm_number

_FRACTIONS = {"½": ".5", "¼": ".25", "¾": ".75"}
_INVISIBLE = re.compile("[\u00ad\u200b\u200c\u200d\u2060\ufeff]")
_SYMBOLS = re.compile(r"[®™©*†‡§¶]")
_XREF_BRACKET = re.compile(r"\[\s*see\b[^\]]*(?:\]|$)", re.I)
_XREF_SEE = re.compile(r"\(\s*see\b[^()]*(?:\([^()]*\)[^()]*)*(?:\)|$)", re.I)
_XREF_NUM = re.compile(r"\(\s*\d+(?:\.\d+)*\s*(?:[,;]\s*(?:and\s+)?\d+(?:\.\d+)*\s*)*\)")
_XREF_OPEN_START = re.compile(r"^\s*\(\s*\d+(?:\.\d+)+\s+")
_XREF_OPEN_END = re.compile(r"\(\s*\d+(?:\.\d+)*\s*$")
_LEAD = re.compile(r"^\s*(?:[•●▪◦■□○◆\-–—·o](?=\s)|\(?(?:\d{1,2}|[a-z]|[ivx]{1,4})[.)](?=\s))\s*", re.I)
_CMP = [("≤", " le "), ("≥", " ge "), ("<=", " le "), (">=", " ge "), ("<", " lt "), (">", " gt "),
        ("±", " pm "), ("%", " pct ")]
_INWORD = re.compile(r"(?<=[a-z])[-/](?=[a-z])")
_TOKEN = re.compile(r"[a-z]+|\d+(?:[.,]\d+)*")

_ADMIN = re.compile(
    r"\brevised\s*:|\brevised\s+\d{1,2}/\d{2,4}|\bissued\s*:|\brev\.\s*\d|\b(?:manufactured|distributed|marketed|"
    r"packaged|made|licensed)\s+(?:for|by|from|in)\b|\ball rights reserved\b|"
    r"\bhas been approved by the u\.?s\.? food and drug administration\b|www\.|\.com\b|"
    r"\b1-8\d\d-|\brevised\s+(?:[a-z]+\s+)?\d{4}\b|\blabel may have been updated\b|\b(?:Company|Corporation)\.?\s*$|\(\d{3}\)\s*\d{3}-\d{4}|\b[A-Z][a-z]+,\s*(?:NJ|NY|PA|NC|CT|IL|DE|CA|MA|IN|OH|PR)\s+\d{5}\b|"
    r"\b(?:Germany|Ireland|India|Puerto Rico|USA)\b\.?\s*$|\b(?:Ltd|Limited|Inc|LLC|Pvt|GmbH)\.?\s*$|©|\bcopyright\b|\blab-\d{3,}|\bUS Patent\b|\bpatents?:",
    re.I)


_SECTION_NAMES = (r"(?:Geriatric Use|Pediatric Use|Pregnancy|Information for Patients|Laboratory Tests|General|"
                  r"Boxed Warning|Indications and Usage|Dosage and Administration|Dosage Forms and Strengths|"
                  r"Contraindications|Warnings and Precautions|Adverse Reactions|Drug Interactions|"
                  r"Use in Specific Populations|Overdosage|Description|Clinical Pharmacology|Clinical Studies|"
                  r"Nonclinical Toxicology|How Supplied[^()]*|Patient Counseling Information|Warnings|Precautions)")
_XREF_FRAGMENT = re.compile(
    rf"^[\s\[()]*(?:and\s+)?(?:see\s+)?(?:{_SECTION_NAMES}\s*(?:\(\s*[\d.,\s]+\)?)?(?:[\s,;\-\]).]|\band\b|\bor\b)*)+$", re.I)

_CODE = re.compile(r"\b[A-Z0-9]*[A-Z]{2}[A-Z0-9]*:[A-Z0-9:]+\b|\b(?=(?:[A-Z]*\d){3})(?=(?:\d*[A-Z]){2})[A-Z0-9]{8,}\b")
_CAPS_TAIL = re.compile(r"^[^a-z]{0,40}[)\]]\W*$")


def is_content(text: str) -> bool:
    """False for fragments that carry no safety content on their own: page numbers, dates, lot
    codes, one-word table headers, and cross-reference tails the sentence splitter cut off
    ("Dosage and Administration (2.2)and")."""
    t = (text or "").strip()
    if _XREF_FRAGMENT.match(t) or _CAPS_TAIL.match(t):
        return False
    words = t.split()
    if len(words) <= 3 and t.upper() == t and not t.endswith((".", "!", "?")):
        return False  # all-caps heading
    if len(words) <= 6 and _CODE.search(t):
        return False  # lot, document or revision code
    return sum(1 for t in tokens(text) if len(t) > 1 and t.isalpha()) >= 2


def is_admin(text: str) -> bool:
    return bool(_ADMIN.search(text or ""))


def strip_markup(text: str) -> str:
    """Steps 1-3 without lowercasing or dropping punctuation."""
    t = text or ""
    for a, b in _FRACTIONS.items():
        t = re.sub(rf"(?<=\d){a}", b, t).replace(a, "0" + b)
    t = unicodedata.normalize("NFKC", t)
    t = _INVISIBLE.sub("", t)
    t = _SYMBOLS.sub("", t)
    t = _XREF_BRACKET.sub(" ", t)
    t = _XREF_SEE.sub(" ", t)
    t = _XREF_NUM.sub(" ", t)
    t = _XREF_OPEN_START.sub("", t)
    t = _XREF_OPEN_END.sub("", t)
    cells = []
    for cell in t.split("|"):
        prev = None
        while prev != cell:
            prev, cell = cell, _LEAD.sub("", cell, count=1)
        cells.append(cell)
    return " | ".join(cells)


def tokens(text: str) -> list[str]:
    t = strip_markup(text).lower()
    for a, b in _CMP:
        t = t.replace(a, b)
    t = _INWORD.sub("", t)
    out: list[str] = []
    for tok in _TOKEN.findall(t):
        if tok[0].isdigit():
            out.append(norm_number(tok))
        elif tok == "per" or (tok in ("c", "f") and out and out[-1][0].isdigit()):
            continue
        else:
            out.append(tok)
    return out


def norm_key(text: str) -> str:
    return " ".join(tokens(text))
