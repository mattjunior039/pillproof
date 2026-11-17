import pytest

from medlabel_data import t3

DOC = {
    "sections": [
        {"index": 0, "title": "Highlights", "first_id": 1, "sentences": ["Take once daily."]},
        {"index": 1, "title": "Medication Guide", "first_id": 2, "sentences": [
            "If you miss a dose, take it as soon as you remember.",
            "Do not take 2 doses at the same time.",
            "If you miss a dose, take it as soon as you remember.",
        ]},
    ],
    "openfda_words": t3._words("Place 1 tablespoon of applesauce into a clean container."),
}


def test_resolve_by_title_and_ids():
    r = t3.resolve(DOC, {"section": "medication guide", "snippets": ["Do not take 2 doses"]})
    assert r["nums"] == [2] and r["ids"] == [3]


def test_repeated_sentence_needs_pin():
    with pytest.raises(ValueError, match="matches 2 sentences"):
        t3.resolve(DOC, {"section": 1, "snippets": ["If you miss a dose"]})
    r = t3.resolve(DOC, {"section": 1, "snippets": [{"n": 3, "text": "If you miss a dose"}]})
    assert r["nums"] == [3] and r["ids"] == [4]
    with pytest.raises(ValueError, match="does not contain"):
        t3.resolve(DOC, {"section": 1, "snippets": [{"n": 2, "text": "If you miss a dose"}]})


def test_in_openfda_ignores_list_number():
    assert t3.in_openfda(DOC, "1. Place 1 tablespoon of applesauce into a clean container.")
    assert not t3.in_openfda(DOC, "Place 2 tablespoons of applesauce into a clean container.")
