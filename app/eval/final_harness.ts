// Final evaluation harness (docs/final-eval.md): runs the frozen app pipeline in Node, item by item.
//
//   node eval/final_harness.ts --items <items.jsonl> --out <run.jsonl> --tier phone|desktop
//        [--gen http://127.0.0.1:8765] [--backups] [--web] [--model-key r1-ft]
//
// Same code path as store.ts answerFor() with the medicine already chosen (forced, router skipped):
//   bge q8 question embedding -> answerQuestion (relevance gate, retrieval, model, checks) ->
//   if unanswered and --backups: runBackups (other FDA labels live from openFDA, FDA consumer pages,
//   DDInter, then --web: Tavily through server/search.js handleSearch, 15 s timeout, one retry).
// The model is reached over HTTP (train/scripts/final/mlx_server.py) instead of WebLLM; with no --gen
// the app's passage-only mode runs (system D). Keys are read from ~/waicy-work/.env and never printed.
import { existsSync, mkdirSync, readFileSync, writeFileSync, appendFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { pipeline, env } from "@huggingface/transformers";
import { LabelIndex } from "../../core/retrieval.js";
import { EMBED_MODEL, makeQueryEmbedder, sentenceSims } from "../../core/embed.js";
import { answerQuestion, plainText, type AnswerResult } from "../src/lib/answer.ts";
import { backupText, medlineLink, runBackups, unanswered, type BackupOutcome } from "../src/lib/backup.ts";
import { otherLabels, toStored } from "../src/lib/openfda.ts";
import { ADVICE_LINE, NOT_COVERED, STANDING_LINE } from "../src/lib/router.ts";
import { webSearch } from "../src/lib/web.ts";
import { handleSearch } from "../server/search.js";
import type { Med } from "../src/lib/types.ts";

const args = process.argv.slice(2);
const arg = (k: string) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : undefined; };
const flag = (k: string) => args.includes(k);
const tier = (arg("--tier") || "phone") as "phone" | "desktop";
const genUrl = arg("--gen");
const backups = flag("--backups");
const web = flag("--web");
const modelKey = arg("--model-key");
const itemsPath = arg("--items")!;
const outPath = arg("--out")!;

const HOME = homedir();
const FINAL = join(HOME, "waicy-work/data/build/final");
const CACHE = join(FINAL, "cache");
for (const d of ["vectors", "openfda_other", "web"]) mkdirSync(join(CACHE, d), { recursive: true });
env.cacheDir = join(HOME, "waicy-work/hf_cache/transformers.js");

const envKey = (name: string) => {
  const line = readFileSync(join(HOME, "waicy-work/.env"), "utf8").split("\n").find((l) => l.startsWith(name + "="));
  return line ? line.slice(name.length + 1).trim().replace(/^["']|["']$/g, "") : "";
};
const lexicon = new Set<string>(JSON.parse(readFileSync(new URL("../../core/data/lexicon.json", import.meta.url), "utf8")));
const fdaFood = JSON.parse(readFileSync(new URL("../data/fda_food.json", import.meta.url), "utf8"));
const ddinter = JSON.parse(readFileSync(new URL("../data/ddinter_food.json", import.meta.url), "utf8"));

// ---- embeddings (same model, pooling and text as labels.ts / ml.worker.ts) -----------------
const extract: any = await pipeline("feature-extraction", EMBED_MODEL, { dtype: "q8" });
const embedQ = await makeQueryEmbedder(pipeline);
async function unitVectors(splId: string, texts: string[]): Promise<Float32Array[]> {
  const p = join(CACHE, "vectors", `${splId}.f32`);
  const dim = 384;
  if (existsSync(p)) {
    const buf = readFileSync(p);
    const all = new Float32Array(buf.buffer, buf.byteOffset, buf.byteLength / 4);
    if (all.length === texts.length * dim) return texts.map((_, i) => all.slice(i * dim, (i + 1) * dim));
  }
  const out: Float32Array[] = [];
  for (let i = 0; i < texts.length; i += 16) {
    const t = await extract(texts.slice(i, i + 16), { pooling: "cls", normalize: true });
    const d = t.dims[1];
    for (let j = 0; j < t.dims[0]; j++) out.push(Float32Array.from(t.data.subarray(j * d, (j + 1) * d)));
  }
  const flat = new Float32Array(out.length * dim);
  out.forEach((v, i) => flat.set(v, i * dim));
  writeFileSync(p, Buffer.from(flat.buffer));
  return out;
}

const labels = new Map<string, { stored: any; index: any; vectors: Float32Array[] }>();
async function labelFor(path: string) {
  if (labels.has(path)) return labels.get(path)!;
  const stored = toStored(JSON.parse(readFileSync(path, "utf8")));
  const texts = stored.passages.flatMap(([h, ss]: [string, string[]]) => ss.map((s) => (h ? `${h}: ${s}` : s)));
  const entry = { stored, index: new LabelIndex(stored.passages), vectors: await unitVectors(stored.splId, texts) };
  labels.set(path, entry);
  return entry;
}

// ---- model ---------------------------------------------------------------------------------
type Call = { user: string; raw: string; prompt_tokens: number; tokens_out: number; seconds: number };
let calls: Call[] = [];
async function generate(user: string): Promise<string> {
  const r = await fetch(`${genUrl}/gen`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user, max_tokens: tier === "phone" ? 128 : 256, mode: "label" }),
  });
  const j: any = await r.json();
  calls.push({ user, raw: j.reply, prompt_tokens: j.prompt_tokens, tokens_out: j.tokens_out, seconds: j.seconds });
  return j.reply;
}

