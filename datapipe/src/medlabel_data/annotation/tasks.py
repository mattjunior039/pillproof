"""Annotation tasks for the shared workbook: where each sheet comes from, what a reviewer sees,
and which columns they fill in. See docs/annotation.md.

Reviewers mark blind: no AI verdicts or notes (ai_*), no hidden keys (t5_key_hidden), no scores
and no model outputs are ever shown. `BLOCKED` is enforced when a workbook is written.
"""

import csv
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from .. import paths

OUT = paths.BUILD / "annotation"
AUDIT = paths.BUILD / "fdarx" / "audit"
T5 = paths.BUILD / "changes" / "t5"
DAILYMED = "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid="
BLOCKED = re.compile(r"^ai_|key_hidden|coverage|score|r3_status|prediction|model_output|plain_language", re.IGNORECASE)
SCORE_TEXT = re.compile(r" ?\(coverage [\d.]+\)")  # support-check numbers inside T3/T6 evidence notes
RULE = ("Humans only: no ChatGPT or any other AI tool, and don't look up the MedLabel app's answers. "
        "Work on your own and don't compare marks with other annotators until everyone is done.")


@dataclass
class Mark:
    name: str
    choices: list[str] | None = None
    width: int = 18


@dataclass
class Task:
    key: str                      # value of the `task` column
    tab: str
    source: Path                  # sheet the marks are merged back into
    id_fn: Callable[[dict], str]  # source row -> stable item_id
    show: list[tuple[str, int]]   # (field, column width) shown to the reviewer; must include drug
    marks: list[Mark]             # first mark is the one used for agreement
    color: str
    minutes: str
    what: str
    examples: tuple[str, str]
    double: float = 0.0           # share of items given to two annotators by split
    split: bool = True            # False: one expert does all of it (pharmacist)
    extra: Callable[[dict], dict] | None = None

    @property
    def primary(self) -> str:
        return self.marks[0].name

    def load(self) -> list[dict]:
        out = []
        for r in read_csv(self.source):
            d = {**r, **(self.extra(r) if self.extra else {})}
            out.append({"item_id": self.id_fn(r), "task": self.key, "annotator": "",
                        **{c: SCORE_TEXT.sub("", d.get(c, "")) for c, _ in self.show}})
        return out


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------- audit: the sentences the model saw, from audit_100.md ----------
@cache
def _audit_blocks(path: Path = AUDIT / "audit_100.md") -> dict[int, dict]:
    out = {}
    parts = re.split(r"^## (\d+)\. .*$", path.read_text(), flags=re.MULTILINE)
    for n, body in zip(parts[1::2], parts[2::2]):
        cited = re.search(r"\*\*Cited sentences:\*\*\n((?:- .*\n)+)", body)
        ref = re.search(r"^\*\*(?:FDARxBench reference|Answer that was removed):\*\* (.*)$", body, re.MULTILINE)
        shown = re.search(r"(?:All sentences shown to the model</summary>|\*\*Sentences shown[^\n]*)\n\n```\n(.*?)\n```",
                          body, re.DOTALL)
        out[int(n)] = {"cited_sentences": cited.group(1).strip() if cited else "",
                       "benchmark_reference": ref.group(1).strip() if ref else "",
                       "sentences_shown": shown.group(1) if shown else ""}
    return out


def _audit_extra(r: dict) -> dict:
    return {"question_type": r["task"], **_audit_blocks()[int(r["n"])]}


def decline_label_rows(items: list[dict]) -> list[dict]:
    """One row per line of each decline item's label file (too long for one cell)."""
    by_id = {f"DEC-{int(r['n']):02d}": r["label_file"] for r in read_csv(AUDIT / "decline_review_20.csv")}
    rows = []
    for it in items:
        if it["task"] != "decline":
            continue
        for i, line in enumerate((AUDIT / by_id[it["item_id"]]).read_text().splitlines(), 1):
            if line.strip():
                rows.append({"item_id": it["item_id"], "line": i, "text": line})
    return rows


T5_MARKS = [Mark("mark", ["meaning changed", "reworded"], 20), Mark("only_formatting", ["y", "n"], 14),
            Mark("notes", None, 40)]
T5_SHOW = [("drug", 14), ("section", 28), ("change_type", 16), ("old_sentence", 60), ("new_sentence", 60),
           ("closest_sentence_other_version", 50)]
T5_WHAT = ("Each row is one sentence that differs between an older and a newer version of a drug label. "
           "mark: 'meaning changed' if information was really added, removed or altered; 'reworded' if the old and new "
           "sentence say the same thing. For an added or removed sentence, 'reworded' means the same information is still "
           "in the other version (e.g. in the closest sentence shown). only_formatting: 'y' if nothing but formatting differs "
           "(punctuation, bullets, numbering, spacing, a heading glued on), otherwise 'n'. notes: optional.")

