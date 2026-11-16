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
