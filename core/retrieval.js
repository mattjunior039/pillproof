// Hybrid retrieval over one drug label: port of datapipe/src/medlabel_data/retrieval.py.
// Golden test: core/fixtures/retrieval_cases.json (core/tests, datapipe/tests).

import { contentTokens } from "./text.js";

export const DEFAULTS = { w_sent: 0.3, w_pass: 0.3, w_emb: 0.4, context: 1, budget: 1500, max_seeds: 12 };
export const PHONE = { ...DEFAULTS, budget: 1600, max_seeds: 12 };
export const DESKTOP = { ...DEFAULTS, budget: 3500, max_seeds: 30 };
const SENT_COST = 6;
const HEAD_COST = 12;

const counter = (xs) => {
  const m = new Map();
  for (const x of xs) m.set(x, (m.get(x) || 0) + 1);
  return m;
};

export class BM25 {
  constructor(docs, k1 = 1.2, b = 0.75) {
    this.docs = docs.map(counter);
    this.len = docs.map((d) => d.length);
    const total = this.len.reduce((a, x) => a + x, 0);
    this.avg = docs.length && total ? total / docs.length : 1.0;
    const df = new Map();
    for (const d of this.docs) for (const t of d.keys()) df.set(t, (df.get(t) || 0) + 1);
    const n = docs.length;
    this.idf = new Map([...df].map(([t, f]) => [t, Math.log(1 + (n - f + 0.5) / (f + 0.5))]));
    this.k1 = k1;
    this.b = b;
  }

  scores(query) {
    const terms = [...new Set(query)].sort();
    return this.docs.map((d, i) => {
      let s = 0.0;
      for (const t of terms) {
        const f = d.get(t);
        if (f) s += (this.idf.get(t) * f * (this.k1 + 1)) / (f + this.k1 * (1 - this.b + (this.b * this.len[i]) / this.avg));
      }
      return s;
    });
  }
}

const scale = (xs) => {
  if (!xs.length) return [];
  const lo = Math.min(...xs);
  const hi = Math.max(...xs);
  return xs.map((x) => (hi > lo ? (x - lo) / (hi - lo) : 0.0));
};

/** Sentence and passage BM25 for one label. `passages` is [[heading, [sentences]], ...]. */
export class LabelIndex {
  constructor(passages) {
    this.passages = passages;
    this.units = [];
    passages.forEach(([, sents], c) => sents.forEach((_, s) => this.units.push([c, s])));
    this.sentBm25 = new BM25(this.units.map(([c, s]) => contentTokens(passages[c][0] + "\n" + passages[c][1][s])));
    this.passBm25 = new BM25(passages.map(([h, ss]) => contentTokens(h + "\n" + ss.join("\n"))));
  }
}

/** Combined score per unit (aligned with index.units); excluded passages get -1. */
export function scores(index, question, sims, params, exclude = new Set()) {
  const q = contentTokens(question);
  const keep = [];
  index.units.forEach(([c], i) => { if (!exclude.has(c)) keep.push(i); });
  const sb = index.sentBm25.scores(q);
  const pb = index.passBm25.scores(q);
  const sbK = scale(keep.map((i) => sb[i]));
  const pbK = scale(keep.map((i) => pb[index.units[i][0]]));
  const emK = sims ? scale(keep.map((i) => sims[i])) : keep.map(() => 0.0);
  const wE = sims ? params.w_emb : 0.0;
  const out = index.units.map(() => -1.0);
  keep.forEach((i, j) => { out[i] = params.w_sent * sbK[j] + params.w_pass * pbK[j] + wE * emK[j]; });
  return out;
}

/** Blocks [[passage, [sentence ids]], ...] chosen best-first under the character budget. */
export function select(index, unitScores, params) {
  const order = unitScores.map((x, i) => i).filter((i) => unitScores[i] >= 0)
    .sort((a, b) => unitScores[b] - unitScores[a] || a - b);
  const chosen = new Map();
  const first = new Map();
  let used = 0;
  let seeds = 0;
  for (const i of order) {
    if (seeds >= params.max_seeds) break;
    const [c, s] = index.units[i];
    const have = chosen.get(c) || new Set();
    if (have.has(s)) continue;
    const sents = index.passages[c][1];
    const k = params.context;
    const head = chosen.has(c) ? 0 : index.passages[c][0].length + HEAD_COST;
    let add = [];
    for (let j = Math.max(0, s - k); j < Math.min(sents.length, s + k + 1); j++) if (!have.has(j)) add.push(j);
    let cost = head + add.reduce((a, j) => a + sents[j].length + SENT_COST, 0);
    if (used + cost > params.budget) {
      add = [s];
      cost = head + sents[s].length + SENT_COST;
      if (used + cost > params.budget) break;
    }
    if (!chosen.has(c)) chosen.set(c, have);
    for (const j of add) have.add(j);
    if (!first.has(c)) first.set(c, seeds);
    used += cost;
    seeds += 1;
  }
  return [...chosen.keys()].sort((a, b) => first.get(a) - first.get(b))
    .map((c) => [c, [...chosen.get(c)].sort((a, b) => a - b)]);
}

/** Same text as fdarx/build.render. Returns {user, numbering: Map("c,s" -> n), sentences: {n: text}}. */
export function render(passages, blocks, drug, question) {
  let n = 1;
  const lines = [];
  const numbering = new Map();
  const sentences = {};
  for (const [chunk, ids] of blocks) {
    const head = passages[chunk][0];
    lines.push(head ? `[Section: ${head}]` : "[Section]");
    for (const s of ids) {
      const text = passages[chunk][1][s];
      lines.push(`[${n}] ${text}`);
      numbering.set(`${chunk},${s}`, n);
      sentences[n] = text;
      n += 1;
    }
    lines.push("");
  }
  const user = `Drug: ${drug}\n\nLabel sentences:\n` + lines.join("\n") + `\nQuestion: ${question}`;
  return { user, numbering, sentences };
}

export function retrieve(index, drug, question, sims = null, params = {}, exclude = new Set()) {
  const p = { ...DEFAULTS, ...params };
  const blocks = select(index, scores(index, question, sims, p, exclude), p);
  return { ...render(index.passages, blocks, drug, question), blocks };
}