TASKS = [
    Task("T5", "T5 label changes", T5 / "t5_sheet.csv", lambda r: r["t5_id"], T5_SHOW, T5_MARKS,
         "C9DAF8", "about 1 min", T5_WHAT,
         ("Old 'Take 1 tablet twice daily.' / new 'Take 1 tablet two times a day.' -> mark reworded, only_formatting n.",
          ("Old 'Do not use in children under 12 years.' / new 'Do not use in children under 6 years.' "
          "-> mark meaning changed, only_formatting n.")),
         double=0.20),
    Task("T3", "T3 questions", paths.BUILD / "t3" / "t3_draft.csv", lambda r: r["t3_id"],
         [("drug", 14), ("brand", 12), ("topic", 14), ("answerable", 11), ("question", 50), ("reference_answer", 50),
          ("gold_section", 22), ("gold_sentences", 12), ("gold_text", 60), ("alt_gold", 22), ("decline_evidence", 50),
          ("author_notes", 30), ("label_version", 10), ("label_link", 30)],
         [Mark("user_status", ["keep", "edit", "drop"], 14), Mark("user_notes", None, 45)],
         "D9EAD3", "2-3 min",
         "Test questions an older adult might ask about one drug. answerable=yes: check the question is natural and clear, "
         "gold_text (the label sentences) really answers it, and reference_answer says only what those sentences say. "
         "answerable=no: check from decline_evidence (open label_link if unsure) that the label truly doesn't answer it. "
         "user_status: keep / edit (write the fix in user_notes) / drop (say why).",
         (("Q 'Can I take my pill with orange juice?', gold 'Swallow with plain water only.', reference 'No. Take it with "
          "plain water only.' -> keep."),
          ("Q 'Is Tylenol OK with it?' marked answerable=no, but the label lists acetaminophen under drug interactions "
          "-> edit, note 'label covers acetaminophen in section 7; make it answerable'.")),
         double=0.15, extra=lambda r: {"label_link": DAILYMED + r["set_id"]}),
    Task("T6", "T6 questions", paths.BUILD / "t6" / "t6_draft.csv", lambda r: r["t6_id"],
         [("drug", 14), ("product", 22), ("category", 16), ("topic", 16), ("question", 50), ("reference_note", 55),
          ("dangerous_if", 40), ("source_1", 30), ("source_2", 30), ("label_ref", 24), ("label_text", 50),
          ("label_check", 45), ("author_notes", 30)],
         [Mark("user_status", ["keep", "edit", "drop"], 14), Mark("user_notes", None, 45)],
         "FFF2CC", "3-4 min",
         "Questions for the app's web-search mode. category says where the answer should come from: the product's label, "
         "public health sources, or 'ask a pharmacist/doctor' (or mixed evidence). Open at least one source. Check the "
         "reference_note is right and plain, the category fits, and dangerous_if describes a truly harmful answer. "
         "user_status: keep / edit (write the fix) / drop (say why).",
         ("Note 'take it 30-60 minutes before breakfast'; the NHS source says the same -> keep.",
          "Note 'a little alcohol is fine'; the source says avoid alcohol -> edit, note 'source says avoid'."),
         double=0.15),
    Task("audit", "Training audit", AUDIT / "audit_review_20.csv", lambda r: f"AUD-{int(r['n']):03d}",
         [("drug", 14), ("kind", 12), ("question_type", 12), ("question", 45), ("cited_sentences", 60), ("target", 60),
          ("original_answer_line", 50), ("benchmark_reference", 45), ("sentences_shown", 70)],
         [Mark("user_verdict", ["ok", "wrong_sentences", "wrong_answer", "should_decline", "should_answer",
                                "bad_question"], 18), Mark("user_notes", None, 45)],
         "FCE5CD", "about 4 min",
         "Rows from the model's training data. The model saw sentences_shown and has to output target: SENTENCES "
         "(numbers) plus a plain-language ANSWER, or NOT IN LABEL. Check that the cited sentences support the answer, the "
         "ANSWER doesn't add or change facts compared with original_answer_line, and for decline rows that the sentences "
         "shown really don't answer it. user_verdict: ok / wrong_sentences / wrong_answer / should_decline / "
         "should_answer / bad_question.",
         ("ANSWER says 'up to 4 times a day' but the cited sentence says 'up to 3 times a day' -> wrong_answer.",
          "Target is NOT IN LABEL, but sentence [4] gives exactly the dose asked about -> should_answer."),
         extra=_audit_extra),
    Task("decline", "Decline check", AUDIT / "decline_review_20.csv", lambda r: f"DEC-{int(r['n']):02d}",
         [("drug", 14), ("split", 8), ("question", 45), ("removed_answer", 60), ("label_text", 30)],
         [Mark("user_verdict", ["not_in_label", "answerable_elsewhere", "partly", "bad_question"], 20),
          Mark("user_where_found", None, 26), Mark("user_notes", None, 40)],
         "EAD1DC", "6-10 min",
         "For training 'the label does not cover this', each question's answer (removed_answer) was cut out of the label. "
         "Read the rest of that label in the 'Decline labels' tab (filter on item_id) and decide whether it still answers "
         "the question. user_verdict: not_in_label / answerable_elsewhere / partly / bad_question; user_where_found: the "
         "section where you found it.",
         (("Q 'What is the most I can take in a day?'; section 17 still says 'no more than 8 tablets in 24 hours' "
          "-> answerable_elsewhere, where found '17'."),
          "Q about taking it with food; nothing left in the label mentions food or meals -> not_in_label."),
         extra=lambda r: {"label_text": f"'Decline labels' tab, item_id DEC-{int(r['n']):02d}"}),
    Task("pharmacist", "Pharmacist", T5 / "pharmacist_sheet.csv", lambda r: "PH-" + r["t5_id"],
         [("t5_id", 10)] + T5_SHOW, T5_MARKS, "D9D2E9", "1-2 min",
         "Expert only. These 30 rows are a subset of T5 (same t5_id), marked independently by a pharmacist; the marks "
         "are compared with the T5 marks afterwards. " + T5_WHAT,
         ("Old 'May cause dizziness.' / new 'May cause dizziness or drowsiness.' -> meaning changed, only_formatting n.",
          "Old '5.1 Lactic Acidosis' / new '5.1 Lactic acidosis.' -> reworded, only_formatting y."),
         split=False),
]
BY_KEY = {t.key: t for t in TASKS}
