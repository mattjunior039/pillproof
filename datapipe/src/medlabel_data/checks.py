"""Quote and number checks on a model reply (plan section 3, items 2 and 3).

1. Parse the reply (docs/output-format.md). A reply is a decline, an answer (sentence
   numbers plus an optional ANSWER line) or invalid. Parsing is mildly lenient (case,
   "**" bold markers, brackets around numbers, a trailing period, extra lines); `strict`
   records whether the reply matched the exact format. A first line that starts with
   "NOT IN LABEL" (any case, e.g. followed by advice) is a decline when no SENTENCES line follows.
2. Verify every cited number exists in the prompt; otherwise the reply is invalid (the app
   shows "not in label"; evaluation counts it as an error).
3. Copy the cited sentences from the prompt, so a displayed quote is always label text.
4. Number check: every number, unit and drug name in the ANSWER line must appear in the
   drug line or the cited sentences (text.restatement_problems). If not, the restatement
   is blocked and only the quotes are shown.

core/checks.js is the browser port; both run core/fixtures/check_cases.json.
"""

import re

from .text import restatement_problems

DECLINE = "NOT IN LABEL"

_THINK = re.compile(r"<think>.*?</think>", re.S)
_STRICT = re.compile(r"SENTENCES: \d+(, \d+)*\nANSWER: [^\n]+")
_SENT_LINE = re.compile(r"^\**\s*SENTENCES?\s*\**\s*:\s*\**\s*(.*)$", re.I)
_ANS_LINE = re.compile(r"^\**\s*ANSWER\s*\**\s*:\s*\**\s*(.*)$", re.I)
# Each separator is required ("," ";" or whitespace) so the pattern cannot backtrack exponentially
# on a long list cut off mid-line (seen on a 256-token "SENTENCES: 10, 11, 12, ..." reply).
_NUM_LIST = re.compile(r"^\d+(?:\s*[,;]\s*\d+|\s+\d+)*\s*\.?$")
_NUMBERED = re.compile(r"^\[(\d+)\] ([^\n]*)$", re.M)


def numbered_sentences(prompt: str) -> dict[int, str]:
    """The `[n] sentence` lines of a rendered prompt."""
    return {int(n): s for n, s in _NUMBERED.findall(prompt)}


def _norm_decline(line: str) -> str:
    return re.sub(r"[\s.!*\"']+$", "", re.sub(r"^[\s*\"']+", "", line)).upper()


def parse_reply(text: str) -> dict:
    """{'kind': 'decline'|'answer'|'invalid', 'sentences', 'answer', 'strict', 'error'}."""
    raw = _THINK.sub("", text or "").strip()
    out = {"kind": "invalid", "sentences": [], "answer": "", "strict": False, "error": ""}
    lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
    if "<think>" in raw:
        out["error"] = "unfinished think block"
        return out
    if not lines:
        out["error"] = "empty reply"
        return out
    idx = next((i for i, ln in enumerate(lines) if _SENT_LINE.match(ln)), None)
    first = _norm_decline(lines[0])
    if first == DECLINE or (idx is None and first.startswith(DECLINE)):
        out.update(kind="decline", strict=raw == DECLINE)
        return out
    if idx is None:
        out["error"] = "no SENTENCES line"
        return out
    rest = _SENT_LINE.match(lines[idx]).group(1)
    rest = re.sub(r"\band\b", " ", re.sub(r"[\[\]*]", "", rest)).strip()
    if not _NUM_LIST.match(rest):
        out["error"] = "SENTENCES line is not a list of numbers"
        return out
    nums = sorted({int(n) for n in re.findall(r"\d+", rest)})
    answer = ""
    for j in range(idx + 1, len(lines)):
        if m := _ANS_LINE.match(lines[j]):
            answer = " ".join([m.group(1).strip()] + lines[j + 1:]).strip()
            break
    out.update(kind="answer", sentences=nums, answer=answer, strict=bool(_STRICT.fullmatch(raw)))
    return out


def check_reply(text: str, sentences: dict[int, str], drug: str, lexicon: set[str]) -> dict:
    """Parse, verify numbers, copy quotes and run the number check.

    Returns the parse fields plus 'status' ('decline'|'answer'|'invalid'), 'quotes'
    ([[n, sentence], ...]), 'problems', 'blocked' and 'restatement' (the ANSWER line, or
    None when it is blocked or missing).
    """
    p = parse_reply(text)
    res = {**p, "status": p["kind"], "quotes": [], "problems": [], "blocked": False, "restatement": None}
    if p["kind"] != "answer":
        return res
    missing = [n for n in p["sentences"] if n not in sentences]
    if missing:
        res.update(status="invalid", error=f"cites sentence {missing[0]}, which is not in the prompt")
        return res
    res["quotes"] = [[n, sentences[n]] for n in p["sentences"]]
    source = drug + "\n" + "\n".join(s for _, s in res["quotes"])
    res["problems"] = restatement_problems(p["answer"], source, lexicon)
    res["blocked"] = bool(res["problems"]) or not p["answer"]
    res["restatement"] = None if res["blocked"] else p["answer"]
    return res
