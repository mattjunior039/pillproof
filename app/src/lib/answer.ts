// Label question → retrieval → model (or passage-only) → checks → what the user sees (plan §5 steps 3-5).
// Pure apart from the injected `generate`, so it runs under node tests too.
import { DESKTOP, PHONE, render, scores, select } from "../../../core/retrieval.js";
import { checkReply } from "../../../core/checks.js";
import { contentTokens } from "../../../core/text.js";
import { sectionName } from "./chunk.ts";
import { concepts, nearMisses, searchQuery } from "./query.ts";
import type { LabelMeta } from "./types.ts";

/** A cited label sentence; `before` is an unhighlighted lead-in ("…if you have:") for context. */
export interface Quote { text: string; section: string; before?: string; url?: string }

export type Shown =
  /** Checked restatement plus the quoted label sentences it came from. */
  | { kind: "answer"; restatement: string; quotes: Quote[] }
  /** The model cited sentences but its restatement failed the number/unit/drug or qualifier check: quotes only. */
  | { kind: "quotes"; quotes: Quote[] }
  /** The model said the retrieved sentences don't answer it. */
  | { kind: "decline" }
  /**
   * No model (or its reply was unusable): the closest label sentences, clearly labelled as such.
   * "declined": the model said NOT IN LABEL but the relevance gate found sentences about the
   * question's topic, so those are quoted as "Your label says:" (extractive, no model text).
   */
  | { kind: "passages"; quotes: Quote[]; why: "no-model" | "invalid" | "error" | "declined" }
  /** No label sentence mentions what the question is about (e.g. "grapefruit juice"); the model is not run. */
  | { kind: "not-found"; missing: string[] };

export interface AnswerResult {
  shown: Shown;
  label: LabelMeta;
  /** Topics of the question that no label sentence mentions (shown as a note when the rest is answered). */
  missing?: string[];
  /** Similar-looking things the label does mention instead ("grapefruit juice" for "grape juice"). */
  near?: string[];
  /** Raw model reply, for the "details" disclosure. */
  raw?: string;
  modelKey?: string;
  ms: number;
}

export interface AnswerOpts {
  tier: "desktop" | "phone";
  sims?: number[] | null;
  lexicon: Set<string>;
  generate?: (user: string) => Promise<string>;
  modelKey?: string;
  passageCount?: number;
  /** General sources (FDA pages, DDInter): sentences matching this, e.g. the drug's name, rank higher. */
  prefer?: RegExp;
}

const heading = (index: any, c: number) => sectionName(index.passages[c][0] || "") || "Label";

/** Gate 2 retrieval (core/retrieval.js), scored on the expanded query; the prompt keeps the user's words. */
export function retrieveFor(index: any, drug: string, question: string, sims: number[] | null | undefined, params: any) {
  const p = { ...params };
  const blocks = select(index, scores(index, searchQuery(question), (sims ?? null) as any, p), p);
  return render(index.passages, blocks, drug, question);
}

/** Medication Guide / patient leaflet headings are questions ("What should I avoid while taking X?"). */
const PATIENT_HEAD = /\?\s*$|^(what|how|who|should|can|do|is|are)\b|patient information|medication guide/i;
/** Table fragments and cross-references like "( 1 )" or "7.1 3.8 4.0 ...". */
const readable = (s: string) =>
  (s.match(/[A-Za-z]{3,}/g) || []).length >= 4 && (s.match(/\d/g) || []).length < s.length / 6 && (s.match(/(?<![\w.])\d+\.\d+(?![\w.])/g) || []).length < 4;

/**
 * The lead-in a cited list item needs to make sense: the sentence before it if that ends
 * with ":", or for a lowercase Drug Facts item ("you have asthma") the nearest earlier
 * capitalized heading-like line, one without a full stop ("Ask a doctor before use if …").
 */
