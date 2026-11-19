// Backup sources (docs/app.md, "Backup sources"): when the user's own label does not answer a
// question, check other sources one at a time and stop at the first that answers:
//   2. other FDA labels with exactly the same active ingredient(s),
//   3. FDA consumer pages (app/data/fda_food.json),
//   4. DDInter 2.0 drug-food rows (app/data/ddinter_food.json, CC BY-NC-SA 4.0),
//   5. a web search (web.ts; any site, consumer health sites first, always marked "may be wrong"),
//   6. otherwise "None of the sources we checked …" and a MedlinePlus link (link only).
// Each source goes through the same relevance gate, model and checks as the label (answer.ts).
// Not used by the frozen evaluation (T1-T5, systems A-E), which stays label-only.
import { LabelIndex } from "../../../core/retrieval.js";
import { answerQuestion, coverage, listWords, notMentioned, type AnswerOpts, type AnswerResult } from "./answer.ts";
import { titleCase } from "./chunk.ts";
import { concepts } from "./query.ts";
import { dailyMedUrl, labelDate, toStored } from "./openfda.ts";
import { ingredientList } from "./rxnorm.ts";
import type { LabelMeta, Med, Passage } from "./types.ts";
import { aboutDrug, IMPLIES_SAFE, pagePassages, rankResults, WEB_SKIP, type Site, type WebResponse } from "./web.ts";

export interface FdaPage {
  id: string; title: string; url: string; publisher: string; content_date: string; accessed: string;
  groups: { ingredients: string[]; passages: Passage[] }[];
}
export interface FdaFile { pages: FdaPage[] }
export interface DdinterRow { id: number; drug: string; food: string; level: string; ddinter_id: string; sentences: string[] }
export interface DdinterFile { source: string; url: string; detail_url: string; license: string; license_url: string; accessed: string; rows: DdinterRow[] }

export interface Source {
  kind: "label" | "fda-page" | "ddinter" | "web";
  /** Badge text, e.g. "Not on your label — from the FDA label for Lipitor (Pfizer), dated Mar 3, 2025". */
  badge: string;
  url: string;
  /** Licence/attribution line, when the source needs one. */
  credit?: { text: string; url: string };
  /** Web answers: the site, shown in large text; "other" sites get an "Unverified website" warning. */
  site?: Site;
}

export interface BackupOutcome {
  hit?: { source: Source; result: AnswerResult };
  /** Sources checked without an answer, in order, e.g. "2 other FDA labels for atorvastatin". */
  checked: string[];
  /** What the question was about, for "None of the sources we checked mention …". */
  topic: string[];
  medline: { title: string; url: string };
}

export interface BackupDeps {
  fda: () => Promise<FdaFile>;
  ddinter: () => Promise<DdinterFile>;
  /** openFDA records for the same ingredients (excluding the user's label); throws offline. */
  otherLabels: () => Promise<any[]>;
  medline: () => Promise<{ title: string; url: string }>;
  /** Web search through our proxy (only ingredients and question are sent); throws Error(reason). */
  web?: (ingredients: string[], question: string) => Promise<WebResponse>;
}

/** The user's label gave no usable answer. */
export function unanswered(r: AnswerResult): boolean {
  const s = r.shown;
  return s.kind === "not-found" || s.kind === "decline" || (s.kind === "passages" && !s.quotes.length);
}

const answered = (r: AnswerResult) => !unanswered(r);
/** Sentences shown without a model answer: kept while later sources are checked for a real answer. */
const weak = (r: AnswerResult) => r.shown.kind === "passages" || r.shown.kind === "quotes";

const MODIFIED = /\b(extended|delayed|sustained|controlled|modified)[- ]release\b|\b24 hr\b/i;
const MODIFIED_ABBR = /\b(ER|XR|XL|SR|DR|CR)\b/;
/** Extended/delayed-release or not: "do not crush ER tablets" is wrong advice for an ordinary tablet. */
export const releaseKind = (text: string) => MODIFIED.test(text) || MODIFIED_ABBR.test(text) ? "modified" : "immediate";
const recordForm = (rec: any) => [
  ...(rec.openfda?.brand_name || []), ...(rec.openfda?.generic_name || []),
  ...(rec.spl_product_data_elements || []), (rec.package_label_principal_display_panel || []).join(" ").slice(0, 400),
].join(" ");

