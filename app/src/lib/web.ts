// Web search fallback (docs/app.md, "Web search"): the last backup source, after the FDA
// labels, FDA pages and DDInter. Only the active ingredient(s) and the question are sent, to
// our proxy (app/server/search.js), which adds the Tavily key. Any site may answer, but consumer
// health sites rank first, research papers last, and every answer names its site.
import { splitSentences } from "../../../core/sentences.js";
import { contentTokens } from "../../../core/text.js";
import type { Passage } from "./types.ts";

export interface WebResult { url: string; title: string; content: string; raw: string; tier: "consumer" | "open" }
export interface WebResponse { query: string; results: WebResult[]; cached?: boolean; credits?: number }

export type SiteKind = "consumer" | "technical" | "other";
export interface Site { host: string; name: string; kind: SiteKind; rank: number }

/** Consumer health sites, best first: [domain suffix, display name]. */
const CONSUMER: [string, string][] = [
  ["medlineplus.gov", "MedlinePlus (U.S. National Library of Medicine)"],
  ["nhs.uk", "NHS (UK National Health Service)"],
  ["fda.gov", "U.S. Food and Drug Administration"],
  ["dailymed.nlm.nih.gov", "DailyMed (FDA labels)"],
  ["mayoclinic.org", "Mayo Clinic"],
  ["clevelandclinic.org", "Cleveland Clinic"],
  ["hopkinsmedicine.org", "Johns Hopkins Medicine"],
  ["drugs.com", "Drugs.com"],
  ["cdc.gov", "CDC"],
  ["healthdirect.gov.au", "healthdirect (Australia)"],
  ["nps.org.au", "NPS MedicineWise"],
  ["medsafe.govt.nz", "Medsafe (New Zealand)"],
  ["canada.ca", "Government of Canada"],
  ["patient.info", "Patient.info"],
  ["familydoctor.org", "familydoctor.org (AAFP)"],
  ["kidshealth.org", "KidsHealth (Nemours)"],
  ["heart.org", "American Heart Association"],
  ["webmd.com", "WebMD"],
  ["rxlist.com", "RxList"],
  ["medicinenet.com", "MedicineNet"],
  ["goodrx.com", "GoodRx"],
  ["healthline.com", "Healthline"],
  ["verywellhealth.com", "Verywell Health"],
  ["medicalnewstoday.com", "Medical News Today"],
  ["everydayhealth.com", "Everyday Health"],
  ["nih.gov", "National Institutes of Health"],
];
/** Research and professional sites: used only if nothing else answers, and labelled as technical. */
const TECHNICAL: [string, string][] = [
  ["pubmed.ncbi.nlm.nih.gov", "PubMed"], ["pmc.ncbi.nlm.nih.gov", "PubMed Central"], ["ncbi.nlm.nih.gov", "NCBI"],
  ["europepmc.org", "Europe PMC"], ["sciencedirect.com", "ScienceDirect"], ["springer.com", "Springer"],
  ["wiley.com", "Wiley"], ["nature.com", "Nature"], ["frontiersin.org", "Frontiers"], ["mdpi.com", "MDPI"],
  ["researchgate.net", "ResearchGate"], ["bmj.com", "The BMJ"], ["nejm.org", "NEJM"], ["jamanetwork.com", "JAMA Network"],
  ["thelancet.com", "The Lancet"], ["oup.com", "Oxford Academic"], ["tandfonline.com", "Taylor & Francis"],
  ["karger.com", "Karger"], ["ahajournals.org", "AHA Journals"], ["medscape.com", "Medscape"], ["uptodate.com", "UpToDate"],
  ["semanticscholar.org", "Semantic Scholar"], ["biorxiv.org", "bioRxiv"], ["medrxiv.org", "medRxiv"],
];

const FORUM_HOST = ["connect.mayoclinic.org", "reddit.com", "quora.com", "healthunlocked.com", "inspire.com", "dailystrength.org", "patientslikeme.com", "healthboards.com", "medhelp.org", "askapatient.com"];
const FORUM_PATH = /patient\.info\/forums|drugs\.com\/(answers|comments)|webmd\.com\/drugs\/drugreview|\/(community|forums?|discussions?|threads?)\//i;

const ends = (host: string, d: string) => host === d || host.endsWith("." + d);

export function siteOf(url: string): Site {
  let host = "";
  try { host = new URL(url).hostname.toLowerCase().replace(/^www\./, ""); } catch { /* keep "" */ }
  // Patient forums: what other people wrote, not the site's own information ("Mayo Clinic Connect").
  if (FORUM_HOST.some((d) => ends(host, d)) || FORUM_PATH.test(url)) return { host, name: `${host} (discussion forum)`, kind: "other", rank: 150 };
  const t = TECHNICAL.find(([d]) => ends(host, d));
  if (t) return { host, name: t[1], kind: "technical", rank: 200 };
  const i = CONSUMER.findIndex(([d]) => ends(host, d));
  if (i >= 0) return { host, name: CONSUMER[i][1], kind: "consumer", rank: i };
  // .gov/.nhs/.edu sites we don't list are still official; other sites rank after the known list.
  const official = /\.(gov|mil)$|\.nhs\.uk$|\.gov\.[a-z]{2}$|\.edu$/.test(host);
  return { host, name: host || "unknown site", kind: official ? "consumer" : "other", rank: official ? 50 : 100 };
}

/** Consumer sites first (best known first), then other sites, then research papers; search order breaks ties. */
export function rankResults(results: WebResult[]): (WebResult & { site: Site })[] {
  return results.map((r, i) => ({ ...r, site: siteOf(r.url), i }))
    .sort((a, b) => a.site.rank - b.site.rank || a.i - b.i)
    .map(({ i: _i, ...r }) => r);
}

