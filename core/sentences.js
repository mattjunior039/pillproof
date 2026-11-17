// Port of datapipe/src/medlabel_data/sentences.py and fdarx/align.py:split_passage.
// Sentence numbers in prompts depend on this, so it must match Python exactly;
// core/tests checks both the golden cases and a Python-generated sample of real labels.

import { PY_WS, pyRstrip, pyStrip } from "./pyws.js";

export const ABBREVIATIONS = new Set([
  "e.g", "i.e", "vs", "approx", "dr", "mr", "mrs", "ms", "no", "nos", "fig", "figs",
  "inc", "ltd", "co", "corp", "st", "jr", "sr", "ca", "cf", "al", "min", "max",
  "hr", "hrs", "resp", "incl", "ref", "refs", "vol", "pp", "sec", "eq",
  "mfd", "dist", "tab", "tabs", "cap", "caps", "oz", "fl", "wt",
]);

const SPACES = /[\u00a0\u2000-\u200b\u202f\u205f\u3000\t\r\f\v]/g;
const BULLETS = new RegExp(`[${PY_WS}]*[•●▪◦][${PY_WS}]*`);
const WS = / +/g;
const BOUNDARY = / ?([.!?])(["'”’)\]]*) +(?=[A-Z0-9"'“‘(\[\-–])/g;
const BOUNDARY_OTC = / ?([.!?])(["'”’)\]]*) +(?=[A-Za-z0-9"'“‘(\[\-–])/g;
// OTC Drug Facts mode (openFDA flattens list items onto one line); see sentences.py rules 7-8.
const OTC_OPENERS =
  "do not (?:take|exceed|use|give)|children under|adults and children|ask a doctor|stop use" +
  "|if pregnant|keep out of reach|store at|avoid excessive heat|read all" +
  "|each (?:tablet|capsule|caplet|softgel|pack|packet) contains|you (?:have|are taking)" +
  "|have (?:[0-9]|had|bloody|stomach pain)|[0-9]+ or more alcoholic|ringing in the ears|take (?:a blood|other drugs|more or)|are age [0-9]|feel faint" +
  "|vomit blood|pain gets worse|fever gets worse|redness or swelling|any new symptoms";
const OTC_ITEM = new RegExp(
  " (?=[A-Z][A-Za-z’'-]*(?: [A-Za-z’'()-]+){0,4} ?:(?= )" +
  "|(?:If|When|Do|Ask|Stop|Keep|Store|Take|Use|Read|Children|Adults|Other|Each)(?![A-Za-z0-9_])" +
  "|(?:" + OTC_OPENERS + ")(?![A-Za-z0-9_]))", "g");
const NO_CUT_AFTER = new Set([
  "if", "when", "and", "or", "that", "who", "unless", "because", "whether", "while", "you",
  "to", "not", "the", "a", "an", "of", "with", "than", "may", "can", "should", "do", "does",
  "have", "has", "had", "are", "is", "be", "take", "taking",
]);
const LAST_WORD = /([A-Za-z]+)$/;
const WORD_BEFORE = /([A-Za-z0-9.]+)$/;
const HAS_ALNUM = /[A-Za-z0-9]/;

function isProtected(prefix, punct) {
  if (punct !== ".") return false;
  const m = WORD_BEFORE.exec(prefix);
  if (!m) return false;
  const word = m[1].replace(/\.+$/, "").toLowerCase();
  if (ABBREVIATIONS.has(word)) return true;
  const before = pyRstrip(prefix.slice(0, prefix.length - m[1].length));
  const last = word.split(".").pop();
  if (last.length === 1 && /[a-z]/.test(last) && !before.endsWith("°")) return true;
  if (/^[0-9]{1,2}$/.test(word) && (!before || "(:;.".includes(before[before.length - 1]))) return true;
  return false;
}

function otcItems(unit) {
  const out = [];
  let start = 0;
  for (const m of unit.matchAll(OTC_ITEM)) {
    const i = m.index;
    const rest = unit.slice(i + 1);
    const lower = /^[a-z0-9]/.test(rest);
    if (i === 0) continue;
    if (unit[i - 1] === ":") {
      if (!lower || unit.slice(start, i).split(/[.!?] /).pop().split(" ").length <= 6) continue;
    } else if (!/[A-Za-z0-9)\]]/.test(unit[i - 1])) continue;
    const w = LAST_WORD.exec(unit.slice(0, i));
    const prev = w ? w[1].toLowerCase() : "";
    if (lower && NO_CUT_AFTER.has(prev) && !(prev === "you" && rest.startsWith("you "))) continue;
    out.push(unit.slice(start, i));
    start = i + 1;
  }
  out.push(unit.slice(start));
  return out;
}

function splitUnit(unit, otc = false) {
  const out = [];
  let start = 0;
  for (const m of unit.matchAll(otc ? BOUNDARY_OTC : BOUNDARY)) {
    if (isProtected(unit.slice(0, m.index), m[1])) continue;
    const full = m.index + m[0].length;
    const end = full - (m[0].length - m[0].replace(/ +$/, "").length); // end of the closers group
    out.push(pyStrip(unit.slice(start, end)));
    start = full;
  }
  out.push(pyStrip(unit.slice(start)));
  return out;
}

/** `otc`: openFDA Drug Facts text, whose list items arrive run together (off for Rx labels). */
export function splitSentences(text, otc = false) {
  text = (text || "").replace(SPACES, " ");
  const sentences = [];
  for (const line of text.split("\n")) {
    for (let unit of line.split(BULLETS)) {
      unit = pyStrip(unit.replace(WS, " "));
      if (!unit) continue;
      for (const item of otc ? otcItems(unit) : [unit]) {
        for (const s of splitUnit(pyStrip(item), otc)) if (HAS_ALNUM.test(s)) sentences.push(s);
      }
    }
  }
  return sentences;
}

const NORM_WS = new RegExp(`[${PY_WS}]+`, "g");
export const normWs = (text) => pyStrip((text || "").replaceAll("\u00a0", " ").replace(NORM_WS, " "));

const HEADING = new RegExp(`^([0-9]+(\\.[0-9]+)*\\.?[${PY_WS}]+)?[A-Za-z][^.:;]{0,100}$`);

/** [heading, sentences] for one label chunk; heading is "" when the first line is ordinary text. */
export function splitPassage(chunk) {
  const lines = pyStrip(chunk).split("\n");
  const head = normWs(lines[0]);
  if (lines.length > 1 && HEADING.test(head) && head.split(" ").length <= 12) {
    return [head, splitSentences(lines.slice(1).join("\n"))];
  }
  return ["", splitSentences(chunk)];
}
