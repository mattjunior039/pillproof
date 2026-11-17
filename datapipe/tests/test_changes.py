"""Label-change pipeline: normalization, alignment, judge parsing and checks."""

import pytest

from medlabel_data.changes import judge
from medlabel_data.changes.align import align_versions
from medlabel_data.changes.baseline import baseline_label
from medlabel_data.changes.extract import Unit, Version, reflow
from medlabel_data.changes.normalize import is_admin, is_content, norm_key


def _version(n, sentences, group="warnings", fmt="PLR"):
    units = [Unit(group, "5.1 Bleeding", i, s, norm_key(s)) for i, s in enumerate(sentences)]
    return Version(n, f"2020-01-0{n}", None, fmt, units)


def _kinds(a, b):
    return sorted(c.kind for c in align_versions(a, b).candidates)


def test_norm_key_ignores_xrefs_bullets_and_quotes():
    a = "• Monitor INR closely [see Warnings and Precautions (5.2)]."
    b = "Monitor INR closely (5.2)."
    assert norm_key(a) == norm_key(b)
    assert norm_key("patient’s risk") == norm_key("patient's risk")
    assert norm_key("Take 2.5 mg") != norm_key("Take 5 mg")


@pytest.mark.parametrize("text,content", [
    ("Warnings and Precautions (5.1), Clinical Pharmacology (12.3)]", False),
    ("WARNINGS, PRECAUTIONS - Geriatric Use, and DOSAGE AND ADMINISTRATION", False),
    ("UPJ:MG:NRTNCTOS:RXB", False),
    ("Acute Kidney Injury", True),
    ("Avoid CYP3A4 inhibitors.", True),
])
def test_is_content(text, content):
    assert is_content(text) is content


def test_is_admin():
    assert is_admin("Revised: 12/2023")
    assert not is_admin("Bleeding can be serious.")


def test_reflow_joins_broken_lines_but_not_bullets():
    assert reflow("may cause serious\nbleeding in some patients.") == \
        "may cause serious bleeding in some patients."
    assert reflow("Tell your doctor if you:\n• bleed easily") == "Tell your doctor if you:\n• bleed easily"
    assert reflow("symptoms.Tell your doctor.") == "symptoms. Tell your doctor."


def test_reordering_and_reformatting_are_not_changes():
    a = _version(1, ["Bleeding can be serious [see (5.2)].", "Monitor patients for signs of bleeding."])
    b = _version(2, ["• Monitor patients for signs of bleeding.", "Bleeding can be serious."])
    assert _kinds(a, b) == []


def test_split_into_bullets_is_matched():
    a = _version(1, ["Avoid use with aspirin, NSAIDs, and warfarin."])
    b = _version(2, ["Avoid use with aspirin,", "NSAIDs,", "and warfarin."])
    assert _kinds(a, b) == []


def test_altered_added_removed():
    a = _version(1, ["Reduce the dose to 2.5 mg twice daily in patients with renal impairment.",
                     "This drug is not recommended for children."])
    b = _version(2, ["Reduce the dose to 5 mg once daily in patients with renal impairment.",
                     "Serious allergic reactions including anaphylaxis have been reported."])
    assert _kinds(a, b) == ["added", "altered", "removed"]


def test_repeated_sentence_is_not_listed():
    a = _version(1, ["Bleeding can be serious."])
    b = _version(2, ["Bleeding can be serious.", "Bleeding can be serious."])
    assert _kinds(a, b) == []


def test_systematic_product_name_edit_is_dropped():
    old = [f"Drugname may cause effect number {w} in some patients." for w in ("one", "two", "three")]
    new = [s.replace("Drugname", "Drugname tablets") for s in old]
    assert _kinds(_version(1, old), _version(2, new)) == []


def test_number_edit_is_never_systematic():
    old = [f"Use {n} mg of the drug for condition {w}." for n, w in ((10, "one"), (20, "two"), (30, "three"))]
    new = [s.replace(" mg", "0 mg") for s in old]
    assert _kinds(_version(1, old), _version(2, new)) == ["altered"] * 3


def test_format_conversion_flag():
    assert align_versions(_version(1, ["A b c d."], fmt="old"), _version(2, ["A b c d."])).format_conversion


def test_baseline_label():
    assert baseline_label(0.3) == "meaning changed"
    assert baseline_label(0.95) == "reworded"


def test_judge_parse_strips_thinking():
    raw = "<think>hmm</think>\nLABEL: Meaning changed\nEXPLANATION: The label now says 5 mg.\nextra"
    assert judge.parse(raw) == ("meaning changed", "The label now says 5 mg.")
    assert judge.parse("I am not sure.")[0] is None


ITEM = {"item_id": "T5-001", "id": "c1", "drug": "apixaban", "section": "7.1", "kind": "altered",
        "old_text": "Decrease the dose to 2.5 mg twice daily.",
        "new_text": "Decrease the dose by 50%.", "closest_text": "", "similarity": 0.6,
        "stratum": "altered_far", "weight": 1.0, "gold": "meaning changed"}


@pytest.mark.parametrize("expl,kept", [
    ("The label now says to decrease the dose by 50% instead of to 2.5 mg.", True),
    ("The label now says to decrease the dose to 10 mg.", False),  # number not in either sentence
    ("The label now mentions warfarin.", False),  # drug not in either sentence
    ("You should stop taking it.", False),  # advice
])
def test_judge_explanation_checks(expl, kept):
    row = judge.judge_item(ITEM, f"LABEL: meaning changed\nEXPLANATION: {expl}", judge.lexicon())
    assert (row["explanation"] is not None) is kept
    assert row["note"] == judge.SAFETY_NOTE


def test_judge_unparsable_counts_as_meaning_changed():
    row = judge.judge_item(ITEM, "no idea", judge.lexicon())
    assert row["label"] == "meaning changed" and not row["parsed"]


def test_judge_scoring_with_mock_backend():
    items = [ITEM, {**ITEM, "item_id": "T5-002", "id": "c2", "drug": "warfarin", "similarity": 0.95,
                    "new_text": "Decrease the dose to 2.5 mg two times daily.", "gold": "reworded"}]
    rows = judge.run(items, judge.MockBackend(items), judge.lexicon())
    s = judge.score(rows)
    assert s["label"]["catch_rate"] == 1.0 and s["label"]["false_flag_rate"] == 0.0
    assert s["parse_failures"] == 0


def test_judge_refuses_unmarked_t5(tmp_path, monkeypatch):
    (tmp_path / "t5_sheet.csv").write_text("t5_id,mark\nT5-001,meaning changed\nT5-002,\n")
    monkeypatch.setattr(judge, "T5_DIR", tmp_path)
    with pytest.raises(SystemExit, match="not fully marked"):
        judge.load_t5()