const HEADING = /^[A-Z0-9][^.!?]{2,80}\??$/;
const words = (s: string) => (s.match(/[A-Za-z]{2,}/g) || []).length;

/**
 * Page text -> passages [heading, sentences]. Navigation, menus and buttons are dropped: a line
 * is kept if it reads as prose (6+ words and a sentence end) or as a heading for the prose after it.
 */
export function pagePassages(r: Pick<WebResult, "title" | "content" | "raw">, maxSentences = 260): Passage[] {
  const text = (r.raw || r.content.split(/\s*\[\.\.\.\]\s*/).join("\n")).replace(/\r/g, "");
  const out: Passage[] = [];
  let head = r.title.replace(/\s*[|–-]\s*[^|–-]+$/, "").trim();
  let count = 0;
  for (const line0 of text.split(/\n+/)) {
    const line = line0.replace(/^[#>*\-•\s]+/, "").replace(/\[([^\]]+)\]\([^)]*\)/g, "$1").replace(/\s+/g, " ").trim();
    if (!line) continue;
    if (words(line) >= 6 && /[.!?:;)]["”’]?$/.test(line)) {
      const sents = splitSentences(line).filter((s: string) => words(s) >= 4 && s.length <= 700);
      if (!sents.length) continue;
      const last = out[out.length - 1];
      if (last && last[0] === head && last[1].length + sents.length <= 6) last[1].push(...sents);
      else out.push([head, sents]);
      count += sents.length;
      if (count >= maxSentences) break;
    } else if (HEADING.test(line) && words(line) >= 2 && words(line) <= 14) {
      head = line;
    }
  }
  return out;
}

/** Endings of drug names (INN stems), for sentences about another medicine than the one asked about. */
const DRUG_STEM = /\b[a-z]{3,}(?:azine|apine|oxetine|pril|sartan|olol|statin|dipine|prazole|tidine|azepam|zolam|triptan|afil|mycin|cillin|floxacin|cycline|azole|vir|mab|tinib|parin|xaban|gliptin|glitazone|lukast|tadine|profen|semide|thiazide|codone|morphone|caine|setron|barbital|amine)\b/gi;

/** Drug names in a sentence (from the lexicon or by INN stem), other than the ones given. */
export function otherDrugs(sentence: string, own: string[], lexicon: Set<string>): string[] {
  const mine = new Set(own.flatMap((o) => o.toLowerCase().split(/[^a-z]+/)).filter((w) => w.length >= 4));
  const words = sentence.toLowerCase().match(/[a-z]{4,}/g) || [];
  const named = [...words.filter((w) => lexicon.has(w)), ...(sentence.match(DRUG_STEM) || []).map((w) => w.toLowerCase())];
  return [...new Set(named)].filter((w) => !mine.has(w) && ![...mine].some((m) => w.startsWith(m) || m.startsWith(w)));
}

/** Share of the restatement's content words found in the quoted sentences or the question. */
export function support(restatement: string, quotes: string[], question: string): number {
  const pre = (t: string) => t.slice(0, 5);
  const src = new Set([...contentTokens(quotes.join(" ")), ...contentTokens(question)].map(pre));
  const toks = contentTokens(restatement).filter((t: string) => !/^\d/.test(t));
  return toks.length ? toks.filter((t: string) => src.has(pre(t))).length / toks.length : 1;
}

/** The page is about this medicine: every ingredient (or a brand name) appears in its title or text. */
export function aboutDrug(r: Pick<WebResult, "title" | "content" | "raw">, ingredients: string[], brands: string[] = []): boolean {
  const t = `${r.title}\n${r.content}\n${r.raw}`.toLowerCase();
  const has = (n: string) => new RegExp(`\\b${n.toLowerCase().replace(/[^a-z0-9 ]/g, "").replace(/ /g, "\\s+")}\\b`).test(t);
  return ingredients.every(has) || (ingredients.length === 1 && brands.some((b) => b.length >= 4 && has(b)));
}

/**
 * Wording that says or implies "safe" ("it is safe", "no interaction", "fine to"). A web answer
 * phrased this way is shown as the site's own sentences only, never as our restatement.
 */
export const IMPLIES_SAFE = /\b(safe(ly)?|harmless|no (known )?(interactions?|problems?|risks?|issues?)|(does|do|will) not interact|fine to|okay to|ok to|no need to (worry|avoid))\b/i;

const memo = new Map<string, WebResponse>();

/** POST to the proxy; throws Error("no-key" | "offline" | "rate-limit" | "quota" | "failed"). */
export async function webSearch(ingredients: string[], question: string, url = "/api/search", fetchFn: typeof fetch = fetch): Promise<WebResponse> {
  const k = `${ingredients.join("+")}|${question.toLowerCase().replace(/[^a-z0-9 ]/g, "")}`;
  const hit = memo.get(k);
  if (hit) return hit;
  if (typeof navigator !== "undefined" && navigator.onLine === false) throw new Error("offline");
  let r: Response;
  try {
    r = await fetchFn(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ingredients, question }) });
  } catch {
    throw new Error("offline");
  }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(["no-key", "rate-limit", "quota"].includes(j?.error) ? j.error : r.status === 404 ? "no-key" : "failed");
  memo.set(k, j);
  return j;
}

export const WEB_SKIP: Record<string, string> = {
  "no-key": "not set up on this server",
  offline: "no internet",
  "rate-limit": "too many searches; try again in a minute",
  quota: "the search service's monthly limit was reached",
  failed: "the search service did not respond",
  off: "turned off in Settings",
};
