import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { route } from "../src/lib/router.ts";
import { answerSchedule, todayDoses, nextDoses, formatTime } from "../src/lib/schedule.ts";
import { buildIcs } from "../src/lib/ics.ts";
import { correctNames, medsMentioned } from "../src/lib/names.ts";
import { med } from "./helpers.ts";

const lex = new Set<string>(JSON.parse(readFileSync(new URL("../../core/data/lexicon.json", import.meta.url), "utf8")));
const ator = med({ ingredient: "atorvastatin", brand: "Lipitor", times: ["08:00", "20:00"] });
const metf = med({ ingredient: "metformin hydrochloride", strength: "500 MG", times: ["08:00"] });
const meds = [ator, metf];

test("emergency goes to the fixed message", () => {
  for (const q of ["I took too many atorvastatin", "my kid swallowed my pills", "can't breathe after metformin", "Overdose on lipitor?", "my throat is swelling"]) {
    assert.equal(route(q, meds, lex).kind, "emergency", q);
  }
  const r = route("I want to kill myself", meds, lex);
  assert.ok(r.kind === "emergency" && r.text.includes("988"));
});

test("schedule, label, choose, not on list, out of scope", () => {
  assert.equal(route("what's next?", meds, lex).kind, "schedule");
  assert.equal(route("When do I take my metformin", meds, lex).kind, "schedule");
  const l = route("can I drink grapefruit juice with atorvastatn", meds, lex);
  assert.ok(l.kind === "label" && l.med === ator);
  assert.ok((route("Can Lipitor cause muscle pain?", meds, lex) as any).med === ator);
  assert.equal(route("what are the side effects", meds, lex).kind, "choose");
  assert.ok((route("what are the side effects", [metf], lex) as any).med === metf);
  assert.ok((route("what is it used for", meds, lex, metf) as any).med === metf);
  const n = route("what is ibuprofen used for", meds, lex);
  assert.ok(n.kind === "not-on-list" && n.names.includes("ibuprofen"));
  // Interaction questions about a listed medicine go to that medicine's label.
  assert.equal(route("does ibuprofen interact with this", meds, lex).kind, "choose");
  assert.ok((route("can I take it with ibuprofen", [metf], lex) as any).med === metf);
  assert.equal(route("what's the capital of France", meds, lex).kind, "out-of-scope");
  assert.equal(route("tell me a joke", meds, lex).kind, "out-of-scope");
  const a = route("should I stop taking metformin", meds, lex);
  assert.ok(a.kind === "label" && a.advice);
});

test("name correction and matching", () => {
  // Speech recognisers split names into sound-alike words (real Moonshine outputs).
  assert.equal(correctNames("Can I drink grapefruit juice with the torefast tatten?", meds), "Can I drink grapefruit juice with the atorvastatin?");
  assert.equal(correctNames("side effects of lip it or", meds), "side effects of lipitor");
  assert.equal(correctNames("can I take met for men with alcohol", meds), "can I take metformin with alcohol");
  for (const q of ["What are the side effects?", "Can I take it at night with food?", "is it safe for my liver", "what is the starting dose"]) assert.equal(correctNames(q, meds), q);
  assert.equal(correctNames("does atorvastaten cause pain", meds), "does atorvastatin cause pain");
  assert.equal(correctNames("metforman with food", meds), "metformin with food");
  assert.deepEqual(medsMentioned("is lipitor safe", meds), [ator]);
});

test("today timeline and next dose", () => {
  const now = new Date(2026, 10, 12, 9, 30);
  const d = todayDoses(meds, now);
  assert.deepEqual(d.map((x) => x.state), ["past", "past", "next"]);
  const nx = nextDoses(meds, now)!;
  assert.equal(nx.time, "20:00");
  assert.equal(nx.minutesAway, 630);
  const late = nextDoses(meds, new Date(2026, 10, 12, 21, 0))!;
  assert.ok(late.tomorrow && late.meds.length === 2);
  assert.equal(formatTime("00:05"), "12:05 AM");
  assert.match(answerSchedule("what's next", meds, now), /^Next: Lipitor 20 mg tablet at 8:00 PM, in 10 hours and 30 minutes\.$/);
  assert.match(answerSchedule("when do I take metformin", meds, now), /metformin hydrochloride 500 mg tablet for 8:00 AM/);
  assert.match(answerSchedule("what are today's meds", meds, now), /^Today: 8:00 AM, Lipitor 20 mg tablet and metformin hydrochloride 500 mg tablet\. 8:00 PM, Lipitor/);
  assert.match(answerSchedule("what's next", [], now), /no medicines/);
});

test("ics export hides names by default", () => {
  const now = new Date(Date.UTC(2026, 10, 12, 12));
  const ics = buildIcs(meds, { includeNames: false, now });
  assert.ok(ics.includes("\r\n") && ics.endsWith("END:VCALENDAR\r\n"));
  assert.equal((ics.match(/BEGIN:VEVENT/g) || []).length, 2);
  assert.ok(!/lipitor|metformin|atorvastatin/i.test(ics));
  assert.equal((ics.match(/SUMMARY:Medication time\r\n/g) || []).length, 2);
  assert.ok(ics.includes("RRULE:FREQ=DAILY"));
  const named = buildIcs(meds, { includeNames: true, now });
  assert.ok(named.includes("SUMMARY:Medication time: Lipitor 20 mg tablet\\, metformin"));
  for (const line of named.split("\r\n")) assert.ok(new TextEncoder().encode(line).length <= 75, line);
});

test("label-change history matches medicines by ingredient or brand", async () => {
  const { historyKeys } = await import("../src/lib/changes.ts");
  const data = JSON.parse((await import("node:fs")).readFileSync(new URL("../data/label_changes.json", import.meta.url), "utf8"));
  assert.deepEqual(historyKeys({ ingredient: "atorvastatin calcium" }, data), ["atorvastatin"]);
  assert.deepEqual(historyKeys({ ingredient: "hydrochlorothiazide / lisinopril" }, data).sort(), ["hydrochlorothiazide", "lisinopril"]);
  assert.deepEqual(historyKeys({ ingredient: "xyz", brand: "Lipitor" }, data), ["atorvastatin"]);
  assert.deepEqual(historyKeys({ ingredient: "ibuprofen" }, data), []);
});
