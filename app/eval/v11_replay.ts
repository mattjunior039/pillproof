// v1.1 harm check on the T1 refusal items (docs/v1.1.md): replays the recorded model reply through the
// app's answerQuestion with the v1.1 display rule off and on. Every recorded T1 reply on these items
// (r1-ft 2B and 0.8B, docs/final-eval.md) is NOT IN LABEL, so no model is needed. Passages are the
// FDARxBench chunks and sims the T1 bge similarities (exported by train/scripts/final/v11_t1_export).
// Only the first step (the user's own label) is replayed; backup sources are not run.
//
//   node eval/v11_replay.ts --in <t1_refusal_replay_in.jsonl> --out <t1_refusal_replay.jsonl>
import { readFileSync, writeFileSync } from "node:fs";
import { LabelIndex } from "../../core/retrieval.js";
import { answerQuestion, plainText } from "../src/lib/answer.ts";
import { unanswered } from "../src/lib/backup.ts";
import { ADVICE_LINE, NOT_COVERED, STANDING_LINE } from "../src/lib/router.ts";

const args = process.argv.slice(2);
const arg = (k: string) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : undefined; };
const lexicon = new Set<string>(JSON.parse(readFileSync(new URL("../../core/data/lexicon.json", import.meta.url), "utf8")));
const items = readFileSync(arg("--in")!, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
const out: string[] = [];
for (const it of items) {
  const index = new LabelIndex(it.passages);
  if (index.units.length !== it.sims.length) throw new Error(`${it.qid}: ${index.units.length} units, ${it.sims.length} sims`);
  const label: any = { title: it.drug, brandNames: [], genericNames: [it.drug], effective: "" };
  for (const tier of ["desktop", "phone"] as const) {
    const run = async (quoteOnDecline: boolean) => {
      const r = await answerQuestion(index, label, it.question, { tier, sims: it.sims, lexicon, generate: async () => "NOT IN LABEL", quoteOnDecline });
      return { shown: r.shown, missing: r.missing ?? null, backups_run: unanswered(r), text: plainText(r, false, ADVICE_LINE, STANDING_LINE, NOT_COVERED) };
    };
    const v10 = await run(false), v11 = await run(true);
    out.push(JSON.stringify({ qid: it.qid, drug: it.drug, question: it.question, tier, v10, v11, changed: v10.text !== v11.text }));
  }
}
writeFileSync(arg("--out")!, out.join("\n") + "\n");
const rows = out.map((l) => JSON.parse(l));
for (const tier of ["desktop", "phone"]) {
  const t = rows.filter((r) => r.tier === tier);
  console.log(tier, { items: t.length, changed: t.filter((r) => r.changed).length, v10_kinds: count(t.map((r) => kind(r.v10))), v11_kinds: count(t.map((r) => kind(r.v11))) });
}
function kind(x: any) { return x.shown.kind + (x.shown.why ? `/${x.shown.why}` : ""); }
function count(xs: string[]) { const c: Record<string, number> = {}; for (const x of xs) c[x] = (c[x] || 0) + 1; return c; }
