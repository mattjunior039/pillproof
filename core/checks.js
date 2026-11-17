// Quote and number checks on a model reply: port of datapipe/src/medlabel_data/checks.py.
// Both run core/fixtures/check_cases.json (see core/tests and datapipe/tests).

import { PY_WS, pyStrip } from "./pyws.js";
import { restatementProblems } from "./text.js";

export const DECLINE = "NOT IN LABEL";

const W = `[${PY_WS}]`;
const THINK = /<think>[\s\S]*?<\/think>/g;
const STRICT = /^SENTENCES: \d+(, \d+)*\nANSWER: [^\n]+$/;
const SENT_LINE = new RegExp(`^\\**${W}*SENTENCES?${W}*\\**${W}*:${W}*\\**${W}*(.*)$`, "i");
const ANS_LINE = new RegExp(`^\\**${W}*ANSWER${W}*\\**${W}*:${W}*\\**${W}*(.*)$`, "i");
// Separators are required so a long, cut-off list cannot backtrack exponentially (see checks.py).
const NUM_LIST = new RegExp(`^\\d+(?:${W}*[,;]${W}*\\d+|${W}+\\d+)*${W}*\\.?$`);
const NUMBERED = /^\[(\d+)\] ([^\n]*)$/gm;
const DECL_HEAD = new RegExp(`^[${PY_WS}*"']+`);
const DECL_TAIL = new RegExp(`[${PY_WS}.!*"']+$`);

// Qualifier check (see checks.py step 5). Letter lookarounds instead of \b so JS and Python agree.
const S = `${W}+`;
const q = (alts) => new RegExp(`(?<![A-Za-z])(?:${alts})(?![A-Za-z])`, "i");
const WARN = q(
  `avoid|do${S}not|don['’]t|should${S}not|shouldn['’]t|must${S}not|not${S}more${S}than|no${S}more${S}than` +
  `|more${S}than|limit|unless|except|only${S}if|stop|contraindicated|not${S}recommended|never`);
const KEEP = q(
  "avoid[A-Za-z]*|not|no|never|don['’]t|doesn['’]t|shouldn['’]t|mustn['’]t|can['’]t|cannot|isn['’]t|aren['’]t" +
  `|limit[A-Za-z]*|unless|except|only|stop[A-Za-z]*|contraindicated|without|max|maximum|up${S}to|at${S}most|less${S}than` +
  `|fewer${S}than|exceed[A-Za-z]*|discontinue[A-Za-z]*|caution[A-Za-z]*|careful[A-Za-z]*`);
const YES = new RegExp(`^[${PY_WS}"'*]*(?:yes|it${S}is${S}(?:generally${S})?safe|it['’]s${S}(?:generally${S})?safe)(?![A-Za-z])`, "i");
const FIRST = /^[^.!?;]*/;
const keeps = (t) => KEEP.test(t) || WARN.test(t);

/** ["qualifier <word>"] if the answer drops the cited warning; ["unqualified yes"] if it opens with one. */
export function qualifierProblems(answer, cited) {
  const w = WARN.exec(cited);
  if (!w || !answer) return [];
  const out = [];
  if (!keeps(answer)) out.push("qualifier " + w[0].toLowerCase().replace(new RegExp(S, "g"), " "));
  if (YES.test(answer) && !keeps(FIRST.exec(answer)[0])) out.push("unqualified yes");
  return out;
}

/** The `[n] sentence` lines of a rendered prompt, as {n: sentence}. */
export function numberedSentences(prompt) {
  const out = {};
  for (const m of prompt.matchAll(NUMBERED)) out[Number(m[1])] = m[2];
  return out;
}

const normDecline = (line) => line.replace(DECL_HEAD, "").replace(DECL_TAIL, "").toUpperCase();

export function parseReply(text) {
  const raw = pyStrip((text || "").replace(THINK, ""));
  const out = { kind: "invalid", sentences: [], answer: "", strict: false, error: "" };
  const lines = raw.split("\n").map(pyStrip).filter(Boolean);
  if (raw.includes("<think>")) return { ...out, error: "unfinished think block" };
  if (!lines.length) return { ...out, error: "empty reply" };
  const idx = lines.findIndex((ln) => SENT_LINE.test(ln));
  const first = normDecline(lines[0]);
  if (first === DECLINE || (idx < 0 && first.startsWith(DECLINE))) {
    return { ...out, kind: "decline", strict: raw === DECLINE };
  }
  if (idx < 0) return { ...out, error: "no SENTENCES line" };
  const rest = pyStrip(SENT_LINE.exec(lines[idx])[1].replace(/[[\]*]/g, "").replace(/\band\b/g, " "));
  if (!NUM_LIST.test(rest)) return { ...out, error: "SENTENCES line is not a list of numbers" };
  const nums = [...new Set(rest.match(/\d+/g).map(Number))].sort((a, b) => a - b);
  let answer = "";
  for (let j = idx + 1; j < lines.length; j++) {
    const m = ANS_LINE.exec(lines[j]);
    if (m) {
      answer = pyStrip([pyStrip(m[1]), ...lines.slice(j + 1)].join(" "));
      break;
    }
  }
  return { ...out, kind: "answer", sentences: nums, answer, strict: STRICT.test(raw) };
}

/**
 * Parse, verify numbers, copy quotes and run the number and qualifier checks.
 * `sentences` maps prompt numbers to sentence text ({n: text} or a Map).
 * Returns the parse fields plus status ("decline" | "answer" | "invalid"), quotes
 * ([[n, sentence], ...]), problems, blocked and restatement (null when blocked or missing).
 */
export function checkReply(text, sentences, drug, lexicon) {
  const get = sentences instanceof Map ? (n) => sentences.get(n) : (n) => sentences[n];
  const p = parseReply(text);
  const res = { ...p, status: p.kind, quotes: [], problems: [], blocked: false, restatement: null };
  if (p.kind !== "answer") return res;
  const missing = p.sentences.filter((n) => get(n) === undefined);
  if (missing.length) {
    return { ...res, status: "invalid", error: `cites sentence ${missing[0]}, which is not in the prompt` };
  }
  res.quotes = p.sentences.map((n) => [n, get(n)]);
  const source = drug + "\n" + res.quotes.map(([, s]) => s).join("\n");
  res.problems = [
    ...restatementProblems(p.answer, source, lexicon),
    ...qualifierProblems(p.answer, res.quotes.map(([, s]) => s).join("\n")),
  ];
  res.blocked = res.problems.length > 0 || !p.answer;
  res.restatement = res.blocked ? null : p.answer;
  return res;
}
