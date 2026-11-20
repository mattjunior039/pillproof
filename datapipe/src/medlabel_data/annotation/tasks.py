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
RULE = "Humans only — no AI tools (no ChatGPT or similar), and don't look up the MedLabel app's answers."
REF_TAB = "Reference – label text"
SECOND_TAB = "Second check"
COLORS = {"markers": "C9DAF8", "pharmacist": "D9D2E9", "testers": "FCE5CD", "info": "E7E6E6"}


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
    marks: list[Mark]             # first mark is the one used for agreement; a mark without choices is notes
    role: str
    minutes: tuple[float, float]  # per row
    what: str
    examples: tuple[str, str]
    double: float = 0.0           # share of items copied to the Second check tab
    split: bool = True            # False: one expert does all of it (pharmacist)
    extra: Callable[[dict], dict] | None = None

    @property
    def primary(self) -> str:
        return self.marks[0].name

    @property
    def color(self) -> str:
        return COLORS[self.role]

    def mark(self, name: str) -> Mark | None:
        return next((m for m in self.marks if m.name == name), None)

    def second_map(self) -> dict[str, str]:
        """Second check column -> mark of this task."""
        out = {"answer": self.primary, "notes": [m.name for m in self.marks if not m.choices][-1]}
        if self.mark("only_formatting"):
            out["only_formatting"] = "only_formatting"
        return out

    def load(self) -> list[dict]:
        out = []
        for r in read_csv(self.source):
            d = {**r, **(self.extra(r) if self.extra else {})}
            out.append({"item_id": self.id_fn(r), "task": self.key, "name": "",
                        **{c: SCORE_TEXT.sub("", d.get(c, "")) for c, _ in self.show}})
        return out


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------- long label text: the audit's sentences shown and the decline-check labels ----------
@cache
def _audit_blocks(path: Path = AUDIT / "audit_100.md") -> dict[int, dict]:
    out = {}
    parts = re.split(r"^## (\d+)\. .*$", path.read_text(), flags=re.MULTILINE)
    for n, body in zip(parts[1::2], parts[2::2], strict=True):
        cited = re.search(r"\*\*Cited sentences:\*\*\n((?:- .*\n)+)", body)
        ref = re.search(r"^\*\*(?:FDARxBench reference|Answer that was removed):\*\* (.*)$", body, re.MULTILINE)
        shown = re.search(r"(?:All sentences shown to the model</summary>|\*\*Sentences shown[^\n]*)\n\n```\n(.*?)\n```",
                          body, re.DOTALL)
        out[int(n)] = {"cited_sentences": cited.group(1).strip() if cited else "",
                       "benchmark_reference": ref.group(1).strip() if ref else "",
                       "sentences_shown": shown.group(1) if shown else ""}
    return out


def _pointer(iid: str) -> str:
    return f"'{REF_TAB}' tab, filter item_id = {iid}"


def _audit_extra(r: dict) -> dict:
    iid = f"AUD-{int(r['n']):03d}"
    b = _audit_blocks()[int(r["n"])]
    return {"cited_sentences": b["cited_sentences"], "benchmark_reference": b["benchmark_reference"],
            "all_sentences": _pointer(iid)}


def ref_rows(items: list[dict]) -> list[dict]:
    """One row per line of label text for the audit and decline items given (too long for one cell)."""
    files = {f"DEC-{int(r['n']):02d}": r["label_file"] for r in read_csv(AUDIT / "decline_review_20.csv")}
    rows = []
    for it in items:
        if it["task"] == "audit":
            lines = _audit_blocks()[int(it["item_id"][4:])]["sentences_shown"].splitlines()
        elif it["task"] == "decline":
            lines = (AUDIT / files[it["item_id"]]).read_text().splitlines()
        else:
            continue
        rows += [{"item_id": it["item_id"], "line": i, "text": s} for i, s in enumerate(lines, 1) if s.strip()]
    return rows


T5_SHOW = [("drug", 14), ("section", 22), ("change_type", 13), ("old_sentence", 45), ("new_sentence", 45),
           ("closest_sentence_other_version", 40)]
KEEP = [Mark("user_status", ["keep", "edit", "drop"], 14), Mark("user_notes", None, 35)]

