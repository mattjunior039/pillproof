// openFDA label record -> passages [heading, sentences] shaped like FDARxBench chunks
// ("5.1 Myopathy and Rhabdomyolysis" + body), the format retrieval and the fine-tune expect.
import { splitSentences } from "../../../core/sentences.js";
import type { Passage } from "./types.ts";

type Rec = Record<string, unknown> & { openfda?: Record<string, string[]> };

// Reading order; child fields (pregnancy, mechanism_of_action...) are dropped when their text is
// already inside a parent field.
const FIELDS: [string, string][] = [
  ["boxed_warning", "Boxed Warning"],
  ["purpose", "Purpose"],
  ["active_ingredient", "Active Ingredient"],
  ["indications_and_usage", "Indications and Usage"],
  ["dosage_and_administration", "Dosage and Administration"],
  ["dosage_forms_and_strengths", "Dosage Forms and Strengths"],
  ["contraindications", "Contraindications"],
  ["warnings_and_cautions", "Warnings and Precautions"],
  ["warnings", "Warnings"],
  ["do_not_use", "Do Not Use"],
  ["ask_doctor", "Ask a Doctor"],
  ["ask_doctor_or_pharmacist", "Ask a Doctor or Pharmacist"],
  ["when_using", "When Using This Product"],
  ["stop_use", "Stop Use"],
  ["pregnancy_or_breast_feeding", "Pregnancy or Breast-Feeding"],
  ["keep_out_of_reach_of_children", "Keep Out of Reach of Children"],
  ["precautions", "Precautions"],
  ["general_precautions", "General Precautions"],
  ["adverse_reactions", "Adverse Reactions"],
  ["drug_interactions", "Drug Interactions"],
  ["use_in_specific_populations", "Use in Specific Populations"],
  ["pregnancy", "Pregnancy"],
  ["nursing_mothers", "Nursing Mothers"],
  ["lactation", "Lactation"],
  ["pediatric_use", "Pediatric Use"],
  ["geriatric_use", "Geriatric Use"],
  ["drug_abuse_and_dependence", "Drug Abuse and Dependence"],
  ["overdosage", "Overdosage"],
  ["description", "Description"],
  ["clinical_pharmacology", "Clinical Pharmacology"],
  ["mechanism_of_action", "Mechanism of Action"],
  ["pharmacodynamics", "Pharmacodynamics"],
  ["pharmacokinetics", "Pharmacokinetics"],
  ["how_supplied", "How Supplied"],
  ["storage_and_handling", "Storage and Handling"],
  ["inactive_ingredient", "Inactive Ingredients"],
  ["information_for_patients", "Patient Counseling Information"],
  ["spl_patient_package_insert", "Patient Information"],
  ["spl_medguide", "Medication Guide"],
  ["spl_unclassified_section", "Patient Information"],
  ["questions", "Questions"],
];
const PATIENT_FIELDS = new Set(["spl_patient_package_insert", "spl_medguide", "spl_unclassified_section"]);
const PATIENT_START = /^\s*(PATIENT INFORMATION|MEDICATION GUIDE|INSTRUCTIONS FOR USE|PATIENT PACKAGE INSERT|Patient Information|Medication Guide)\b/;

const CONNECTORS = new Set(["and", "of", "the", "in", "with", "for", "to", "or", "on", "by", "a", "an", "at", "from", "during", "after", "before", "&", "/", "-", "vs"]);
const PIECE = 600;
const LONG = 700;
const UPPER_MAX = 12;
const MAX_HEAD_WORDS = 20;
const UNITS = new Set(["mg", "mcg", "ml", "g", "kg", "mg/kg", "mg/day", "years", "year"]);

const clean = (s: string) => s.replace(/\s+/g, " ").trim();
const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

export function isPatientText(field: string, text: string): boolean {
  return field !== "spl_unclassified_section" || PATIENT_START.test(text);
}

/** True for the patient-facing parts of a label (plan §3 item 8 prefers labels that have one). */
export function hasPatientSection(rec: Rec): boolean {
  return [...PATIENT_FIELDS].some((f) => {
    const v = rec[f];
    return Array.isArray(v) && v.some((t) => isPatientText(f, String(t)));
  });
}

