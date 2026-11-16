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

function splitUnit(unit) {
  const out = [];
  let start = 0;
  for (const m of unit.matchAll(BOUNDARY)) {
    if (isProtected(unit.slice(0, m.index), m[1])) continue;
    const full = m.index + m[0].length;
    const end = full - (m[0].length - m[0].replace(/ +$/, "").length); // end of the closers group
    out.push(pyStrip(unit.slice(start, end)));
    start = full;
  }
  out.push(pyStrip(unit.slice(start)));
  return out;
}

export function splitSentences(text) {
  text = (text || "").replace(SPACES, " ");
  const sentences = [];
  for (const line of text.split("\n")) {
    for (let unit of line.split(BULLETS)) {
      unit = pyStrip(unit.replace(WS, " "));
      if (!unit) continue;
      for (const s of splitUnit(unit)) if (HAS_ALNUM.test(s)) sentences.push(s);
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
