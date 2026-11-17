import json
from pathlib import Path

import pytest

from medlabel_data import labels, sections, text
from medlabel_data.fdarx import align, split, support
from medlabel_data.sentences import number_sentences, split_sentences
from medlabel_data.spl import parse_spl

FIXTURES = Path(__file__).parent / "fixtures"
CASES = json.loads((FIXTURES / "sentence_cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_sentence_golden(case):
    assert split_sentences(case["text"], otc=case.get("otc", False)) == case["sentences"]


def test_number_sentences_runs_across_passages():
    assert number_sentences([["a", "b"], ["c"]]) == [[(1, "a"), (2, "b")], [(3, "c")]]


@pytest.mark.parametrize("title,code,expected", [
    ("5.3 Hepatic Dysfunction", "42229-5", "warnings_precautions"),
    ("8.5 Geriatric Use", None, "specific_populations"),
    ("6.1 Clinical Trials Experience", None, "clinical_trials_ae"),
    ("Ask a doctor before use if you have", None, "otc_ask_doctor"),
    ("Some heading", "34070-3", "contraindications"),
    ("Some heading", "42229-5", "other"),
    ("DOSAGE & ADMINISTRATION", None, "dosage"),
])
def test_classify_section(title, code, expected):
    assert sections.classify_section(title, code) == expected


@pytest.mark.parametrize("name,expected", [
    ("AMLODIPINE BESYLATE", "amlodipine"),
    ("Metformin Hydrochloride", "metformin"),
    ("CALCIUM CARBONATE", "calcium carbonate"),
    ("emtricitabine and tenofovir alafenamide", "emtricitabine and tenofovir"),
])
def test_base_ingredient(name, expected):
    assert labels.base_ingredient(name) == expected


def test_numbers_normalized():
    assert text.numbers("Take 0.50 mg, up to 1,000 mg (2.5 times)") == {"0.5", "1000", "2.5"}


def test_strip_xrefs():
    assert text.strip_xrefs("Monitor INR ( 5.1 , 5.2 ) [see Warnings (5.1)].") == "Monitor INR."


def test_split_components_keep_shared_ingredients_together():
    label_ings = {"a": ["x"], "b": ["x", "y"], "c": ["y"], "d": ["z"]}
    comps = sorted(split.components(label_ings))
    assert comps == [["a", "b", "c"], ["d"]]
    out = split.assign(comps, {k: 10 for k in label_ings})
    assert out["a"] == out["b"] == out["c"]


def test_split_large_family_goes_to_train():
    comps = [["big"]] + [[f"s{i}"] for i in range(200)]
    weight = {"big": 100, **{f"s{i}": 5 for i in range(200)}}
    for seed in range(5):
        assert split.assign(comps, weight, seed=seed)["big"] == "train"


def test_align_picks_supporting_sentences():
    lab = align.Label({"set_id": "s", "drug_name": "Testdrug", "chunks": [
        "2.1 Dosage\nTake 10 mg once daily with food. Store in a dry place.",
        "5.1 Bleeding\nTestdrug can cause serious bleeding. Tell your doctor about bruising.",
    ]})
    assert lab.passages[0][0] == "2.1 Dosage"
    cands = [(c, s) for c in range(2) for s in range(len(lab.passages[c][1]))]
    answer = "Take 10 mg once daily with food."
    ans = align.answer_tokens(answer, "How much should I take?", {"testdrug"})
    chosen, coverage, missing, _ = align.align_answer(answer, cands, lab, ans)
    assert chosen == [(0, 0)]
    assert coverage == 1.0 and missing == []


def _decline_label():
    return align.Label({"set_id": "s", "drug_name": "Testdrug", "chunks": [
        "8.5 Geriatric Use\nIn geriatric patients, start at 5 mg once daily because of reduced renal clearance.",
        "What should I tell my doctor?\nIf you are older, your doctor may start you on 5 mg once daily. "
        "Tell your doctor if you have kidney problems.",
        "6 Adverse Reactions\nHeadache and nausea were the most common reactions.",
    ]})


def test_support_finds_lay_paraphrase_outside_removed_passage():
    lab = _decline_label()
    rec = {"target": "Elderly patients should start at 5 mg once daily due to reduced kidney clearance.",
           "question": "What is the starting dose for elderly patients?", "drug_name": "Testdrug"}
    res = support.supported_elsewhere(rec, lab, {0}, {"testdrug"})
    assert res["supported"] and res["sentences"][0][0] == 1
    # with both passages removed, nothing supports it
    assert not support.supported_elsewhere(rec, lab, {0, 1}, {"testdrug"})["supported"]


def test_support_requires_key_numbers():
    lab = _decline_label()
    rec = {"target": "Elderly patients should start at 2.5 mg once daily due to reduced kidney clearance.",
           "question": "What is the starting dose for elderly patients?", "drug_name": "Testdrug"}
    res = support.supported_elsewhere(rec, lab, {0}, {"testdrug"})
    assert not res["supported"] and "number 2.5" in res["key_fact_problems"]


SPL = b"""<?xml version="1.0"?>
<document xmlns="urn:hl7-org:v3">
 <code code="34391-3" codeSystem="2.16.840.1.113883.6.1" displayName="HUMAN PRESCRIPTION DRUG LABEL"/>
 <title>Testdrug tablets</title>
 <effectiveTime value="20240101"/>
 <setId root="ABC-123"/>
 <versionNumber value="3"/>
 <component><structuredBody>
  <component><section>
   <code code="34068-7" codeSystem="2.16.840.1.113883.6.1" displayName="DOSAGE &amp; ADMINISTRATION SECTION"/>
   <title>2 DOSAGE AND ADMINISTRATION</title>
   <excerpt><highlight><text><paragraph>Highlight text.</paragraph></text></highlight></excerpt>
   <component><section>
    <code code="42229-5" codeSystem="2.16.840.1.113883.6.1"/>
    <title>2.1 Drug Interactions Requiring Dose Changes</title>
    <text>
     <paragraph>Take 10 mg daily. Store at 20&#176;C to 25&#176;C.</paragraph>
     <list listType="unordered">
      <item><caption>o</caption>with food</item>
      <item>at bedtime</item>
     </list>
     <table><tbody>
      <tr><td>Drug</td><td>Dose</td></tr>
      <tr><td>A</td><td>5 mg</td></tr>
     </tbody></table>
    </text>
   </section></component>
  </section></component>
  <component><section>
   <code code="34067-9" codeSystem="2.16.840.1.113883.6.1"/>
   <title>INDICATIONS AND USAGE</title>
   <component><section><code code="42229-5" codeSystem="2.16.840.1.113883.6.1"/>
    <title>1. Hypertension</title><text><paragraph>Lowers blood pressure.</paragraph></text>
   </section></component>
  </section></component>
 </structuredBody></component>
</document>"""


def test_parse_spl():
    doc = parse_spl(SPL)
    assert (doc.set_id, doc.version, doc.effective_time) == ("abc-123", 3, "20240101")
    top, sub, ind, ind_sub = doc.sections
    assert top.category == "dosage" and top.text == ""  # highlights skipped
    assert sub.parent == 0 and sub.depth == 1
    assert sub.category == "dosage"  # PLR number wins over the words in the title
    assert sub.text.split("\n") == [
        "Take 10 mg daily. Store at 20°C to 25°C.", "• with food", "• at bedtime", "Drug | Dose", "A | 5 mg"]
    assert sub.sentences[:3] == ["Take 10 mg daily.", "Store at 20°C to 25°C.", "with food"]
    assert ind_sub.category == "indications"  # "1." in an old-format label is a list number


def test_units_attached_to_numbers_and_synonyms():
    assert text.units("Take 10 milligrams twice a day, max 80 mg/day, for 2 weeks at 25°C") == {
        "mg", "day", "week", "°c"}
    assert text.units("once a day for several weeks") == set()


def test_restatement_problems():
    lex = {"atorvastatin", "lipitor", "warfarin", "ethinyl estradiol", "estradiol"}
    src = "LIPITOR 10 mg once daily; ethinyl estradiol levels increased"
    assert text.restatement_problems("Take 10 milligrams of Lipitor each day.", src, lex) == []
    assert text.restatement_problems("Take 20 mg of Lipitor with warfarin for 2 hours.", src, lex) == [
        "number 2", "number 20", "unit hour", "drug warfarin"]
    assert text.drug_terms("ethinyl estradiol", lex) == {"ethinyl estradiol", "estradiol"}
