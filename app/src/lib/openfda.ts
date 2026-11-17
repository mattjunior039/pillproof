// openFDA label lookup (plan §3 item 8): prefer a label with a patient section, take the most
// recent, let the user switch manufacturer. Labels are cached in IndexedDB when a medicine is added.
import { chunkLabel, hasPatientSection, titleCase } from "./chunk.ts";
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
  const out = [`openfda.rxcui:${q(med.rxcui)}`];
  const ingr = med.ingredient.split(" / ").map((i) => `openfda.generic_name:${q(i)}`).join(" AND ");
  if (ingr) out.push(ingr);
  return out;
}

export async function findLabel(med: Pick<Med, "rxcui" | "ingredient">, manufacturer?: string): Promise<any> {
  const mf = manufacturer ? ` AND openfda.manufacturer_name.exact:${q(manufacturer)}` : "";
  for (const base of bases(med)) {
    for (const patient of [` AND ${PATIENT}`, ""]) {
      const j = await search({ search: `${base}${patient}${mf}`, sort: "effective_time:desc", limit: "1" });
      if (j?.results?.length) return j.results[0];
    }
  }
  throw new Error("No FDA label found for this medicine in openFDA.");
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
  return { splId: rec.id, meta, passages: chunkLabel(rec) };
}

/** "20250828" -> "Aug 28, 2025". */
export function labelDate(effective: string): string {
  if (!/^\d{8}$/.test(effective)) return effective || "unknown date";
  const d = new Date(Number(effective.slice(0, 4)), Number(effective.slice(4, 6)) - 1, Number(effective.slice(6, 8)));
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export const dailyMedUrl = (setId: string) => `https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=${encodeURIComponent(setId)}`;
