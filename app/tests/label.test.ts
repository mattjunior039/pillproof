import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { chunkLabel, hasPatientSection, sectionName, splitTitle } from "../src/lib/chunk.ts";
import { parseProduct, productsFrom, suggest } from "../src/lib/rxnorm.ts";
import { LabelIndex, retrieve, PHONE } from "../../core/retrieval.js";

const fx = (n: string) => JSON.parse(readFileSync(new URL(`./fixtures/${n}`, import.meta.url), "utf8"));
const rec = fx("atorvastatin_openfda.json");

test("chunker makes FDARxBench-style passages", () => {
  const p = chunkLabel(rec);
  const heads = new Set(p.map(([h]) => h));
  for (const h of ["5.1 Myopathy and Rhabdomyolysis", "8.1 Pregnancy Risk Summary", "8.5 Geriatric Use", "7.3 Atorvastatin Calcium Effects on Other Drugs",
    "2.1 Important Dosage Information", "How should I take atorvastatin calcium tablets?", "What should I avoid while taking atorvastatin calcium tablets?"]) {
    assert.ok(heads.has(h), h);
  }
  // No tables, clinical studies, nonclinical toxicology; child fields not duplicated.
  const all = p.flatMap(([, s]) => s).join(" ");
  assert.ok(!all.includes("<table") && !all.includes("ASCOT") && !/carcinogenicity study/.test(all));
  assert.equal(p.filter(([h]) => h === "12.1 Mechanism of Action").length, 1);
  assert.ok(p.every(([, s]) => s.length > 0 && s.join(" ").length < 1400));
  assert.ok(hasPatientSection(rec));
  assert.equal(sectionName("5 WARNINGS AND PRECAUTIONS"), "Warnings and Precautions");
  assert.equal(sectionName("8.1 Pregnancy Risk Summary"), "Pregnancy Risk Summary");
});

test("splitTitle keeps the title and leaves the sentence", () => {
  const d = new Set(["atorvastatin", "calcium"]);
  assert.deepEqual(splitTitle("Geriatric Use Of the total number", d), ["Geriatric Use", "Of the total number"]);
  assert.deepEqual(splitTitle("Myopathy and Rhabdomyolysis Atorvastatin calcium may cause", d), ["Myopathy and Rhabdomyolysis", "Atorvastatin calcium may cause"]);
});

test("retrieval finds grapefruit in chunked label", () => {
  const idx = new LabelIndex(chunkLabel(rec));
  const r = retrieve(idx, "Atorvastatin calcium", "Can I drink grapefruit juice?", null, PHONE);
  assert.ok(Object.values(r.sentences).some((s: any) => /grapefruit/i.test(s)));
  assert.ok(r.user.startsWith("Drug: Atorvastatin calcium\n\nLabel sentences:\n[Section: "));
});

test("rxnorm product parsing", () => {
  assert.deepEqual(
    (({ ingredient, strength, form, brand, combo }) => ({ ingredient, strength, form, brand, combo }))(parseProduct("atorvastatin 20 MG Oral Tablet [Lipitor]")),
    { ingredient: "atorvastatin", strength: "20 MG", form: "Oral Tablet", brand: "Lipitor", combo: false });
  const x = parseProduct("24 HR metformin hydrochloride 1000 MG / saxagliptin 5 MG Extended Release Oral Tablet");
  assert.equal(x.ingredient, "metformin hydrochloride / saxagliptin");
  assert.equal(x.strength, "1000 MG / 5 MG");
  assert.equal(x.form, "24 HR Extended Release Oral Tablet");
  assert.equal(parseProduct("atorvastatin 4 MG/ML Oral Suspension").strength, "4 MG/ML");
  const ps = productsFrom(fx("rxnav_atorvastatin.json"));
  assert.equal(ps[0].ingredient, "atorvastatin");
  assert.ok(!ps[0].combo && ps[0].tty === "SCD");
  assert.ok(ps.findIndex((p) => p.combo) > ps.findIndex((p) => p.brand === "Lipitor"));
  assert.deepEqual(suggest(["Lipitor", "atorvastatin", "Atorvaliq", "amlodipine / atorvastatin"], "ator"), ["Atorvaliq", "atorvastatin", "amlodipine / atorvastatin"]);
});

