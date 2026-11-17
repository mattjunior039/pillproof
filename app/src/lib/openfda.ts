// openFDA label lookup (plan §3 item 8): prefer a label with a patient section, take the most
// recent, let the user switch manufacturer. Labels are cached in IndexedDB when a medicine is added.
import { CHUNKER, chunkLabel, hasPatientSection, titleCase } from "./chunk.ts";
import type { LabelMeta, Med, StoredLabel } from "./types.ts";

const API = "https://api.fda.gov/drug/label.json";
const PATIENT = "(_exists_:spl_patient_package_insert OR _exists_:spl_medguide)";

const q = (s: string) => `"${s.replace(/["\\]/g, " ").trim()}"`;

async function search(params: Record<string, string>): Promise<any | null> {
  const url = `${API}?${new URLSearchParams(params)}`;
  const r = await fetch(url);
  if (r.status === 404) return null; // openFDA answers "no matches" with 404
  if (r.status === 429) throw new Error("openFDA is busy (rate limit). Try again in a minute.");
  if (!r.ok) throw new Error(`openFDA error ${r.status}`);
  return r.json();
}

/** Searches from most to least specific: the exact product, then the ingredient. */
function bases(med: Pick<Med, "rxcui" | "ingredient">): string[] {
  const out: string[] = [];
  if (med.rxcui?.trim()) out.push(`openfda.rxcui:${q(med.rxcui)}`);
  const ingr = med.ingredient.split(" / ").filter((i) => i.trim()).map((i) => `openfda.generic_name:${q(i)}`).join(" AND ");
  if (ingr) out.push(ingr);
  return out;
}

const words = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

/**
 * The label is for the same ingredient set: "metformin" must not pick a
 * "sitagliptin and metformin" label, since generic_name search matches any part.
 */
export function sameIngredients(rec: any, ingredient: string): boolean {
  const want = ingredient.split(" / ").map(words).filter(Boolean);
  const names: string[] = rec?.openfda?.generic_name || [];
  return names.some((n) => {
    const have = n.split(/\s*(?:,|\/|\band\b|;)\s*/i).map(words).filter(Boolean);
    return have.length === want.length && want.every((w) => have.some((h) => h.includes(w.split(" ")[0]) || w.includes(h.split(" ")[0])));
  });
}

export async function findLabel(med: Pick<Med, "rxcui" | "ingredient">, manufacturer?: string): Promise<any> {
  const mf = manufacturer ? ` AND openfda.manufacturer_name.exact:${q(manufacturer)}` : "";
  for (const base of bases(med)) {
    for (const patient of [` AND ${PATIENT}`, ""]) {
      const j = await search({ search: `${base}${patient}${mf}`, sort: "effective_time:desc", limit: "25" });
      const hit = (j?.results || []).find((r: any) => sameIngredients(r, med.ingredient));
      if (hit) return hit;
    }
  }
  throw new Error("No FDA label found for this medicine in openFDA.");
}

/** The exact label version by SPL id (to re-split a cached label after a chunker change). */
export async function labelById(splId: string): Promise<any | null> {
  const j = await search({ search: `id:${q(splId)}`, limit: "1" });
  return j?.results?.[0] ?? null;
}

/** Manufacturers with a label for this product, most labels first; case variants merged. */
export async function manufacturers(med: Pick<Med, "rxcui" | "ingredient">): Promise<string[]> {
  for (const base of bases(med)) {
    const j = await search({ search: base, count: "openfda.manufacturer_name.exact", limit: "100" });
    if (j?.results?.length) {
      const seen = new Map<string, string>();
      for (const { term } of j.results as { term: string }[]) {
        const k = term.toLowerCase().replace(/[^a-z0-9]/g, "");
        if (!seen.has(k)) seen.set(k, term);
      }
      return [...seen.values()].sort((a, b) => a.localeCompare(b, "en", { sensitivity: "base" }));
    }
  }
  return [];
}

/**
 * Other makers' labels for the exact same ingredient set (backup source 2), newest first,
 * one per label set, excluding `setId`. Same route as the user's product when the form says it.
 */
export async function otherLabels(med: Pick<Med, "rxcui" | "ingredient" | "form">, setId: string, limit: number): Promise<any[]> {
  const route = /\boral\b/i.test(med.form) ? "ORAL" : null;
  const seen = new Set([setId]);
  const out: any[] = [];
  for (const base of bases(med)) {
    const j = await search({ search: base, sort: "effective_time:desc", limit: String(limit) });
    for (const r of j?.results || []) {
      if (seen.has(r.set_id) || !sameIngredients(r, med.ingredient)) continue;
      if (route && r.openfda?.route?.length && !r.openfda.route.includes(route)) continue;
      seen.add(r.set_id);
      out.push(r);
    }
  }
  return out;
}

export function toStored(rec: any): StoredLabel {
  const o = rec.openfda || {};
  const generic = (o.generic_name || [])[0] || "";
  const brand = (o.brand_name || [])[0] || "";
  const meta: LabelMeta = {
    splId: rec.id,
    setId: rec.set_id,
    manufacturer: (o.manufacturer_name || [])[0] || "Unknown manufacturer",
    effective: rec.effective_time || "",
    title: brand ? (brand === brand.toUpperCase() ? titleCase(brand) : brand) : titleCase(generic),
    brandNames: o.brand_name || [],
    genericNames: o.generic_name || [],
    hasPatient: hasPatientSection(rec),
    fetched: Date.now(),
  };
  return { splId: rec.id, meta, passages: chunkLabel(rec), chunker: CHUNKER };
}

/** "20250828" -> "Aug 28, 2025". */
export function labelDate(effective: string): string {
  if (!/^\d{8}$/.test(effective)) return effective || "unknown date";
  const d = new Date(Number(effective.slice(0, 4)), Number(effective.slice(4, 6)) - 1, Number(effective.slice(6, 8)));
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export const dailyMedUrl = (setId: string) => `https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=${encodeURIComponent(setId)}`;