function leadIn(index: any, c: number, s: number): string | undefined {
  // Earlier sentences under the same heading, nearest first (a list can span passages).
  const prev: string[] = [];
  for (let pc = c, ps = s - 1; pc >= 0 && prev.length < 8; ) {
    if (ps < 0) {
      if (pc === 0 || index.passages[pc - 1][0] !== index.passages[c][0]) break;
      pc--; ps = index.passages[pc][1].length - 1;
      continue;
    }
    prev.push(index.passages[pc][1][ps--]);
  }
  if (prev.length && /:\s*$/.test(prev[0])) return prev[0];
  if (!/^[a-z]/.test(index.passages[c][1][s])) return undefined;
  return prev.find((x) => /^[A-Z]/.test(x) && !/[.!?]["')\]]*$/.test(x));
}

export function quoteAt(index: any, c: number, s: number): Quote {
  return { text: index.passages[c][1][s], section: heading(index, c), before: leadIn(index, c, s) };
}

/** Lowercased "heading: sentence" per retrieval unit, for concept matching ("" for table fragments). */
const unitText = (index: any, i: number) => {
  const [c, s] = index.units[i];
  const sent = index.passages[c][1][s];
  return readable(sent) ? `${index.passages[c][0] || ""}: ${sent}`.toLowerCase() : "";
};

/**
 * Relevance gate: which of the question's concepts the label mentions anywhere, and a
 * filter for sentences that mention at least one of them (everything, if the question
 * has no concepts, e.g. "What is atorvastatin?").
 */
export function coverage(index: any, question: string, ownNames: string[]) {
  const cs = concepts(question, ownNames);
  const texts: string[] = index.units.map((_: unknown, i: number) => unitText(index, i));
  const covered = cs.filter((c) => texts.some((t) => c.covers(t)));
  const notCovered = cs.filter((c) => !covered.includes(c));
  return {
    any: cs.length > 0,
    covered,
    missing: notCovered.map((c) => c.name),
    near: notCovered.flatMap((c) => nearMisses(c, texts)),
    keep: (i: number) => !cs.length || covered.some((c) => c.covers(texts[i])),
    /** Sentences under a heading about the asked topic ("How do I store …?") rank a little higher. */
    boost: (i: number) => (covered.some((c) => c.head?.test((index.passages[index.units[i][0]][0] || "").toLowerCase())) ? 0.1 : 0),
  };
}

/** Best label sentences, best first; patient-leaflet sentences slightly preferred; weak and off-topic matches dropped. */
export function topSentences(index: any, question: string, sims: number[] | null | undefined, params: any, n = 2,
  keep: (i: number) => boolean = () => true, boost: (i: number) => number = () => 0): Quote[] {
  const sc: number[] = scores(index, searchQuery(question), (sims ?? null) as any, params).map((x: number, i: number) => {
    const [c, s] = index.units[i];
    if (x <= 0 || !keep(i) || !readable(index.passages[c][1][s])) return 0;
    return x + (PATIENT_HEAD.test(index.passages[c][0] || "") ? 0.08 : 0) + boost(i);
  });
  const top = Math.max(0, ...sc);
  const ranked = sc.map((x, i) => i).filter((i) => sc[i] > 0 && sc[i] >= 0.6 * top).sort((a, b) => sc[b] - sc[a] || a - b);
  // The same item can appear twice on Drug Facts labels ("have 3 or more alcoholic drinks …").
  const best: number[] = [];
  const low = (i: number) => index.passages[index.units[i][0]][1][index.units[i][1]].toLowerCase();
  for (const i of ranked) {
    if (best.length >= n) break;
    if (!best.some((j) => low(j).includes(low(i)) || low(i).includes(low(j)))) best.push(i);
  }
  return best.map((i) => quoteAt(index, index.units[i][0], index.units[i][1]));
}

/**
 * The answer spells out an abbreviation differently from the quoted sentences ("premature menstruation
 * (PMDD)" where the label says "premenstrual dysphoric disorder (PMDD)"): the model made it up.
 */
export function wrongExpansion(restatement: string, quotes: string[]): string | null {
  const pre = (t: string) => t.slice(0, 5);
  const src = quotes.join(" ");
  for (const m of restatement.matchAll(/((?:[A-Za-z'-]+\s+){1,7})\(([A-Z]{2,6})s?\)/g)) {
    const acr = m[2];
    const q = src.match(new RegExp(`((?:[A-Za-z'-]+[\\s,]+){1,9})\\(${acr}s?\\)`));
    if (!q) continue;
    const said = m[1].trim().split(/\s+/).slice(-acr.length).join(" ");
    const theirs = new Set(contentTokens(q[1]).map(pre));
    if (contentTokens(said).some((t: string) => !theirs.has(pre(t)))) return acr;
  }
  return null;
}

/**
 * An answer cut off mid-sentence ("… adults with primary dysb") keeps its complete sentences only;
 * null if none is complete (then only the quoted label sentences are shown).
 */
export function completeSentences(restatement: string): string | null {
  const t = restatement.trim();
  if (/[.!?]["”’)]?$/.test(t)) return t;
  const m = t.match(/^[\s\S]*[.!?]["”’)]?(?=\s)/);
  return m ? m[0].trim() : null;
}

/** Most quotes shown under a model answer: highlighting only helps if it is selective. */
export const MAX_QUOTES = 3;

export async function answerQuestion(index: any, label: LabelMeta, question: string, o: AnswerOpts): Promise<AnswerResult> {
  const t0 = Date.now();
  const params = o.tier === "phone" ? PHONE : DESKTOP;
  const cov = coverage(index, question, [label.title, ...(label.brandNames || []), ...(label.genericNames || [])]);
  const missing = cov.missing.length ? cov.missing : undefined;
  const near = cov.near.length ? cov.near : undefined;
  if (cov.any && !cov.covered.length) return { shown: { kind: "not-found", missing: cov.missing }, label, near, ms: Date.now() - t0 };
  const passages = (why: "no-model" | "invalid" | "error" | "declined", n = o.passageCount ?? 2): Shown => {
    const prefer = (i: number) => (o.prefer?.test(index.passages[index.units[i][0]][1][index.units[i][1]]) ? 1 : 0);
    const quotes = topSentences(index, question, o.sims, params, n, cov.keep, (i) => cov.boost(i) + prefer(i));
    return !quotes.length && cov.any ? { kind: "not-found", missing: cov.missing.length ? cov.missing : cov.covered.map((c) => c.name) } : { kind: "passages", why, quotes };
  };
  if (!o.generate) return { shown: passages("no-model"), label, missing, near, ms: Date.now() - t0 };

  const r = retrieveFor(index, label.title, question, o.sims, params);
  const where = new Map<number, [number, number]>();
  for (const [key, n] of r.numbering as Map<string, number>) where.set(n, key.split(",").map(Number) as [number, number]);
  const raw = await o.generate(r.user);
  const chk = checkReply(raw, r.sentences, label.title, o.lexicon);
  const base = { label, raw, modelKey: o.modelKey, missing, near };
  const quotes = (): Quote[] => chk.quotes.slice(0, MAX_QUOTES).map(([n, text]: [number, string]) => {
    const at = where.get(n);
    return at ? { ...quoteAt(index, at[0], at[1]), text } : { text, section: "Label" };
  });
  const unitOf = new Map<string, number>(index.units.map((u: [number, number], i: number) => [`${u[0]},${u[1]}`, i]));
  const onTopic = (qs: [number, string][]) => qs.some(([n]) => {
    const at = where.get(n);
    const i = at && unitOf.get(`${at[0]},${at[1]}`);
    return i !== undefined && cov.keep(i);
  });
  let shown: Shown;
  if (chk.status === "decline") {
    // Over-declining: when the gate found sentences about the asked topic, quote them instead
    // (only then: with no topic words, or none in the label, unrelated sentences are never shown).
    // Every topic must be covered: for "stop suddenly" a sentence about stopping is not the answer.
    const q = cov.any && cov.covered.length && !cov.missing.length ? passages("declined", MAX_QUOTES) : null;
    shown = q && q.kind === "passages" && q.quotes.length ? q : { kind: "decline" };
  }
  else if (chk.status === "answer" && chk.quotes.length && cov.any && !onTopic(chk.quotes)) {
    // The model cited only sentences that don't mention what was asked ("used for" answered from a
    // varicella sentence): its answer is not grounded, so show the on-topic sentences instead.
    shown = passages("invalid");
  }
  else if (chk.status === "answer" && chk.quotes.length) {
    const qs = quotes();
    const said = completeSentences(chk.restatement || "");
    shown = chk.blocked || !said || wrongExpansion(said, qs.map((x) => x.text)) ? { kind: "quotes", quotes: qs } : { kind: "answer", restatement: said, quotes: qs };
  } else shown = passages("invalid");
  return { ...base, shown, ms: Date.now() - t0 };
}

/** Text for speech and for copying. */
/** "grapefruit juice", "coffee and tea", "a, b and c". */
export const listWords = (xs: string[]) => (xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);

/** The label is silent on this: say so plainly, and never let silence read as "safe". */
export const notMentioned = (missing: string[], near?: string[]) =>
  `The label does not mention ${listWords(missing.map((m) => `“${m}”`))}.` +
  (near?.length ? ` It does mention ${listWords(near.map((m) => `“${m}”`))}, which ${near.length > 1 ? "are" : "is"} different.` : "") +
  " That does not mean it is safe or unsafe.";

export function plainText(res: AnswerResult, advice: boolean, adviceLine: string, standing: string, notCovered: string): string {
  const s = res.shown;
  const parts: string[] = [];
  if (advice) parts.push(adviceLine);
  if (s.kind === "not-found") parts.push(notMentioned(s.missing, res.near), "Ask your pharmacist.");
  else if (res.missing?.length && s.kind !== "decline") parts.push(notMentioned(res.missing, res.near));
  if (s.kind === "answer") parts.push(s.restatement, "The label says: " + s.quotes.map((q) => q.text).join(" "));
  else if (s.kind === "quotes") parts.push("The label says: " + s.quotes.map((q) => q.text).join(" "));
  else if (s.kind === "decline") parts.push(notCovered);
  else if (s.kind === "not-found") { /* said above */ }
  else if (s.why === "declined") parts.push("Your label says: " + s.quotes.map((q) => q.text).join(" "));
  else if (s.quotes.length) parts.push("The closest sentences in the label: " + s.quotes.map((q) => q.text).join(" "));
  else parts.push(notCovered);
  parts.push(standing);
  return parts.join(" ");
}