/** Lowercase drug-name words; a heading never runs into them. */
function drugWords(rec: Rec): Set<string> {
  const o = rec.openfda || {};
  const names = [...(o.brand_name || []), ...(o.generic_name || []), ...(o.substance_name || [])];
  return new Set(names.flatMap((n) => norm(n).split(" ")).filter((w) => w.length >= 4));
}

const isCap = (w: string) => /^[A-Z(]/.test(w) && /[A-Za-z]/.test(w);
const bare = (w: string) => w.replace(/[^A-Za-z0-9&/-]/g, "").toLowerCase();

/**
 * Split "Myopathy and Rhabdomyolysis Atorvastatin calcium may ..." into a title and body.
 * The title is a run of Capitalized words and connectors; the last capitalized word is
 * dropped when a lowercase word follows, since it starts the first sentence.
 */
export function splitTitle(text: string, drugs: Set<string>): [string, string] {
  const toks = text.split(" ");
  let i = 0;
  let stoppedByLower = false;
  let leadingDrug = true;
  while (i < toks.length && i < MAX_HEAD_WORDS) {
    const t = toks[i];
    const b = bare(t);
    const isDrug = drugs.has(b) || drugs.has(b.replace(/s$/, ""));
    leadingDrug &&= isDrug;
    // A drug name ends the title unless the title starts with it or a connector leads into it.
    if (isDrug && !leadingDrug && !CONNECTORS.has(bare(toks[i - 1] || ""))) {
      stoppedByLower = !isCap(t);
      break;
    }
    if (isCap(t) || /^\(?[A-Z0-9]{2,}\)?[,:]?$/.test(t) || /^\d+(\.\d+)*$/.test(t) || UNITS.has(b) || CONNECTORS.has(b)) {
      i++;
      if (/[:.]$/.test(t)) break;
      continue;
    }
    stoppedByLower = true;
    break;
  }
  if (stoppedByLower) {
    let j = i - 1;
    while (j >= 0 && !isCap(toks[j])) j--; // back over trailing connectors to the sentence's first word
    if (j >= 2) i = j; // keep at least two title words ("Drug Interactions that may...")
  }
  // "Increases in HbA1c ... Levels Increases in HbA1c and fasting": the body repeats the title's first word.
  const first = bare(toks[0]);
  for (let k = 2; k < i; k++) if (bare(toks[k]) === first) { i = k; break; }
  while (i > 0 && CONNECTORS.has(bare(toks[i - 1]))) i--;
  if (i === toks.length || i >= MAX_HEAD_WORDS) return ["", text];
  const title = toks.slice(0, i).join(" ").replace(/[:,]$/, "");
  return [title, toks.slice(i).join(" ")];
}

/** Split "5 WARNINGS AND PRECAUTIONS rest" -> ["5 WARNINGS AND PRECAUTIONS", "rest"]. */
function splitUpperHeading(text: string, drugs: Set<string>): [string, string, string | null] {
  const m = /^(\d{1,2})?\s*/.exec(text)!;
  const num = m[1] ?? null;
  const toks = text.slice(m[0].length).split(" ");
  let i = 0;
  while (i < toks.length && i < UPPER_MAX) {
    const t = toks[i];
    const letters = t.replace(/[^A-Za-z]/g, "");
    if (drugs.has(bare(t)) && i > 0) break;
    if (!(letters.length >= 1 && letters === letters.toUpperCase() && !/^\d/.test(t)) && t !== "&" && t !== "/") break;
    if (letters.length === 1 && i > 0 && !["A", "&"].includes(t)) break;
    i++;
    if (/:$/.test(t)) break;
  }
  if (i === 0 || i >= UPPER_MAX) return ["", text, num];
  return [[num, ...toks.slice(0, i)].filter(Boolean).join(" ").replace(/:$/, ""), toks.slice(i).join(" "), num];
}

/** Flattened tables come out as one huge "sentence"; cut them at word boundaries. */
function capSentence(s: string): string[] {
  if (s.length <= LONG) return [s];
  const out: string[] = [];
  let rest = s;
  while (rest.length > LONG) {
    let cut = rest.lastIndexOf(" ", 500);
    if (cut < 200) cut = 500;
    out.push(rest.slice(0, cut).trim());
    rest = rest.slice(cut).trim();
  }
  if (rest) out.push(rest);
  return out;
}

/** Break a body into ~PIECE-char groups of whole sentences that share a heading. */
function pieces(heading: string, body: string, otc = false): Passage[] {
  const sents = splitSentences(body, otc).flatMap(capSentence);
  if (!sents.length) return [];
  const out: Passage[] = [];
  let cur: string[] = [], len = 0;
  for (const s of sents) {
    if (cur.length && len + s.length > PIECE) { out.push([heading, cur]); cur = []; len = 0; }
    cur.push(s);
    len += s.length + 1;
  }
  if (cur.length) out.push([heading, cur]);
  return out;
}

/** Numbered subsections: "5.1 Title ..." at the start or after a sentence end, matching the section number. */
function splitNumbered(text: string, num: string | null): { head: string; body: string }[] {
  if (!num) return [{ head: "", body: text }];
  const re = new RegExp(`(^|[.:!?)\\]] )(${num}\\.\\d{1,2}) (?=[A-Z])`, "g");
  const cuts: number[] = [];
  for (const m of text.matchAll(re)) cuts.push(m.index! + m[1].length);
  if (!cuts.length) return [{ head: "", body: text }];
  const out = [{ head: "", body: text.slice(0, cuts[0]) }];
  cuts.forEach((c, k) => out.push({ head: "#", body: text.slice(c, cuts[k + 1] ?? text.length) }));
  return out.filter((x) => x.body.trim());
}

const QUESTION = /(?:^|(?<= ))((?:What|How|Who|Can|Should|Do|Does|Is|Are|When|Where|Why)\b[^?.!]{3,150}\?|General information about the safe and effective use of [^.]{1,80}\.)/g;

function splitPatient(text: string, title: string, otc: boolean): Passage[] {
  const cuts = [...text.matchAll(QUESTION)].map((m) => ({ at: m.index!, q: m[1] }));
  const out: Passage[] = [];
  const first = cuts.length ? text.slice(0, cuts[0].at) : text;
  out.push(...pieces(title, first, otc));
  cuts.forEach((c, k) => {
    const body = text.slice(c.at + c.q.length, cuts[k + 1]?.at ?? text.length);
    out.push(...pieces(c.q.replace(/\.$/, ""), body, otc));
  });
  return out;
}

/** Bump when chunking changes so cached labels are re-fetched and re-split. 3: table rows as sentences. */
export const CHUNKER = 3;

/**
 * Tables whose rows are turned into sentences. The plain-text fields flatten tables into one
 * run-on block (doses split from the row they belong to); a row sentence keeps them together:
 * "For CABP: Loading Doses: NUZYRA Tablets: Day 1: 300 mg orally twice; Maintenance Dose: …".
 * App only: the FDARxBench/T1 passages and the Python splitter are untouched.
 */
const TABLES: [string, string][] = [
  ["dosage_and_administration_table", "Dosage and Administration"],
  ["dosage_forms_and_strengths_table", "Dosage Forms and Strengths"],
  ["drug_interactions_table", "Drug Interactions"],
  ["use_in_specific_populations_table", "Use in Specific Populations"],
];

const ENTITIES: Record<string, string> = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " ", ge: "≥", le: "≤", micro: "µ", mu: "µ", deg: "°", plusmn: "±", times: "×", ndash: "–", mdash: "—" };
const decode = (t: string) => t.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e: string) =>
  e[0] === "#" ? String.fromCodePoint(e[1].toLowerCase() === "x" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10)) : ENTITIES[e.toLowerCase()] ?? m);
