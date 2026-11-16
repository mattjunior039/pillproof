// Port of datapipe/src/medlabel_data/text.py (tokens, numbers, units, drug names and
// the restatement check). Must match Python; see core/tests.

import { PY_WS } from "./pyws.js";

const STOPWORDS = new Set(`
a an the and or but if then than that this these those of to in on at by for from with without
as is are was were be been being it its it's into onto over under about after before during
while not no nor do does did done can could may might must should would will shall
has have had having which who whom whose what when where why how all any both each few more
most other some such only own same so too very s t just also there their they them he she
his her him we our you your i me my one ones per via upon within than vs e g ie eg
`.split(/\s+/).filter(Boolean));

const TOKEN = /[a-z]+|\d+(?:[.,]\d+)*/g;
const NUMBER = /(?<![0-9.,])\d+(?:[.,]\d+)*/g;

export function stem(word) {
  for (const [suf, rep] of [["ies", "y"], ["ing", ""], ["ed", ""], ["es", ""], ["s", ""], ["ly", ""]]) {
    if (word.endsWith(suf) && word.length - suf.length >= 3) {
      word = word.slice(0, -suf.length) + rep;
      break;
    }
  }
  if (word.endsWith("e") && word.length > 4) word = word.slice(0, -1);
  return word;
}

export function normNumber(num) {
  num = /^\d{1,3}(,\d{3})+$/.test(num) ? num.replaceAll(",", "") : num.replaceAll(",", ".");
  if (num.includes(".")) num = num.replace(/0+$/, "").replace(/\.+$/, "");
  const i = num.indexOf(".");
  const whole = i < 0 ? num : num.slice(0, i);
  const rest = i < 0 ? "" : num.slice(i);
  return (whole.replace(/^0+/, "") || "0") + rest;
}

/** Lowercased, stemmed content words and normalized numbers, stopwords removed. */
export function contentTokens(text) {
  const out = [];
  for (const [t] of (text || "").toLowerCase().matchAll(TOKEN)) {
    if (t[0] >= "0" && t[0] <= "9") out.push(normNumber(t));
    else if (!STOPWORDS.has(t) && t.length > 1) out.push(stem(t));
  }
  return out;
}

export function numbers(text) {
  return new Set([...(text || "").toLowerCase().matchAll(NUMBER)].map((m) => normNumber(m[0])));
}

const UNIT_CANON = {
  mg: "mg", milligram: "mg", milligrams: "mg",
  mcg: "mcg", "µg": "mcg", "μg": "mcg", ug: "mcg", microgram: "mcg", micrograms: "mcg",
  g: "g", gram: "g", grams: "g",
  kg: "kg", kilogram: "kg", kilograms: "kg",
  ml: "ml", milliliter: "ml", milliliters: "ml", millilitre: "ml", millilitres: "ml",
  l: "l", liter: "l", liters: "l", dl: "dl",
  meq: "meq", mmol: "mmol", iu: "iu", unit: "unit", units: "unit",
  "%": "%", percent: "%",
  "°c": "°c", "°f": "°f",
  h: "hour", hr: "hour", hrs: "hour", hour: "hour", hours: "hour",
  min: "minute", minute: "minute", minutes: "minute",
  day: "day", days: "day", daily: "day",
  week: "week", weeks: "week", weekly: "week",
  month: "month", months: "month", year: "year", years: "year",
};
const escape = (s) => s.replace(/[.*+?^${}()|[\]\\\-]/g, "\\$&");
// Python sorts by length only (stable), keeping dict order for ties.
const UNIT_ALT = Object.keys(UNIT_CANON).map((u, i) => [u, i])
  .sort((a, b) => b[0].length - a[0].length || a[1] - b[1]).map(([u]) => escape(u)).join("|");
const UNIT_AFTER_NUM = new RegExp(`\\d[${PY_WS}]*-?[${PY_WS}]*(${UNIT_ALT})(?![a-z])`, "gi");
const UNIT_PER = new RegExp(`(?:/[${PY_WS}]*|\\bper[${PY_WS}]+)(${UNIT_ALT})(?![a-z])`, "gi");
const DRUG_SUFFIX = new RegExp(
  "\\b[a-z]{3,}(?:azole|olol|pril|sartan|statin|dipine|mycin|cillin|floxacin|tidine|prazole|" +
  "navir|tinib|mab|parin|oxetine|triptan|semide|thiazide|azepam|azolam|barbital|profen|" +
  "codone|morphone|gliptin|gliflozin|glitazone|lukast|dronate|setron|tadine)\\b", "gi");

export function units(text) {
  const t = text || "";
  const found = [...t.matchAll(UNIT_AFTER_NUM), ...t.matchAll(UNIT_PER)].map((m) => m[1].toLowerCase());
  return new Set(found.map((u) => UNIT_CANON[u] ?? u));
}

const lexCache = new WeakMap();

function lexiconRe(lexicon) {
  if (!lexCache.has(lexicon)) {
    const alt = [...lexicon].sort().sort((a, b) => b.length - a.length).map(escape).join("|");
    lexCache.set(lexicon, new RegExp(`(?<![a-z])(?=(${alt})(?![a-z]))`, "g"));
  }
  return lexCache.get(lexicon);
}

/** Drug names in text: lexicon phrases (lowercase) plus words with common drug-name suffixes. */
export function drugTerms(text, lexicon) {
  const low = (text || "").toLowerCase();
  const found = new Set();
  if (lexicon.size) for (const m of low.matchAll(lexiconRe(lexicon))) found.add(m[1]);
  for (const d of lexicon) if (d.includes(" ") && low.includes(d)) found.add(d);
  for (const m of low.matchAll(DRUG_SUFFIX)) found.add(m[0].toLowerCase());
  return found;
}

const sorted = (set) => [...set].sort();

/** Numbers, units and drug names in the restatement that are absent from the source. */
export function restatementProblems(restatement, source, lexicon) {
  const srcNums = numbers(source);
  const srcUnits = units(source);
  const src = (source || "").toLowerCase();
  return [
    ...sorted(numbers(restatement)).filter((n) => !srcNums.has(n)).map((n) => `number ${n}`),
    ...sorted(units(restatement)).filter((u) => !srcUnits.has(u)).map((u) => `unit ${u}`),
    ...sorted(drugTerms(restatement, lexicon)).filter((d) => !src.includes(d)).map((d) => `drug ${d}`),
  ];
}
