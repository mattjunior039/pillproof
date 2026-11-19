import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { LabelIndex } from "../../core/retrieval.js";
import { answerQuestion } from "../src/lib/answer.ts";
import { runBackups, webAnswer, type BackupDeps } from "../src/lib/backup.ts";
import { pagePassages, rankResults, siteOf, type WebResult } from "../src/lib/web.ts";
import { handleSearch, limiter } from "../server/search.js";
import type { LabelMeta } from "../src/lib/types.ts";
import { med } from "./helpers.ts";

const data = (n: string) => JSON.parse(readFileSync(new URL(`../data/${n}`, import.meta.url), "utf8"));
const meta = (title: string): LabelMeta => ({
  splId: "s", setId: "set-1", manufacturer: "Maker", effective: "20260101", title,
  brandNames: [], genericNames: [title.toLowerCase()], hasPatient: true, fetched: 0,
});
const label = (drug: string) => new LabelIndex([
  ["How should I take it?", [`Take ${drug} tablets by mouth once a day, with or without food.`]],
  ["What are the possible side effects?", ["The most common side effects are headache, nausea and muscle aches."]],
]);
const page = (url: string, title: string, raw: string, tier: WebResult["tier"] = "consumer"): WebResult => ({ url, title, content: "", raw, tier });
const KOMBUCHA = page("https://www.example-health-blog.com/kombucha", "Kombucha and rosuvastatin | Blog", [
  "Home", "Menu", "Sign up for our newsletter",
  "Kombucha and statins",
  "Kombucha is a fermented tea that contains a small amount of alcohol.",
  "There are no studies of kombucha with rosuvastatin, so ask your pharmacist before drinking large amounts of kombucha.",
  "Share this article",
].join("\n"));
const OTHER_DRUG = page("https://medlineplus.gov/druginfo/meds/a600045.html", "Warfarin: MedlinePlus",
  "Warfarin and kombucha\nDo not drink large amounts of kombucha while taking warfarin without talking to your doctor.");

const opts = { opts: { tier: "phone" as const, lexicon: new Set<string>() }, maxLabels: 2 };
const deps = (over: Partial<BackupDeps> = {}): BackupDeps => ({
  fda: async () => data("fda_food.json"), ddinter: async () => data("ddinter_food.json"), otherLabels: async () => [],
  medline: async () => ({ title: "MedlinePlus: X", url: "https://medlineplus.gov/x.html" }), ...over,
});
async function ask(drug: string, q: string, d: BackupDeps, o: Partial<typeof opts & { webOff: "off" }> = {}) {
  const title = drug.replace(/^\w/, (c) => c.toUpperCase());
  const first = await answerQuestion(label(drug), meta(title), q, opts.opts);
  return runBackups(med({ ingredient: drug }), meta(title), q, first, d, { ...opts, ...o });
}

test("sites: consumer health sites first, unknown sites after, research papers last", () => {
  const ranked = rankResults([
    page("https://pubmed.ncbi.nlm.nih.gov/1", "Paper", ""),
    page("https://someblog.net/a", "Blog", "", "open"),
    page("https://www.drugs.com/a", "Drugs.com", ""),
    page("https://medlineplus.gov/a", "MedlinePlus", ""),
    page("https://health.ny.gov/a", "NY", ""),
  ]).map((r) => [r.site.host, r.site.kind]);
  assert.deepEqual(ranked, [
    ["medlineplus.gov", "consumer"], ["drugs.com", "consumer"], ["health.ny.gov", "consumer"],
    ["someblog.net", "other"], ["pubmed.ncbi.nlm.nih.gov", "technical"],
  ]);
  assert.equal(siteOf("https://www.nhs.uk/medicines/x/").name, "NHS (UK National Health Service)");
});

test("page text keeps prose and headings, drops menus and buttons", () => {
  const ps = pagePassages(KOMBUCHA);
  assert.deepEqual(ps.map((p) => p[0]), ["Kombucha and statins"]);
  assert.equal(ps[0][1].length, 2);
  assert.ok(!ps.flatMap((p) => p[1]).some((s) => /newsletter|Share this/.test(s)));
});