TASKS = [
    Task("T5", "Markers – T5 label changes", T5 / "t5_sheet.csv", lambda r: r["t5_id"], T5_SHOW,
         [Mark("mark", ["meaning changed", "reworded"], 20), Mark("only_formatting", ["y", "n"], 14),
          Mark("notes", None, 35)],
         "markers", (1, 1),
         "Each row is a sentence that differs between an old and a new version of a medicine label. "
         "mark: 'meaning changed' if information was added, removed or changed; 'reworded' if it says the same thing "
         "(for an added or removed sentence: the same information is still in the other version, see the closest "
         "sentence). only_formatting: 'y' if only punctuation, bullets, numbering or spacing differ.",
         ("'Take 1 tablet twice daily.' → 'Take 1 tablet two times a day.': reworded, n.",
          "'Do not use in children under 12 years.' → '... under 6 years.': meaning changed, n."),
         double=0.20),
    Task("T3", "Markers – T3 questions", paths.BUILD / "t3" / "t3_draft.csv", lambda r: r["t3_id"],
         [("drug", 14), ("topic", 13), ("answerable", 11), ("question", 40), ("reference_answer", 40),
          ("gold_section", 18), ("gold_text", 45), ("decline_evidence", 40), ("label_link", 22)],
         KEEP, "markers", (2, 3),
         "Test questions an older adult might ask about one medicine. If answerable = yes: is the question clear, do "
         "the label sentences (gold_text) answer it, and does reference_answer say only what they say? If answerable = "
         "no: does the label really not answer it (see decline_evidence, or open label_link)? user_status: keep / edit "
         "(write the fix in user_notes) / drop (say why).",
         (("'Can I take it with orange juice?', label 'Swallow with plain water only.', answer 'No, plain water "
          "only.': keep."),
          "'Is Tylenol OK with it?' marked not answerable, but the label lists acetaminophen: edit, 'label covers it'."),
         double=0.15, extra=lambda r: {"label_link": DAILYMED + r["set_id"]}),
    Task("T6", "Markers – T6 questions", paths.BUILD / "t6" / "t6_draft.csv", lambda r: r["t6_id"],
         [("drug", 14), ("product", 18), ("category", 15), ("question", 40), ("reference_note", 45),
          ("dangerous_if", 35), ("source_1", 24), ("source_2", 24), ("label_text", 40)],
         KEEP, "markers", (3, 4),
         "Questions for the app's web-search mode. category says where the answer comes from: the label, public "
         "health sources, or 'ask a pharmacist/doctor'. Open at least one source. Is reference_note right and plain, "
         "does the category fit, and does dangerous_if describe a truly harmful answer? user_status: keep / edit / drop.",
         ("Note 'take it 30–60 minutes before breakfast', NHS page says the same: keep.",
          "Note 'a little alcohol is fine', but the source says avoid alcohol: edit, 'source says avoid'."),
         double=0.15),
    Task("audit", "Markers – Training audit", AUDIT / "audit_review_20.csv", lambda r: f"AUD-{int(r['n']):03d}",
         [("drug", 14), ("kind", 11), ("question", 40), ("cited_sentences", 45), ("target", 45),
          ("original_answer_line", 40), ("benchmark_reference", 35), ("all_sentences", 20)],
         [Mark("user_verdict", ["ok", "wrong_sentences", "wrong_answer", "should_decline", "should_answer",
                                "bad_question"], 18), Mark("user_notes", None, 35)],
         "markers", (4, 4),
         "Rows of the model's training data. target is what the model learns to write: sentence numbers plus a "
         "plain answer, or NOT IN LABEL. Do the cited sentences support the answer? Does the answer add or change "
         "anything compared with original_answer_line? For NOT IN LABEL rows, check the full sentences (reference "
         "tab) really don't answer it. user_verdict: ok / wrong_sentences / wrong_answer / should_decline / "
         "should_answer / bad_question.",
         ("Answer says 'up to 4 times a day', cited sentence says 3: wrong_answer.",
          "Target NOT IN LABEL, but sentence [4] gives the dose asked about: should_answer."),
         extra=_audit_extra),
    Task("decline", "Markers – Decline check", AUDIT / "decline_review_20.csv", lambda r: f"DEC-{int(r['n']):02d}",
         [("drug", 14), ("question", 40), ("removed_answer", 45), ("all_sentences", 20)],
         [Mark("user_verdict", ["not_in_label", "answerable_elsewhere", "partly", "bad_question"], 20),
          Mark("user_where_found", None, 20), Mark("user_notes", None, 35)],
         "markers", (6, 10),
         "To teach the model to say 'the label doesn't cover this', the answer (removed_answer) was cut out of the "
         "label. Read the rest of the label (reference tab, filter on item_id): does it still answer the question? "
         "user_verdict: not_in_label / answerable_elsewhere / partly / bad_question; user_where_found: the section.",
         (("'What is the most I can take in a day?', section 17 still says 'no more than 8 tablets': "
          "answerable_elsewhere, '17'."),
          "Question about food; nothing left mentions food or meals: not_in_label."),
         extra=lambda r: {"all_sentences": _pointer(f"DEC-{int(r['n']):02d}")}),
    Task("pharmacist", "Pharmacist", T5 / "pharmacist_sheet.csv", lambda r: "PH-" + r["t5_id"], T5_SHOW,
         [Mark("mark", ["meaning changed", "reworded"], 20), Mark("only_formatting", ["y", "n"], 14),
          Mark("clinically_important", ["y", "n"], 14), Mark("notes", None, 35)],
         "pharmacist", (1, 2),
         "Each row is a sentence that differs between an earlier and the current SPL of the same product (section "
         "shown); the 30 rows are a random subset of the T5 items, which students mark separately. mark: 'meaning "
         "changed' if the clinical content differs (dose, population, indication, contraindication, warning, "
         "interaction, monitoring), 'reworded' if clinically equivalent; for an added or removed sentence, 'reworded' "
         "if the content is still in the other version (closest sentence shown). only_formatting: y if only "
         "punctuation, numbering or layout differ. clinically_important: y if the change could alter what a patient "
         "or prescriber does (new boxed warning, dose or renal adjustment, new contraindication).",
         ("'May cause dizziness.' → 'May cause dizziness or drowsiness.': meaning changed, n, y.",
          "'5.1 Lactic Acidosis' → '5.1 Lactic acidosis.': reworded, y, n."),
         split=False),
]
BY_KEY = {t.key: t for t in TASKS}

SECOND_WHAT = ("Do these only if you did NOT mark the same item on another tab. These are copies of some T5, T3 "
               "and T6 rows, used to measure how often two people agree. Mark them the same way: T5 rows → answer = "
               "meaning changed / reworded, plus only_formatting; T3 and T6 rows → answer = keep / edit / drop.")
LABELS = {"old_sentence": "OLD", "new_sentence": "NEW", "closest_sentence_other_version": "Closest sentence in the "
          "other version", "gold_text": "Label sentences", "reference_answer": "Reference answer"}


def second_text(task: Task, it: dict) -> str:
    return "\n".join(f"{LABELS.get(c, c.replace('_', ' ').capitalize())}: {it[c]}"
                     for c, _ in task.show if c != "drug" and it.get(c))
