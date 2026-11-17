// Matching medicine names in typed or heard text against the user's own list.
import type { Med } from "./types.ts";

export function editDistance(a: string, b: string): number {
  if (a === b) return 0;
  const m = a.length, n = b.length;
  let prev = Array.from({ length: n + 1 }, (_, j) => j);
  for (let i = 1; i <= m; i++) {
    const cur = [i];
    for (let j = 1; j <= n; j++) {
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    }
    prev = cur;
  }
  return prev[n];
}

/** Allowed typos for a name of this length: none for short names. */
const slack = (len: number) => (len >= 9 ? 2 : len >= 5 ? 1 : 0);

export const words = (text: string) => text.toLowerCase().match(/[a-z][a-z0-9-]*/g) || [];

/** Lowercase names a medicine can be called by: ingredient words, brand, label brand names. */
export function medNames(med: Med): string[] {
  const out = new Set<string>();
  const add = (s?: string) => {
    if (!s) return;
    const w = s.toLowerCase().replace(/[^a-z0-9 -]/g, " ").replace(/\s+/g, " ").trim();
    if (w.length >= 3) out.add(w);
  };
  for (const part of med.ingredient.split(/\s*\/\s*|\s+and\s+/)) {
    add(part);
    add(part.split(" ")[0]);
  }
  add(med.brand);
  for (const b of med.label?.brandNames || []) add(b);
  return [...out];
}

/** True when `name` (one or more words) occurs in `toks`, allowing small typos. */
export function containsName(toks: string[], name: string): boolean {
  const parts = name.split(" ");
  for (let i = 0; i + parts.length <= toks.length; i++) {
    if (parts.every((p, j) => editDistance(toks[i + j], p) <= slack(p.length))) return true;
  }
  return false;
}

export function medsMentioned(text: string, meds: Med[]): Med[] {
  const toks = words(text);
  return meds.filter((m) => medNames(m).some((n) => containsName(toks, n)));
}

/** Drug names from the lexicon that appear in the text (exact words only). */
export function lexiconMentions(text: string, lexicon: Set<string>): string[] {
  return [...new Set(words(text).filter((w) => w.length >= 4 && lexicon.has(w)))];
}

/** Rough sound-alike key: speech recognisers spell drug names by sound ("lip it or", "met for men"). */
export const soundKey = (s: string) =>
  s.toLowerCase().replace(/[^a-z]/g, "").replace(/ph/g, "f").replace(/v/g, "f").replace(/c(?=[eiy])/g, "s")
    .replace(/[ckq]/g, "k").replace(/z/g, "s").replace(/[aeiouy]+/g, "a").replace(/(.)\1+/g, "$1");

/** Replace misheard words, or runs of up to 4 words, with the closest name on the user's list (plan §5 step 1). */
export function correctNames(text: string, meds: Med[]): string {
  const names = [...new Set(meds.flatMap(medNames).filter((n) => !n.includes(" ")))];
  if (!names.length) return text;
  const toks = [...text.matchAll(/[A-Za-z][A-Za-z'-]*/g)].map((m) => ({ w: m[0], at: m.index!, end: m.index! + m[0].length }));
  const cands: { from: number; to: number; name: string; d: number; k: number }[] = [];
  for (let i = 0; i < toks.length; i++) {
    for (let k = 1; k <= 4 && i + k <= toks.length; k++) {
      const span = toks.slice(i, i + k).map((t) => t.w).join("").toLowerCase();
      for (const n of names) {
        if (span === n) { cands.push({ from: i, to: i + k, name: n, d: k === 1 ? -1 : 0, k }); continue; }
        let d = Infinity;
        if (k === 1 && span.length >= 4) {
          const e = editDistance(span, n);
          if (e <= 1 || (span[0] === n[0] && e <= Math.floor(n.length / 3))) d = e;
        }
        const a = soundKey(span), b = soundKey(n);
        if (a.length >= b.length * 0.7 && a.length <= b.length * 1.4) {
          const e = editDistance(a, b);
          if (e <= Math.floor(b.length / 4)) d = Math.min(d, e);
        }
        if (d < Infinity) cands.push({ from: i, to: i + k, name: n, d, k });
      }
    }
  }
  cands.sort((x, y) => x.d - y.d || x.k - y.k);
  const used = new Array(toks.length).fill(false);
  const picked: typeof cands = [];
  for (const c of cands) {
    if (used.slice(c.from, c.to).some(Boolean)) continue;
    for (let i = c.from; i < c.to; i++) used[i] = true;
    picked.push(c);
  }
  picked.sort((x, y) => y.from - x.from);
  let out = text;
  for (const c of picked) {
    if (c.d === -1) continue;
    out = out.slice(0, toks[c.from].at) + c.name + out.slice(toks[c.to - 1].end);
  }
  return out;
}