test("web answer: only ingredients and question are sent; pages about another drug are skipped; badge, site and links", async () => {
  const sent: unknown[] = [];
  const out = await ask("rosuvastatin", "Can I drink kombucha?", deps({
    web: async (ingr, q) => { sent.push([ingr, q]); return { query: "", results: [OTHER_DRUG, KOMBUCHA] }; },
  }));
  assert.deepEqual(sent, [[["rosuvastatin"], "Can I drink kombucha?"]]);
  assert.equal(out.hit?.source.kind, "web");
  assert.equal(out.hit!.source.site!.kind, "other", "unknown site: gets the Unverified website warning");
  assert.equal(out.hit!.source.badge, "From the web (example-health-blog.com) — not your label, may be wrong");
  const qs = (out.hit!.result.shown as any).quotes;
  assert.ok(qs.length && qs.every((q: any) => q.url.startsWith(KOMBUCHA.url + "#:~:text=")));
  assert.ok(qs.some((q: any) => /rosuvastatin/.test(q.text)) && !qs.some((q: any) => /warfarin/i.test(q.text)));
});

test("grape juice: a web page that only mentions grapefruit is not an answer", async () => {
  const grapefruit = page("https://www.mayoclinic.org/x", "Statins and grapefruit", "Grapefruit and statins\nGrapefruit juice can raise the level of atorvastatin in your blood, so avoid large amounts.");
  const out = await ask("atorvastatin", "Can I drink grape juice?", deps({ web: async () => ({ query: "", results: [grapefruit] }) }));
  assert.equal(out.hit, undefined);
  assert.ok(out.checked.includes("1 web page about atorvastatin"));
});

test("web answers never restate 'safe' or an unqualified yes: the site's sentences are shown instead", () => {
  const r = (restatement: string) => webAnswer({ shown: { kind: "answer", restatement, quotes: [{ text: "q", section: "s" }] }, label: meta("X"), ms: 0 }, true)!.shown.kind;
  assert.equal(r("Yes, you can drink grape juice."), "quotes");
  assert.equal(r("It is safe to take with food."), "quotes");
  assert.equal(r("There is no known interaction with grape juice."), "quotes");
  assert.equal(r("Take it at the same time each day."), "answer");
  assert.equal(webAnswer({ shown: { kind: "passages", why: "no-model", quotes: [{ text: "q", section: "s" }] }, label: meta("X"), ms: 0 }, false), null,
    "sentences without the asked topic are never shown");
});

test("web not available: the reason is listed, and the answer is still 'none of the sources'", async () => {
  const noKey = await ask("rosuvastatin", "Can I drink kombucha?", deps({ web: async () => { throw new Error("no-key"); } }));
  assert.equal(noKey.hit, undefined);
  assert.ok(noKey.checked.includes("the web (not checked: not set up on this server)"));
  const off = await ask("rosuvastatin", "Can I drink kombucha?", deps(), { webOff: "off" });
  assert.ok(off.checked.includes("the web (not checked: turned off in Settings)"));
});

test("proxy: no key, bad requests, cache hits cost nothing, rate limit", async () => {
  assert.deepEqual(await handleSearch({ ingredients: ["x"], question: "q?" }, { key: "" }), [503, { error: "no-key" }]);
  assert.equal((await handleSearch({ ingredients: [], question: "q?" }, { key: "k" }))[0], 400);
  assert.equal((await handleSearch({ ingredients: ["x"], question: "q".repeat(400) }, { key: "k" }))[0], 400);
  let calls = 0;
  const fetchFn = (async (_u: string, init: any) => {
    calls++;
    const body = JSON.parse(init.body);
    assert.equal(init.headers.Authorization, "Bearer k");
    assert.equal(body.search_depth, "advanced");
    return new Response(JSON.stringify({ results: [1, 2, 3].map((i) => ({ url: `https://medlineplus.gov/${i}`, title: "t", content: "c", raw_content: "r" })) }));
  }) as typeof fetch;
  const store = new Map();
  const cache = { get: (k: string) => store.get(k), set: (k: string, v: unknown) => void store.set(k, v) };
  const [s1, r1] = await handleSearch({ ingredients: ["x"], question: "Q?" }, { key: "k", fetchFn, cache });
  assert.equal(s1, 200);
  assert.equal(r1.results.length, 3);
  assert.equal(r1.credits, 2);
  const [, r2] = await handleSearch({ ingredients: ["x"], question: "q" }, { key: "k", fetchFn, cache });
  assert.equal(r2.cached, true);
  assert.equal(calls, 1);
  const allow = limiter({ perMinute: 1, perDay: 5 });
  assert.equal((await handleSearch({ ingredients: ["y"], question: "a" }, { key: "k", fetchFn, allow }))[0], 200);
  assert.deepEqual(await handleSearch({ ingredients: ["y"], question: "b" }, { key: "k", fetchFn, allow }), [429, { error: "rate-limit" }]);
});