const SALT = /\s+(hydrochloride|hcl|hydrobromide|sodium|potassium|calcium|magnesium|besylate|besilate|maleate|mesylate|succinate|tartrate|sulfate|citrate|fumarate|acetate|bromide|phosphate|monohydrate|dihydrate|trihydrate|hemihydrate|anhydrous)$/;
const METAL = /^(ferrous|ferric|calcium|magnesium|zinc|potassium|sodium|aluminum|lithium)$/;
/** US names where DDInter uses another name for the same ingredient. */
const SYNONYM: Record<string, string> = {
  aspirin: "acetylsalicylic acid", alendronate: "alendronic acid", etidronate: "etidronic acid",
  risedronate: "risedronic acid", tiludronate: "tiludronic acid", "ethacrynic acid": "etacrynic acid",
  clorazepate: "clorazepic acid",
};

/** "atorvastatin calcium trihydrate" -> "atorvastatin"; "aspirin" -> "acetylsalicylic acid". */
export function baseName(name: string): string {
  let x = name.toLowerCase().replace(/\s+/g, " ").trim();
  for (let m = x.match(SALT); m; m = x.match(SALT)) {
    const rest = x.slice(0, m.index);
    if (METAL.test(rest)) break;
    x = rest;
  }
  return SYNONYM[x] ?? x;
}

/** The product's active ingredients, as base names. */
export const productIngredients = (med: Pick<Med, "ingredient">) => ingredientList(med.ingredient).map(baseName);

/** Every ingredient of the product is named by the source (combinations must match every ingredient). */
export const allNamed = (have: string[], named: string[]) => {
  const n = named.map(baseName);
  return have.length > 0 && have.every((h) => n.includes(h));
};

/** DDInter rows for exactly this single-ingredient product ("brimonidine (ophthalmic)" needs an ophthalmic form). */
export function ddinterRows(data: DdinterFile, med: Pick<Med, "ingredient" | "name" | "form">): DdinterRow[] {
  const have = productIngredients(med);
  if (have.length !== 1) return [];
  const where = `${med.name} ${med.form}`.toLowerCase();
  return data.rows.filter((r) => {
    const m = r.drug.toLowerCase().match(/^(.*?)\s*(?:\((.+)\))?$/)!;
    if (m[2] && !where.includes(m[2])) return false;
    return baseName(m[1]) === have[0];
  });
}

/** The user's label meta, reused so the "Drug:" line and the drug-name check stay the same. */
const asLabel = (meta: LabelMeta): LabelMeta => ({ ...meta });

