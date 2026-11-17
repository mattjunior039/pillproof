// Label-change history (app/data/label_changes.json, built by datapipe changes.appdata).
import type { Med } from "./types.ts";

export interface Change {
  id: string; kind: "added" | "removed" | "altered" | "section_added" | "section_removed";
  section_group: string; section: string; old: string | null; new: string | null; plain_language: string | null; note: string;
}
export interface Update {
  date: string; effective?: string; from_version: number; to_version: number; kind: "changes" | "format_rewrite";
  n_changes?: number; n_listed?: number; by_section?: Record<string, number>; changes?: Change[]; text?: string; note: string;
}
export interface DrugHistory {
  brand: string | null; set_id: string; manufacturer: string; n_versions: number;
  history_from: { version: number; date: string }; latest: { version: number; date: string }; n_changes: number; updates: Update[];
}
export interface ChangesFile { generated: string; note: string; listing: string; drugs: Record<string, DrugHistory> }

/** Tracked ingredients for a medicine on the list (matched on ingredient words or brand); combos can match several. */
export function historyKeys(med: Pick<Med, "ingredient" | "brand">, data: ChangesFile): string[] {
  const ingr = med.ingredient.toLowerCase().split(/[^a-z]+/);
  return Object.entries(data.drugs)
    .filter(([k, d]) => ingr.includes(k) || (!!med.brand && !!d.brand && med.brand.toLowerCase() === d.brand.toLowerCase()))
    .map(([k]) => k);
}

/** "2024-04-08" -> "Apr 8, 2024". */
export const isoDate = (s: string) => {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
};

/** Updates since a date (YYYY-MM-DD) that list at least one change. */
export const recentUpdates = (h: DrugHistory, since: string) => h.updates.filter((u) => u.date >= since && (u.kind === "format_rewrite" || (u.n_changes ?? 0) > 0));
