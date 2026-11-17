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

/** Replace misheard words with the closest name on the user's list (plan §5 step 1). */
export function correctNames(text: string, meds: Med[]): string {
  const names = [...new Set(meds.flatMap(medNames).filter((n) => !n.includes(" ")))];
  if (!names.length) return text;
  return text.replace(/[A-Za-z][A-Za-z-]{3,}/g, (w) => {
    const lw = w.toLowerCase();
    if (names.includes(lw)) return w;
    let best: string | null = null, bestD = Infinity;
    for (const n of names) {
      const d = editDistance(lw, n);
      const ok = d <= 1 || (lw[0] === n[0] && d <= Math.floor(n.length / 3));
      if (ok && d < bestD) { best = n; bestD = d; }
    }
    return best ?? w;
  });
}
