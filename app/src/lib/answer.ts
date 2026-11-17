// Label question → retrieval → model (or passage-only) → checks → what the user sees (plan §5 steps 3-5).
// Pure apart from the injected `generate`, so it runs under node tests too.
import { DESKTOP, PHONE, retrieve, scores } from "../../../core/retrieval.js";
import { checkReply } from "../../../core/checks.js";
import { sectionName } from "./chunk.ts";
import type { LabelMeta } from "./types.ts";

export interface Quote { text: string; section: string }

export type Shown =
  /** Checked restatement plus the quoted label sentences it came from. */
  | { kind: "answer"; restatement: string; quotes: Quote[] }
  /** The model cited sentences but its restatement failed the number/unit/drug check: quotes only. */
  | { kind: "quotes"; quotes: Quote[] }
  /** The model said the retrieved sentences don't answer it. */
  | { kind: "decline" }
  /** No model (or its reply was unusable): the closest label sentences, clearly labelled as such. */
  | { kind: "passages"; quotes: Quote[]; why: "no-model" | "invalid" | "error" };

export interface AnswerResult {
  shown: Shown;
  label: LabelMeta;
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
}

const heading = (index: any, c: number) => sectionName(index.passages[c][0] || "") || "Label";

/** Top label sentences by the same retrieval score, shown in label order. */
export function topSentences(index: any, question: string, sims: number[] | null | undefined, params: any, n = 3): Quote[] {
  const sc: number[] = scores(index, question, (sims ?? null) as any, params);
  const best = sc.map((x, i) => i).filter((i) => sc[i] > 0).sort((a, b) => sc[b] - sc[a] || a - b).slice(0, n).sort((a, b) => a - b);
  return best.map((i) => {
    const [c, s] = index.units[i];
    return { text: index.passages[c][1][s], section: heading(index, c) };
  });
}

export async function answerQuestion(index: any, label: LabelMeta, question: string, o: AnswerOpts): Promise<AnswerResult> {
  const t0 = Date.now();
  const params = o.tier === "phone" ? PHONE : DESKTOP;
  const passages = (why: "no-model" | "invalid" | "error"): Shown => ({ kind: "passages", why, quotes: topSentences(index, question, o.sims, params, o.passageCount ?? 3) });
  if (!o.generate) return { shown: passages("no-model"), label, ms: Date.now() - t0 };

  const r = retrieve(index, label.title, question, (o.sims ?? null) as any, params);
  const where = new Map<number, string>();
  for (const [key, n] of r.numbering as Map<string, number>) where.set(n, heading(index, Number(key.split(",")[0])));
  const raw = await o.generate(r.user);
  const chk = checkReply(raw, r.sentences, label.title, o.lexicon);
  const base = { label, raw, modelKey: o.modelKey };
  const quotes = (): Quote[] => chk.quotes.map(([n, text]: [number, string]) => ({ text, section: where.get(n) || "Label" }));
  let shown: Shown;
  if (chk.status === "decline") shown = { kind: "decline" };
  else if (chk.status === "answer" && chk.quotes.length) {
    shown = chk.blocked ? { kind: "quotes", quotes: quotes() } : { kind: "answer", restatement: chk.restatement!, quotes: quotes() };
  } else shown = passages("invalid");
  return { ...base, shown, ms: Date.now() - t0 };
}

/** Text for speech and for copying. */
export function plainText(res: AnswerResult, advice: boolean, adviceLine: string, standing: string, notCovered: string): string {
  const s = res.shown;
  const parts: string[] = [];
  if (advice) parts.push(adviceLine);
  if (s.kind === "answer") parts.push(s.restatement, "The label says: " + s.quotes.map((q) => q.text).join(" "));
  else if (s.kind === "quotes") parts.push("The label says: " + s.quotes.map((q) => q.text).join(" "));
  else if (s.kind === "decline") parts.push(notCovered);
  else if (s.quotes.length) parts.push("The closest sentences in the label: " + s.quotes.map((q) => q.text).join(" "));
  else parts.push(notCovered);
  parts.push(standing);
  return parts.join(" ");
}