// ---- backup sources ------------------------------------------------------------------------
const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "_").slice(0, 80);
async function cachedOtherLabels(m: Med, setId: string, limit: number) {
  const p = join(CACHE, "openfda_other", `${slug(m.ingredient)}_${m.rxcui}_${setId}_${limit}.json`);
  if (existsSync(p)) return JSON.parse(readFileSync(p, "utf8"));
  const recs = await otherLabels(m, setId, limit);
  writeFileSync(p, JSON.stringify(recs));
  return recs;
}
const tavilyKey = web ? envKey("TAVILY_API_KEY") : "";
const webCache = {
  get: async (k: string) => { const p = join(CACHE, "web", slug(k) + ".json"); return existsSync(p) ? JSON.parse(readFileSync(p, "utf8")) : undefined; },
  set: async (k: string, v: any) => { writeFileSync(join(CACHE, "web", slug(k) + ".json"), JSON.stringify(v)); },
};
let webCalls = 0;
const proxyFetch: typeof fetch = (async (_url: any, init: any) => {
  webCalls++;
  const [status, body] = await handleSearch(JSON.parse(init.body), { key: tavilyKey, fetchFn: fetch, cache: webCache });
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}) as any;

// ---- run -----------------------------------------------------------------------------------
const items = readFileSync(itemsPath, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
mkdirSync(dirname(outPath), { recursive: true });
const done = new Set<string>(existsSync(outPath) ? readFileSync(outPath, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l).id) : []);
const t0 = Date.now();
let n = 0;
for (const it of items) {
  if (done.has(it.id)) continue; // resume after a crash only; finished items are never re-run
  const lab = await labelFor(it.label_file);
  const meta = lab.stored.meta;
  const m: Med = { id: it.id, rxcui: it.rxcui || "", name: it.ingredient, ingredient: it.ingredient, strength: "", form: it.form || "Oral Tablet", times: [], created: 0, label: meta };
  calls = [];
  const tq = Date.now();
  const sims = sentenceSims(await embedQ(it.question), lab.vectors);
  const base = { tier, sims, lexicon, modelKey };
  const own = { ...base, quoteOnDecline: true }; // v1.1, as in store.ts; the v1.0 runs use the frozen tag's code
  const first: AnswerResult = await answerQuestion(lab.index, meta, it.question, genUrl ? { ...own, generate } : own);
  const labelCalls = calls.length;
  let backup: BackupOutcome | undefined, backupError: string | undefined;
  if (backups && unanswered(first)) {
    try {
      backup = await runBackups(m, meta, it.question, first, {
        fda: async () => fdaFood, ddinter: async () => ddinter,
        otherLabels: () => cachedOtherLabels(m, meta.setId, tier === "phone" ? 8 : 20),
        medline: () => medlineLink(m),
        web: web ? (ingr, q) => webSearch(ingr, q, "http://local/api/search", proxyFetch) : undefined,
      }, {
        opts: genUrl ? { ...base, sims: null, generate } : { ...base, sims: null },
        maxLabels: tier === "phone" ? 2 : 3, maxWeb: tier === "phone" ? 2 : 3, webOff: web ? undefined : "off",
      });
    } catch (e) { backupError = String((e as Error)?.message || e); }
  }
  const labelText = plainText(first, false, ADVICE_LINE, STANDING_LINE, NOT_COVERED);
  const shownText = backup ? [backupText(first, backup), STANDING_LINE].join(" ") : labelText;
  const row = {
    id: it.id, tier, model_key: modelKey || null, backups, web,
    label: { set_id: meta.setId, spl_id: meta.splId, title: meta.title, manufacturer: meta.manufacturer, effective: meta.effective },
    first: { shown: first.shown, missing: first.missing, near: first.near, raw: first.raw ?? null, ms: first.ms },
    label_text: labelText,
    label_calls: calls.slice(0, labelCalls),
    backup: backup ? { hit: backup.hit ? { source: backup.hit.source, shown: backup.hit.result.shown, raw: backup.hit.result.raw ?? null,
      label: backup.hit.result.label } : null, checked: backup.checked, topic: backup.topic, medline: backup.medline } : null,
    backup_error: backupError ?? null,
    backup_calls: calls.slice(labelCalls),
    shown_text: shownText,
    ms: Date.now() - tq,
  };
  appendFileSync(outPath, JSON.stringify(row) + "\n");
  if (++n % 20 === 0) console.log(`${n}/${items.length - done.size} ${((Date.now() - t0) / 1000).toFixed(0)}s`);
}
const meta = { items: itemsPath, tier, gen: genUrl || null, backups, web, model_key: modelKey || null, n, seconds: (Date.now() - t0) / 1000, web_requests: webCalls };
writeFileSync(outPath.replace(/\.jsonl$/, ".meta.json"), JSON.stringify(meta, null, 1));
console.log(JSON.stringify(meta));
