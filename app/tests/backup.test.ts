import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { LabelIndex } from "../../core/retrieval.js";
import { answerQuestion } from "../src/lib/answer.ts";
import { backupText, baseName, ddinterRows, medlineLink, runBackups, unanswered, type BackupDeps } from "../src/lib/backup.ts";
import type { LabelMeta, Med } from "../src/lib/types.ts";
import { med } from "./helpers.ts";

const data = (n: string) => JSON.parse(readFileSync(new URL(`../data/${n}`, import.meta.url), "utf8"));
const fda = data("fda_food.json");
const dd = data("ddinter_food.json");

const meta = (title: string): LabelMeta => ({
  splId: "s", setId: "set-1", manufacturer: "Maker", effective: "20260101", title,
  brandNames: [], genericNames: [title.toLowerCase()], hasPatient: true, fetched: 0,
});
/** A small label that never mentions food or drink. */
const plainLabel = (drug: string) => new LabelIndex([
  ["How should I take it?", [`Take ${drug} tablets by mouth once a day, with or without food.`, `Swallow ${drug} tablets whole with water.`]],
  ["What are the possible side effects?", ["The most common side effects are headache, nausea and muscle aches."]],
]);
const opts = { opts: { tier: "phone" as const, lexicon: new Set<string>() }, maxLabels: 2 };
const deps = (over: Partial<BackupDeps> = {}): BackupDeps => ({
  fda: async () => fda, ddinter: async () => dd, otherLabels: async () => [],
  medline: async () => ({ title: "MedlinePlus: X", url: "https://medlineplus.gov/druginfo/meds/x.html" }), ...over,
});
async function ask(m: Med, q: string, d = deps()) {
  const title = m.ingredient.replace(/^\w/, (c) => c.toUpperCase());
  const first = await answerQuestion(plainLabel(m.ingredient), meta(title), q, opts.opts);
  assert.ok(unanswered(first), `label should not answer "${q}"`);
  return { first, out: await runBackups(m, meta(title), q, first, d, opts) };
}

test("grapefruit on a statin whose label is silent: FDA consumer page, badged, quotes link to the page", async () => {
  const { first, out } = await ask(med({ ingredient: "simvastatin" }), "Can I drink grapefruit juice?");
  assert.equal(out.hit?.source.kind, "fda-page");
  assert.match(out.hit!.source.badge, /^Not on your label — from FDA: Grapefruit Juice and Some Drugs Don't Mix/);
  const qs = (out.hit!.result.shown as any).quotes;
  assert.ok(qs.some((q: any) => /simvastatin|Zocor/i.test(q.text)), "quotes the sentence naming the drug");
  assert.ok(qs.every((q: any) => q.url.startsWith("https://www.fda.gov/") && q.url.includes("#:~:text=")));
  assert.match(backupText(first, out), /^The label does not mention “grapefruit juice”\. .*Not on your label\. from FDA/);
});

test("no source mentions it: say so, never imply safe, link MedlinePlus", async () => {
  const { first, out } = await ask(med({ ingredient: "rosuvastatin" }), "Can I drink kombucha?");
  assert.equal(out.hit, undefined);
  const text = backupText(first, out);
  assert.match(text, /None of the sources we checked mention “kombucha” with this medicine\. Ask your pharmacist\./);
  assert.ok(text.includes("That does not mean it is safe or unsafe."));
  assert.doesNotMatch(text.replace("That does not mean it is safe or unsafe.", ""), /\bsafe\b|\bfine\b|\bok(ay)?\b/i);
  assert.match(out.medline.url, /medlineplus\.gov/);
  assert.deepEqual(out.checked, ["other FDA labels for rosuvastatin", "FDA consumer pages on food and drink", "the DDInter 2.0 drug–food database"]);
});

test("offline: other labels are reported as not checked, local sources still run", async () => {
  const { out } = await ask(med({ ingredient: "lisinopril" }), "Can I drink alcohol?", deps({ otherLabels: async () => { throw new Error("offline"); } }));
  assert.equal(out.hit?.source.kind, "ddinter");
  assert.ok(out.checked.includes("other FDA labels (not checked: no internet)"));
  assert.match(out.hit!.source.credit!.text, /CC BY-NC-SA 4\.0/);
});

test("combination products match only sources that name every ingredient", async () => {
  const goody = med({ ingredient: "acetaminophen / aspirin", form: "Oral Powder" });
  assert.deepEqual(ddinterRows(dd, goody), [], "DDInter rows are single-drug only");
  const { out } = await ask(goody, "Can I drink alcohol?");
  // The FDA page's pain-reliever row names both acetaminophen and aspirin.
  assert.equal(out.hit?.source.kind, "fda-page");
  const { out: none } = await ask(med({ ingredient: "acetaminophen / oxycodone" }), "Can I drink alcohol?");
  assert.equal(none.hit, undefined);
});

test("ingredient names: salts stripped, metals kept, DDInter synonyms", () => {
  assert.equal(baseName("Atorvastatin Calcium Trihydrate"), "atorvastatin");
  assert.equal(baseName("levothyroxine sodium"), "levothyroxine");
  assert.equal(baseName("ferrous sulfate"), "ferrous sulfate");
  assert.equal(baseName("aspirin"), "acetylsalicylic acid");
  const rows = ddinterRows({ ...dd, rows: [{ id: 1, drug: "Timolol (ophthalmic)", food: "x", level: "Minor", ddinter_id: "D", sentences: ["s"] }] }, med({ ingredient: "timolol maleate" }));
  assert.equal(rows.length, 0, "an ophthalmic-only row never matches an oral tablet");
});

test("MedlinePlus link falls back to the Connect page when the service is unreachable", async () => {
  const l = await medlineLink(med({ ingredient: "atorvastatin calcium", rxcui: "617310" }), (async () => { throw new Error("offline"); }) as any);
  assert.match(l.url, /^https:\/\/connect\.medlineplus\.gov\/application\?.*617310/);
});

test("chemistry mentions of alcohol (solubility, excipients) don't count as answering a drinking question", async () => {
  const ix = new LabelIndex([["11 DESCRIPTION", ["It is soluble in water and practically insoluble in alcohol.", "Inactive ingredients: cetyl alcohol and lactose."]]]);
  const r = await answerQuestion(ix, meta("Lisinopril"), "Can I drink alcohol?", opts.opts);
  assert.deepEqual(r.shown, { kind: "not-found", missing: ["alcohol"] });
});

test("a model decline on a curated source still shows its sentences; on other labels it counts as no answer", async () => {
  const m = med({ ingredient: "fexofenadine hydrochloride" });
  const first = await answerQuestion(plainLabel("fexofenadine"), meta("Fexofenadine"), "Can I drink grapefruit juice?", opts.opts);
  let calls = 0;
  const declines = { ...opts, opts: { ...opts.opts, generate: async () => { calls++; return "NOT IN LABEL"; } } };
  const other = { openfda: { generic_name: ["FEXOFENADINE HYDROCHLORIDE"] }, set_id: "set-2", effective_time: "20250101",
    indications_and_usage: ["Fexofenadine is used for allergies. Do not take with grapefruit juice."] };
  const out = await runBackups(m, meta("Fexofenadine"), "Can I drink grapefruit juice?", first, deps({ otherLabels: async () => [other] }), declines);
  assert.ok(calls >= 2, "the other label and the FDA page were both sent to the model");
  assert.equal(out.hit?.source.kind, "fda-page");
  assert.equal(out.hit!.result.shown.kind, "passages");
  assert.match((out.hit!.result.shown as any).quotes[0].text, /fexofenadine/i);
});