test("answer pipeline: checked answer, blocked restatement, decline, invalid, passage-only", async () => {
  const { answerQuestion, plainText } = await import("../src/lib/answer.ts");
  const idx = new LabelIndex(chunkLabel(rec));
  const label: any = { title: "Atorvastatin calcium", effective: "20250101" };
  const lexicon = new Set(["atorvastatin", "warfarin"]);
  const q = "Can I drink grapefruit juice?";
  const r = retrieve(idx, label.title, q, null, PHONE);
  const n = Number(Object.entries(r.sentences).find(([, s]: any) => /grapefruit/i.test(s))![0]);
  const ask = (reply: string) => answerQuestion(idx, label, q, { tier: "phone", lexicon, generate: async () => reply });

  const ok = await ask(`SENTENCES: ${n}\nANSWER: Avoid large amounts of grapefruit juice.`);
  assert.equal(ok.shown.kind, "answer");
  if (ok.shown.kind === "answer") assert.ok(/grapefruit/i.test(ok.shown.quotes[0].text) && ok.shown.quotes[0].section.length > 0);
  assert.equal((await ask(`SENTENCES: ${n}\nANSWER: Do not take more than 99 mg with warfarin.`)).shown.kind, "quotes");
  // Qualifier check: an unqualified "Yes" over "Avoid … more than 1.2 liters" shows the cited sentence instead.
  const yes = await ask(`SENTENCES: ${n}\nANSWER: Yes, you can drink grapefruit juice.`);
  assert.ok(yes.shown.kind === "quotes" && /grapefruit/i.test(yes.shown.quotes[0].text));
  // Over-declining (A1): the gate found grapefruit sentences, so they are quoted ("Your label says:"), not declined.
  const dec = await ask("NOT IN LABEL");
  assert.ok(dec.shown.kind === "passages" && dec.shown.why === "declined" && dec.shown.quotes.length >= 1 && dec.shown.quotes.length <= 3);
  if (dec.shown.kind === "passages") for (const x of dec.shown.quotes) assert.match(x.text, /grapefruit/i);
  assert.match(plainText(dec, false, "", "", "NOT COVERED"), /^Your label says: .*grapefruit/i);
  // With no topic words to match, a decline stays a decline (no unrelated sentences).
  const plain = await answerQuestion(idx, label, "Is it any good?", { tier: "phone", lexicon, generate: async () => "NOT IN LABEL" });
  assert.equal(plain.shown.kind, "decline");
  const bad = await ask("SENTENCES: 999\nANSWER: whatever");
  assert.equal(bad.shown.kind, "passages");
  // Degenerate repetition (lite-r3 4-bit on NUZYRA): never shown as the model's answer.
  const ones = "1" + "0".repeat(120);
  for (const reply of [`SENTENCES: ${n}\nANSWER: Take ${ones}`, `SENTENCES: ${ones}`, ones]) {
    const d = await ask(reply);
    assert.ok(d.shown.kind !== "answer" && !JSON.stringify(d.shown).includes("1000000"), reply.slice(0, 30));
  }
  const po = await answerQuestion(idx, label, q, { tier: "phone", lexicon });
  assert.ok(po.shown.kind === "passages" && po.shown.why === "no-model" && po.shown.quotes.some((x) => /grapefruit/i.test(x.text)));
});

test("OTC Drug Facts: run-together list items are split; Rx chunking is unchanged", () => {
  const otc = fx("goodys_otc_openfda.json");
  const sents = chunkLabel(otc).flatMap(([, s]) => s);
  assert.ok(sents.some((s) => /^children under 12 years of age: ask a doctor\.?$/.test(s)), "own item");
  assert.ok(!sents.some((s) => /24 hours.*children under 12/.test(s)));
  assert.ok(!sents.some((s) => /alcoholic drinks.*Stomach bleeding warning/.test(s)));
  // Rx labels keep FDARxBench sentence numbering (otc mode is off for them).
  const rx = chunkLabel(rec).flatMap(([, s]) => s);
  assert.ok(rx.length > 300 && rx.includes("Discontinue atorvastatin calcium if markedly elevated CK levels occur or myopathy is diagnosed or suspected."));
});

test("autocomplete ranks single ingredients and oral tablets first", () => {
  assert.deepEqual(suggest(["acetaminophen / aspirin", "Acetaminophen PM", "acetaminophen", "acetaminophen / caffeine"], "acetam"),
    ["acetaminophen", "Acetaminophen PM", "acetaminophen / aspirin", "acetaminophen / caffeine"]);
  const g = (tty: string, names: string[]) => ({ tty, conceptProperties: names.map((name, i) => ({ rxcui: `${tty}${i}`, name, synonym: "", tty })) });
  const ps = productsFrom({ drugGroup: { conceptGroup: [g("SCD", [
    "acetaminophen 325 MG / aspirin 500 MG Powder for Oral Solution",
    "100 ML acetaminophen 10 MG/ML Injection",
    "acetaminophen 500 MG Oral Tablet",
    "acetaminophen 160 MG/5ML Oral Suspension",
  ])] } });
  assert.deepEqual(ps.map((p) => p.form), ["Oral Tablet", "Oral Suspension", "100 ML Injection", "Powder for Oral Solution"]);
  assert.equal(ps[2].ingredient, "acetaminophen");
  assert.ok(ps[3].combo);
});