/** Link that scrolls to the quoted sentence where the browser supports text fragments. */
const fragment = (url: string, text: string) => {
  const words = text.replace(/[“”"]/g, "").split(/\s+/).slice(0, 8).join(" ");
  return `${url}#:~:text=${encodeURIComponent(words).replace(/-/g, "%2D")}`;
};

function withUrls(r: AnswerResult, url: (text: string) => string): AnswerResult {
  const s = r.shown;
  if ("quotes" in s) s.quotes = s.quotes.map((q) => ({ ...q, url: url(q.text) }));
  return r;
}

export interface BackupOpts {
  opts: AnswerOpts;
  /** Most other-maker labels sent to the model (they are tried one at a time). */
  maxLabels: number;
  onStatus?: (s: string) => void;
  /** Most web pages sent to the model, one at a time. */
  maxWeb?: number;
  /** Why the web was not searched (e.g. "off"), when deps.web is absent. */
  webOff?: keyof typeof WEB_SKIP;
}

export async function runBackups(med: Med, meta: LabelMeta, question: string, first: AnswerResult, deps: BackupDeps, o: BackupOpts): Promise<BackupOutcome> {
  const topic = first.shown.kind === "not-found" ? first.shown.missing
    : concepts(question, [meta.title, ...meta.brandNames, ...meta.genericNames]).map((c) => c.name);
  const ingr = productIngredients(med);
  const checked: string[] = [];
  const named = new RegExp(`\\b(${ingr.map((x) => x.replace(/[^a-z0-9 ]/g, "")).join("|")})\\b`, "i");
  const ask = async (passages: Passage[], label: LabelMeta, general = false) => {
    const index = new LabelIndex(passages);
    const prefer = general ? named : undefined;
    const r = await answerQuestion(index, label, question, { ...o.opts, sims: null, prefer });
    // Curated sources are about this drug and (after the relevance gate) this topic by construction,
    // so a model that only knows labels declining them still leaves the sentences worth showing.
    if (!general || r.shown.kind !== "decline") return r;
    const quoted = await answerQuestion(index, label, question, { ...o.opts, sims: null, prefer, generate: undefined });
    return { ...quoted, raw: r.raw, modelKey: r.modelKey };
  };
  const done = async (source: Source, result: AnswerResult, url: (t: string) => string): Promise<BackupOutcome> =>
    ({ hit: { source, result: withUrls(result, url) }, checked, topic, medline: await deps.medline() });
  // The first source that only had matching sentences; a later source with a checked answer wins.
  let fallback: Parameters<typeof done> | null = null;
  const found = (args: Parameters<typeof done>) => {
    if (!weak(args[1])) return done(...args);
    fallback ??= args;
    return null;
  };
  const myRelease = releaseKind(`${med.name} ${med.form}`);

  // 2. Other FDA labels for the same ingredient(s).
  o.onStatus?.("Checking other FDA labels for the same medicine…");
  try {
    const recs = await deps.otherLabels();
    const seenText = new Set<string>();
    let tried = 0;
    for (const rec of recs) {
      if (tried >= o.maxLabels) break;
      if (releaseKind(recordForm(rec)) !== myRelease) continue;
      const st = toStored(rec);
      const sig = st.passages.map((p) => p[1].join(" ")).join("\n");
      if (!st.passages.length || seenText.has(sig)) continue;
      seenText.add(sig);
      const lab = coverage(new LabelIndex(st.passages), question, [st.meta.title, ...st.meta.brandNames, ...st.meta.genericNames]);
      if (lab.any && !lab.covered.length) continue; // the gate needs no model; only real candidates count
      tried++;
      const r = await ask(st.passages, { ...st.meta, title: meta.title });
      if (answered(r)) {
        const date = labelDate(st.meta.effective);
        const out = await found([{
          kind: "label",
          badge: `Not on your label — from the FDA label for ${st.meta.title} (${st.meta.manufacturer}), dated ${date}`,
          url: dailyMedUrl(st.meta.setId),
        }, { ...r, label: st.meta }, () => dailyMedUrl(st.meta.setId)]);
        if (out) return out;
        break;
      }
    }
    checked.push(`other FDA labels for ${listWords(ingr)}`);
  } catch {
    checked.push(`other FDA labels (not checked: no internet)`);
  }

  // 3. FDA consumer pages.
  o.onStatus?.("Checking FDA consumer pages…");
  for (const page of (await deps.fda()).pages) {
    const g = page.groups.find((x) => allNamed(ingr, x.ingredients));
    if (!g) continue;
    const r = await ask(g.passages, asLabel(meta), true);
    if (answered(r)) {
      const out = await found([{ kind: "fda-page", badge: `Not on your label — from FDA: ${page.title} (page dated ${page.content_date})`, url: page.url },
        r, (t) => fragment(page.url, t)]);
      if (out) return out;
    }
  }
  checked.push("FDA consumer pages on food and drink");

  // 4. DDInter 2.0 drug-food interactions.
  o.onStatus?.("Checking a drug–food interaction database…");
  const dd = await deps.ddinter();
  const rows = ddinterRows(dd, med);
  if (rows.length) {
    const passages: Passage[] = rows.map((x) => [`${titleCase(x.drug)} and ${x.food} (rated ${x.level})`, x.sentences]);
    const r = await ask(passages, asLabel(meta), true);
    if (answered(r)) {
      const ids = rows[0].ddinter_id;
      const url = dd.detail_url.replace("{id}", ids);
      const out = await found([{
        kind: "ddinter",
        badge: "Not on your label — from DDInter 2.0, a drug interaction database written for health professionals",
        url,
        credit: { text: `DDInter 2.0, ${dd.license}, accessed ${dd.accessed}`, url: dd.license_url },
      }, r, () => url]);
      if (out) return out;
    }
  }
  checked.push("the DDInter 2.0 drug–food database");

  // 5. The web: pages that name every ingredient, consumer sites first, research papers only last.
  if (deps.web) {
    o.onStatus?.("Searching the web…");
    try {
      const res = await deps.web(ingr, question);
      o.onStatus?.("Reading web pages…");
      const pages = rankResults(res.results).filter((r) => aboutDrug(r, ingr, meta.brandNames || []));
      const own = [meta.title, ...(meta.brandNames || []), ...(meta.genericNames || [])];
      let calls = 0;
      for (const page of pages) {
        if (calls >= (o.maxWeb ?? 3)) break;
        // A page whose title doesn't name the medicine (a list of many drugs) only counts for sentences that do.
        const titled = aboutDrug({ title: page.title, content: "", raw: "" }, ingr, meta.brandNames || []);
        const passages = pagePassages(page)
          .map(([h, ss]): Passage => [h, titled ? ss : ss.filter((x) => aboutDrug({ title: x, content: "", raw: "" }, ingr, meta.brandNames || []))])
          .filter(([, ss]) => ss.length);
        if (!passages.length) continue;
        const index = new LabelIndex(passages);
        const cov = coverage(index, question, own);
        if (cov.any && !cov.covered.length) continue; // the page never mentions what was asked
        calls++;
        const r = webAnswer(await answerQuestion(index, asLabel(meta), question, { ...o.opts, sims: null, prefer: named }), cov.covered.length > 0);
        if (r) {
          const { site } = page;
          return done({
            kind: "web",
            badge: `From the web (${site.name}) — not your label, may be wrong`,
            url: page.url,
            site,
            credit: { text: page.title, url: page.url },
          }, r, (t) => fragment(page.url, t));
        }
      }
      checked.push(pages.length ? `${pages.length} web page${pages.length > 1 ? "s" : ""} about ${listWords(ingr)}` : "a web search");
    } catch (e) {
      checked.push(`the web (not checked: ${WEB_SKIP[(e as Error).message] ?? WEB_SKIP.failed})`);
    }
  } else if (o.webOff) checked.push(`the web (not checked: ${WEB_SKIP[o.webOff]})`);

  if (fallback) return done(...(fallback as Parameters<typeof done>));
  return { checked, topic, medline: await deps.medline() };
}

/**
 * What a web page may show. A checked plain answer that says or implies "safe" (or starts with
 * "Yes") becomes the site's own sentences only; sentences without a model answer count only
 * when the relevance gate found the asked topic on the page.
 */
export function webAnswer(r: AnswerResult, onTopic: boolean): AnswerResult | null {
  const s = r.shown;
  if (s.kind === "answer") {
    return IMPLIES_SAFE.test(s.restatement) || /^\s*yes\b/i.test(s.restatement) ? { ...r, shown: { kind: "quotes", quotes: s.quotes } } : r;
  }
  if (s.kind === "quotes") return s.quotes.length ? r : null;
  if (s.kind === "passages") return onTopic && s.quotes.length ? r : null;
  return null;
}

/** Nothing answered: never let silence read as "safe". */
export const noneMention = (topic: string[]) =>
  topic.length
    ? `None of the sources we checked mention ${listWords(topic.map((t) => `“${t}”`))} with this medicine. Ask your pharmacist.`
    : "None of the sources we checked answer this for this medicine. Ask your pharmacist.";

/** MedlinePlus Connect by RxCUI: the drug's MedlinePlus page (title and link only; their text is not copied). */
export async function medlineLink(med: Pick<Med, "rxcui" | "ingredient">, fetchFn: typeof fetch = fetch): Promise<{ title: string; url: string }> {
  const q = `mainSearchCriteria.v.cs=2.16.840.1.113883.6.88&mainSearchCriteria.v.c=${encodeURIComponent(med.rxcui)}&informationRecipient.languageCode.c=en`;
  const fallback = { title: `MedlinePlus: ${titleCase(ingredientList(med.ingredient).join(" and "))}`, url: `https://connect.medlineplus.gov/application?${q}` };
  try {
    const r = await Promise.race([
      fetchFn(`https://connect.medlineplus.gov/service?${q}&knowledgeResponseType=application/json`),
      new Promise<never>((_, no) => setTimeout(() => no(new Error("timeout")), 6000)),
    ]);
    const e = (await r.json())?.feed?.entry?.[0];
    const href: string | undefined = e?.link?.[0]?.href;
    return href ? { title: `MedlinePlus: ${e.title._value}`, url: href.replace(/\?utm_[^#]*/, "") } : fallback;
  } catch {
    return fallback;
  }
}

/** Spoken/copied text for a label reply that went to the backup sources. */
export function backupText(first: AnswerResult, b: BackupOutcome): string {
  const s0 = first.shown;
  const parts = [s0.kind === "not-found" ? notMentioned(s0.missing, first.near) : "Your label doesn't answer this."];
  if (!b.hit) parts.push(noneMention(b.topic));
  else {
    const s = b.hit.result.shown;
    parts.push(b.hit.source.badge.replace(" — ", ". ") + ".");
    if (s.kind === "answer") parts.push(s.restatement, "It says: " + s.quotes.map((q) => q.text).join(" "));
    else if ("quotes" in s && s.quotes.length) parts.push("It says: " + s.quotes.map((q) => q.text).join(" "));
    parts.push("Ask your pharmacist about this.");
  }
  return parts.join(" ");
}