/** Cell HTML -> text: inline tags become spaces (SPL runs words into tags), cross-references go. */
const cellText = (h: string) => clean(decode(h.replace(/<[^>]*>/g, " ")))
  .replace(/\(\s*(?:\d+(?:\.\d+)*\s*,?\s*)+\)/g, "").replace(/\s+([,.;:)])/g, "$1").replace(/\(\s+/g, "(").replace(/\s+/g, " ").trim();
const cells = (row: string) => [...row.matchAll(/<(t[hd])\b[^>]*>([\s\S]*?)<\/\1>/gi)].map((m) => ({ th: m[1].toLowerCase() === "th", text: cellText(m[2]) }));

/** One sentence per table row: "For <row header>: <column>: <cell>; …" (regex parsing; tests run without a DOM). */
export function tableSentences(html: string): { caption: string; rows: string[] } {
  const caption = cellText(/<caption\b[^>]*>([\s\S]*?)<\/caption>/i.exec(html)?.[1] ?? "");
  const thead = /<thead\b[^>]*>([\s\S]*?)<\/thead>/i.exec(html)?.[1];
  let rows = [...html.replace(/<thead\b[\s\S]*?<\/thead>/i, "").matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)].map((m) => cells(m[1]));
  let head: string[] = [];
  if (thead) {
    const hr = [...thead.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)].map((m) => cells(m[1]).map((c) => c.text));
    head = hr[hr.length - 1] || [];
  } else if (rows[0]?.length > 1 && rows[0].every((c) => c.th)) {
    head = rows[0].map((c) => c.text);
    rows = rows.slice(1);
  }
  const out: string[] = [];
  let group = "";
  for (const r of rows) {
    const full = r.filter((c) => c.text);
    if (!full.length) continue;
    // A row with one filled cell is a group label ("Adults", "Pediatric Patients").
    if (full.length === 1 && r.length > 1) { group = full[0].text.replace(/:$/, ""); continue; }
    const [first, ...rest] = r.map((c) => c.text);
    const parts = rest.map((t, k) => (t ? (head[k + 1] ? `${head[k + 1].replace(/:$/, "")}: ${t}` : t) : "")).filter(Boolean);
    if (!parts.length) continue;
    const who = [group, first].filter(Boolean).join(", ");
    let line = `${who ? `For ${who}` : head[0] || "Row"}: ${parts.join("; ")}`;
    if (!/[.!?]$/.test(line)) line += ".";
    out.push(line);
  }
  return { caption, rows: out };
}

