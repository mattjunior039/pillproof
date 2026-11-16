"""Golden tests shared with the JS ports (core/tests/ports.test.mjs)."""

import json
from pathlib import Path

from medlabel_data import text as T
from medlabel_data.checks import check_reply, numbered_sentences

CORE = Path(__file__).resolve().parents[2] / "core"
LEX = set(json.loads((CORE / "data/lexicon.json").read_text()))


def _load(name):
    return json.loads((CORE / "fixtures" / name).read_text())


def test_check_cases():
    for c in _load("check_cases.json"):
        sents = {int(k): v for k, v in c["sentences"].items()}
        r = check_reply(c["reply"], sents, c["drug"], set(c["lexicon"]))
        for k, v in c["expect"].items():
            assert r[k] == v, (c["id"], k, r[k], v)
        if r["status"] == "answer":
            assert r["quotes"] == [[n, sents[n]] for n in r["sentences"]]


def test_text_cases():
    cases = _load("text_cases.json")
    for c in cases["text"]:
        assert T.content_tokens(c["text"]) == c["content_tokens"]
        assert sorted(T.numbers(c["text"])) == c["numbers"]
        assert sorted(T.units(c["text"])) == c["units"]
        assert sorted(T.drug_terms(c["text"], LEX)) == c["drug_terms"]
    for c in cases["restatement"]:
        assert T.restatement_problems(c["restatement"], c["source"], LEX) == c["problems"]


def test_numbered_sentences():
    p = "Drug: X\n\nLabel sentences:\n[Section: DOSAGE]\n[1] Take one.\n[12] Take two.\n\nQuestion: q"
    assert numbered_sentences(p) == {1: "Take one.", 12: "Take two."}


def test_retrieval_cases():
    from medlabel_data import retrieval as R

    fx = _load("retrieval_cases.json")
    idx = [R.LabelIndex([(h, s) for h, s in p]) for p in fx["labels"]]
    for c in fx["cases"]:
        ix = idx[c["label"]]
        assert R.scores(ix, c["question"], c["sims"], c["params"], set(c["exclude"])) == c["scores"]
        user, _, blocks = R.retrieve(ix, c["drug"], c["question"], c["sims"], c["params"], set(c["exclude"]))
        assert [[b, ids] for b, ids in blocks] == c["blocks"] and user == c["user"], c["id"]