test("relevance gate: a topic the label never mentions is 'not found', never generic-word matches", async () => {
  const { answerQuestion, plainText } = await import("../src/lib/answer.ts");
  const otc = fx("goodys_otc_openfda.json");
  const idx = new LabelIndex(chunkLabel(otc));
  const label: any = { title: "Goodys Back and Body Pain", brandNames: ["Goodys Back and Body Pain"], genericNames: ["ACETAMINOPHEN AND ASPRIN"], effective: "20240101" };
  let called = false;
  const gen = async () => { called = true; return "NOT IN LABEL"; };
  const r = await answerQuestion(idx, label, "Can I drink grapefruit juice?", { tier: "phone", lexicon: new Set(), generate: gen });
  assert.deepEqual(r.shown, { kind: "not-found", missing: ["grapefruit juice"] });
  assert.equal(called, false, "model not run when nothing matches");
  const text = plainText(r, false, "", "Label information, not medical advice.", "");
  assert.match(text, /does not mention “grapefruit juice”\. That does not mean it is safe or unsafe/);
  assert.doesNotMatch(text, /\bis safe\b(?! or)/);
  // Alcohol is on this label: passages only about alcohol, at most 2, cited sentence plus lead-in at most.
  const a = await answerQuestion(idx, label, "Can I drink alcohol with it?", { tier: "phone", lexicon: new Set() });
  assert.ok(a.shown.kind === "passages" && a.shown.quotes.length > 0 && a.shown.quotes.length <= 2);
  if (a.shown.kind === "passages") for (const q of a.shown.quotes) assert.match(q.text, /alcohol/i);
  // A partly covered question names what is missing.
  const atorva = new LabelIndex(chunkLabel(rec));
  const m = await answerQuestion(atorva, { title: "Atorvastatin calcium", brandNames: [], genericNames: ["ATORVASTATIN CALCIUM"], effective: "" } as any,
    "Can I drink grapefruit juice or kombucha?", { tier: "phone", lexicon: new Set() });
  assert.equal(m.shown.kind, "passages");
  assert.deepEqual(m.missing, ["kombucha"]);
  if (m.shown.kind === "passages") assert.ok(m.shown.quotes.every((q) => /grapefruit/i.test(q.text)));
});

test("near-miss terms: grape juice is not grapefruit juice", async () => {
  const { answerQuestion, plainText } = await import("../src/lib/answer.ts");
  const { concepts } = await import("../src/lib/query.ts");
  const idx = new LabelIndex(chunkLabel(rec));
  const label: any = { title: "Atorvastatin calcium", brandNames: [], genericNames: ["ATORVASTATIN CALCIUM"], effective: "" };
  let called = false;
  const r = await answerQuestion(idx, label, "Can I take this with grape juice?", { tier: "phone", lexicon: new Set(), generate: async () => { called = true; return "NOT IN LABEL"; } });
  assert.deepEqual(r.shown, { kind: "not-found", missing: ["grape juice"] });
  assert.equal(called, false);
  assert.deepEqual(r.near, ["grapefruit juice"]);
  assert.match(plainText(r, false, "", "", ""), /does not mention “grape juice”\. It does mention “grapefruit juice”, which is different\. That does not mean it is safe or unsafe/);
  // Whole words by stem: plurals still match, longer words don't.
  const c = concepts("Can I eat grapes?", []).find((x) => x.name === "grapes")!;
  assert.ok(c.covers("avoid eating grapes") && c.covers("one grape") && !c.covers("grapefruit"));
});

test("lead-in context: a list item is shown with its unhighlighted lead-in", async () => {
  const { quoteAt } = await import("../src/lib/answer.ts");
  const p: any = { passages: [["Warnings", ["Ask a doctor before use if you have:", "liver disease", "asthma", "Keep out of reach of children."]],
    ["Directions", ["Directions", "Drink a full glass of water with each dose.", "children under 12 years: ask a doctor"]]] };
  assert.equal(quoteAt(p, 1, 2).before, "Directions");
  assert.equal(quoteAt(p, 0, 1).before, "Ask a doctor before use if you have:");
  assert.equal(quoteAt(p, 0, 2).before, "Ask a doctor before use if you have:");
  assert.equal(quoteAt(p, 0, 3).before, undefined);
});
