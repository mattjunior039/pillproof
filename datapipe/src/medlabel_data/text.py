"""Token and number helpers shared by alignment, retrieval and checks.

Kept simple (regex + a crude suffix stemmer) so the same logic can be ported to
the browser for the app's number check.
"""

import re

STOPWORDS = set("""
a an the and or but if then than that this these those of to in on at by for from with without
as is are was were be been being it its it's into onto over under about after before during
while not no nor do does did done can could may might must should would will shall
has have had having which who whom whose what when where why how all any both each few more
most other some such only own same so too very s t just also there their they them he she
his her him we our you your i me my one ones per via upon within than vs e g ie eg
""".split())

_TOKEN = re.compile(r"[a-z]+|\d+(?:[.,]\d+)*")
_NUMBER = re.compile(r"(?<![0-9.,])\d+(?:[.,]\d+)*")
_WS = re.compile(r"\s+")


# Section cross-references such as "( 5.1 , 5.3 )", "(5.2)" or "[see Warnings and Precautions (5.1)]".
_XREF = re.compile(r"\[\s*see [^\]]*\]|\(\s*\d+(?:\.\d+)*\s*(?:[,;]\s*\d+(?:\.\d+)*\s*)*\)", re.I)


def strip_xrefs(text: str) -> str:
    text = re.sub(r"[ \t]{2,}", " ", _XREF.sub("", text or ""))
    text = re.sub(r" +([.,;:])", r"\1", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def norm_ws(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\u00a0", " ")).strip()


def stem(word: str) -> str:
    for suf, rep in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", ""), ("ly", "")):
        if word.endswith(suf) and len(word) - len(suf) >= 3:
            word = word[: -len(suf)] + rep
            break
    if word.endswith("e") and len(word) > 4:
        word = word[:-1]
    return word


def norm_number(num: str) -> str:
    num = num.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", num) else num.replace(",", ".")
    if "." in num:
        num = num.rstrip("0").rstrip(".")
    whole, dot, frac = num.partition(".")
    return (whole.lstrip("0") or "0") + dot + frac


def content_tokens(text: str) -> list[str]:
    """Lowercased, stemmed content words and normalized numbers, stopwords removed."""
    out = []
    for t in _TOKEN.findall((text or "").lower()):
        if t[0].isdigit():
            out.append(norm_number(t))
        elif t not in STOPWORDS and len(t) > 1:
            out.append(stem(t))
    return out


def numbers(text: str) -> set[str]:
    return {norm_number(n) for n in _NUMBER.findall((text or "").lower())}


# --- Restatement check (plan: "any number, unit, or drug name in the plain-language
# answer must also appear in the selected sentences"). Units are only counted when
# attached to a number ("10 mg", "2 hours") or after "/" or "per" ("mg/day", "per day").
_UNIT_CANON = {
    "mg": "mg", "milligram": "mg", "milligrams": "mg",
    "mcg": "mcg", "µg": "mcg", "μg": "mcg", "ug": "mcg", "microgram": "mcg", "micrograms": "mcg",
    "g": "g", "gram": "g", "grams": "g",
    "kg": "kg", "kilogram": "kg", "kilograms": "kg",
    "ml": "ml", "milliliter": "ml", "milliliters": "ml", "millilitre": "ml", "millilitres": "ml",
    "l": "l", "liter": "l", "liters": "l", "dl": "dl",
    "meq": "meq", "mmol": "mmol", "iu": "iu", "unit": "unit", "units": "unit",
    "%": "%", "percent": "%",
    "°c": "°c", "°f": "°f",
    "h": "hour", "hr": "hour", "hrs": "hour", "hour": "hour", "hours": "hour",
    "min": "minute", "minute": "minute", "minutes": "minute",
    "day": "day", "days": "day", "daily": "day",
    "week": "week", "weeks": "week", "weekly": "week",
    "month": "month", "months": "month", "year": "year", "years": "year",
}
_UNIT_ALT = "|".join(sorted((re.escape(u) for u in _UNIT_CANON), key=len, reverse=True))
_UNIT_AFTER_NUM = re.compile(rf"\d\s*-?\s*({_UNIT_ALT})(?![a-z])", re.I)
_UNIT_PER = re.compile(rf"(?:/\s*|\bper\s+)({_UNIT_ALT})(?![a-z])", re.I)
_DRUG_SUFFIX = re.compile(
    r"\b[a-z]{3,}(?:azole|olol|pril|sartan|statin|dipine|mycin|cillin|floxacin|tidine|prazole|"
    r"navir|tinib|mab|parin|oxetine|triptan|semide|thiazide|azepam|azolam|barbital|profen|"
    r"codone|morphone|gliptin|gliflozin|glitazone|lukast|dronate|setron|tadine)\b", re.I)


def units(text: str) -> set[str]:
    t = text or ""
    return {_UNIT_CANON.get(m.lower(), m.lower()) for m in _UNIT_AFTER_NUM.findall(t) + _UNIT_PER.findall(t)}


_LEX_RE: dict[frozenset, re.Pattern] = {}


def _lexicon_re(lexicon: set[str]) -> re.Pattern:
    key = frozenset(lexicon)
    if key not in _LEX_RE:
        alt = "|".join(re.escape(d) for d in sorted(key, key=len, reverse=True))
        # lookahead so overlapping names ("estradiol" inside "ethinyl estradiol") are all found
        _LEX_RE[key] = re.compile(rf"(?<![a-z])(?=({alt})(?![a-z]))")
    return _LEX_RE[key]


def drug_terms(text: str, lexicon: set[str]) -> set[str]:
    """Drug names in text: lexicon phrases (lowercase) plus words with common drug-name suffixes."""
    low = (text or "").lower()
    found = set(_lexicon_re(lexicon).findall(low)) if lexicon else set()
    found |= {d for d in lexicon if " " in d and d in low}
    return found | {m.lower() for m in _DRUG_SUFFIX.findall(low)}


def restatement_problems(restatement: str, source: str, lexicon: set[str]) -> list[str]:
    """Numbers, units and drug names in the restatement that are absent from the source."""
    probs = [f"number {n}" for n in sorted(numbers(restatement) - numbers(source))]
    probs += [f"unit {u}" for u in sorted(units(restatement) - units(source))]
    src = (source or "").lower()
    probs += [f"drug {d}" for d in sorted(drug_terms(restatement, lexicon)) if d not in src]
    return probs
