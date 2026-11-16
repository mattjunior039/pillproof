// Golden tests shared with Python (datapipe/tests/test_checks.py): the JS ports must match exactly.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { splitSentences } from "../sentences.js";
import { contentTokens, numbers, units, drugTerms, restatementProblems } from "../text.js";
import { checkReply, numberedSentences } from "../checks.js";

const load = (p) => JSON.parse(readFileSync(new URL(p, import.meta.url), "utf8"));
const LEX = new Set(load("../data/lexicon.json"));
const sorted = (s) => [...s].sort();

test("sentence splitting matches datapipe fixtures", () => {
  for (const c of load("../../datapipe/tests/fixtures/sentence_cases.json")) {
    assert.deepEqual(splitSentences(c.text), c.sentences, c.id);
  }
});

test("text helpers match Python", () => {
  const { text, restatement } = load("../fixtures/text_cases.json");
  for (const c of text) {
    assert.deepEqual(contentTokens(c.text), c.content_tokens, c.text);
    assert.deepEqual(sorted(numbers(c.text)), c.numbers, c.text);
    assert.deepEqual(sorted(units(c.text)), c.units, c.text);
    assert.deepEqual(sorted(drugTerms(c.text, LEX)), c.drug_terms, c.text);
  }
  for (const c of restatement) {
    assert.deepEqual(restatementProblems(c.restatement, c.source, LEX), c.problems, c.restatement);
  }
});

test("reply checks match fixtures", () => {
  for (const c of load("../fixtures/check_cases.json")) {
    const r = checkReply(c.reply, c.sentences, c.drug, new Set(c.lexicon));
    for (const [k, v] of Object.entries(c.expect)) assert.deepEqual(r[k], v, `${c.id}.${k}`);
    if (r.status === "answer") {
      assert.deepEqual(r.quotes, r.sentences.map((n) => [n, c.sentences[n]]), c.id);
    }
  }
});

test("numberedSentences reads rendered prompts", () => {
  const p = "Drug: X\n\nLabel sentences:\n[Section: DOSAGE]\n[1] Take one.\n[12] Take two.\n\nQuestion: q";
  assert.deepEqual(numberedSentences(p), { 1: "Take one.", 12: "Take two." });
});
