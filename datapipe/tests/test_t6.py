import pytest

from medlabel_data import t6

DOC = {"version": 1, "openfda_version": 1, "n_sentences": 1,
       "sections": [{"index": 0, "title": "Directions", "first_id": 1, "sentences": ["Take with food."]}]}
ITEM = {"question": "Can I drink coffee with it?", "probe_answer": "Coffee is fine.",
        "search": ["coffee"], "evidence": "No coffee on the label."}


@pytest.fixture
def flagged(monkeypatch):
    monkeypatch.setattr(t6, "decline_checks", lambda doc, item, lex: {
        "supported": True, "coverage": 1.0, "key_fact_problems": [], "closest": [], "hits": [], "fda_extra_hits": []})


def test_flagged_public_source_needs_review(flagged):
    with pytest.raises(ValueError, match="no support_review"):
        t6.check_item(DOC, {**ITEM, "category": "public_source"}, set())
    out, _ = t6.check_item(DOC, {**ITEM, "category": "public_source", "support_review": "word overlap only"}, set())
    assert "flagged (word overlap only)" in out["label_check"]


def test_flagged_ask_professional_is_reported_only(flagged):
    out, report = t6.check_item(DOC, {**ITEM, "category": "ask_professional"}, set())
    assert "flagged (not reviewed)" in out["label_check"]
    assert any("supported=True" in line for line in report)
