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