function tablePassages(rec: Rec): Passage[] {
  const out: Passage[] = [];
  const seen = new Set<string>();
  for (const [field, name] of TABLES) {
    const vals = rec[field];
    if (!Array.isArray(vals)) continue;
    for (const html of vals) {
      const { caption, rows } = tableSentences(String(html));
      const fresh = rows.filter((r) => !seen.has(r) && (seen.add(r), true)).flatMap(capSentence);
      if (!fresh.length) continue;
      const head = `${name} table${caption ? `: ${caption.replace(/[.:]$/, "")}` : ""}`;
      for (let i = 0; i < fresh.length; i += 4) out.push([head, fresh.slice(i, i + 4)]);
    }
  }
  return out;
}

/** OTC Drug Facts labels arrive from openFDA with their list items run together. */
export const isOtc = (rec: Rec) => (rec.openfda?.product_type || []).some((t: string) => /OTC/i.test(t));

export function chunkLabel(rec: Rec): Passage[] {
  const drugs = drugWords(rec);
  const otc = isOtc(rec);
  const seen: string[] = [];
  const out: Passage[] = [];
  for (const [field, name] of FIELDS) {
    const vals = rec[field];
    if (!Array.isArray(vals)) continue;
    for (const raw of vals) {
      const text = clean(String(raw));
      if (!text || !isPatientText(field, text)) continue;
      const probe = norm(text).slice(0, 300);
      if (seen.some((s) => s.includes(probe))) continue;
      seen.push(norm(text));
      if (PATIENT_FIELDS.has(field)) {
        const [h, body] = splitUpperHeading(text, drugs);
        out.push(...splitPatient(body, h ? titleCase(h) : name, otc));
        continue;
      }
      const [intro, rest, num] = splitUpperHeading(text, drugs);
      const sectionHead = intro || name;
      for (const part of splitNumbered(rest, num)) {
        if (part.head === "#") {
          const sub = /^(\d{1,2}\.\d{1,2}) (.*)$/s.exec(part.body)!;
          const [title, body] = splitTitle(sub[2], drugs);
          out.push(...pieces(title ? `${sub[1]} ${title}` : sub[1], body, otc));
        } else {
          out.push(...pieces(sectionHead, part.body, otc));
        }
      }
    }
  }
  return [...out, ...tablePassages(rec)];
}

export function titleCase(s: string): string {
  return s.toLowerCase().replace(/\b([a-z])([a-z]*)/g, (w, a, b) => (CONNECTORS.has(w) ? w : a.toUpperCase() + b)).replace(/^./, (c) => c.toUpperCase());
}

/** Readable section name for display: "5 WARNINGS AND PRECAUTIONS" -> "Warnings and Precautions". */
export function sectionName(heading: string): string {
  const h = heading.replace(/^\d{1,2}(\.\d{1,2})?\s+/, "");
  return h === h.toUpperCase() ? titleCase(h) : h;
}
