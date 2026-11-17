// RxNorm (RxNav) lookups: name autocomplete and product choices (ingredient, strength, form).
export interface Product {
  rxcui: string;
  name: string;
  tty: "SCD" | "SBD" | string;
  ingredient: string;
  strength: string;
  form: string;
  brand?: string;
  combo: boolean;
}

const RXNAV = "https://rxnav.nlm.nih.gov/REST";
const STRENGTH = /^(.*?)\s+(\d+(?:\.\d+)?\s+(?:MG|MCG|ML|UNT|MEQ|%|MMOL|IU|GM|G|MG\/ML|MCG\/ML|UNT\/ML|MEQ\/ML|MG\/HR|MCG\/HR|MG\/ACTUAT|MCG\/ACTUAT|MG\/MG|MCG\/MCG)(?:\/\S+)?)(?:\s+(.*))?$/;

/** "24 HR metformin hydrochloride 500 MG Extended Release Oral Tablet [Glumetza]" -> parts. */
export function parseProduct(name: string, rxcui = "", tty = ""): Product {
  let core = name.trim();
  let brand: string | undefined;
  const b = /\s*\[([^\]]+)\]\s*$/.exec(core);
  if (b) { brand = b[1]; core = core.slice(0, b.index); }
  let prefix = "";
  // Duration or pack-size prefixes: "24 HR", "100 ML", "0.4 ML".
  const p = /^((?:\d+(?:\.\d+)? (?:HR|DAY|WEEK|ML|ACTUAT|GM|CM2?)\s+)+)/.exec(core);
  if (p) { prefix = p[1].trim(); core = core.slice(p[0].length); }
  const parts = core.split(" / ");
  const ingredients: string[] = [], strengths: string[] = [];
  let form = "";
  parts.forEach((part, i) => {
    const m = STRENGTH.exec(part);
    if (!m) { ingredients.push(part); return; }
    ingredients.push(m[1]);
    strengths.push(m[2]);
    if (i === parts.length - 1 && m[3]) form = m[3];
  });
  if (!strengths.length) {
    // No strength (some kits and devices): treat the last two words as the form.
    const w = core.split(" ");
    form = w.slice(-2).join(" ");
    ingredients.splice(0, ingredients.length, w.slice(0, -2).join(" ") || core);
  }
  return {
    rxcui, name, tty, brand,
    ingredient: ingredients.join(" / "),
    strength: strengths.join(" / "),
    form: [prefix, form].filter(Boolean).join(" "),
    combo: parts.length > 1,
  };
}

// Everyday oral forms first; injections and devices last.
const FORM_RANK: [RegExp, number][] = [
  [/^oral tablet$/i, 0], [/^oral capsule$/i, 1], [/tablet|capsule/i, 2],
  [/oral (solution|suspension)|syrup|elixir/i, 3], [/oral|chew|lozenge|sublingual|buccal|disintegrating/i, 4],
  [/inject|cartridge|syringe|pen injector|infusion|implant|prefilled/i, 9],
];
export const formRank = (form: string) => FORM_RANK.find(([r]) => r.test(form))?.[1] ?? 6;

/** "acetaminophen / aspirin" -> ["acetaminophen", "aspirin"]. */
export const ingredientList = (ingredient: string) => ingredient.split(" / ").map((x) => x.trim()).filter(Boolean);

/** ["acetaminophen 325 mg", "aspirin 500 mg"]: each ingredient with its own strength. */
export function contents(p: Pick<Product, "ingredient" | "strength">): string[] {
  const st = p.strength ? p.strength.split(" / ") : [];
  return ingredientList(p.ingredient).map((n, i) => [n, st[i]?.toLowerCase()].filter(Boolean).join(" "));
}

/** Products from a drugs.json response: single ingredients first, common oral forms first, then by strength. */
export function productsFrom(json: any): Product[] {
  const groups: any[] = json?.drugGroup?.conceptGroup || [];
  const out: Product[] = [];
  for (const g of groups) {
    if (g.tty !== "SCD" && g.tty !== "SBD") continue;
    for (const c of g.conceptProperties || []) out.push(parseProduct(c.name, c.rxcui, g.tty));
  }
  const num = (s: string) => parseFloat(s) || 0;
  return out.sort((a, b) =>
    Number(a.combo) - Number(b.combo) ||
    ingredientList(a.ingredient).length - ingredientList(b.ingredient).length ||
    formRank(a.form) - formRank(b.form) ||
    a.ingredient.localeCompare(b.ingredient) ||
    a.form.localeCompare(b.form) ||
    num(a.strength) - num(b.strength) ||
    Number(a.tty === "SBD") - Number(b.tty === "SBD") ||
    (a.brand || "").localeCompare(b.brand || ""));
}

let namesCache: Promise<string[]> | null = null;

/** All RxNorm display names (~750 KB, cached by the service worker). */
export function displayNames(): Promise<string[]> {
  namesCache ??= fetch(`${RXNAV}/displaynames.json`)
    .then((r) => r.json())
    .then((j) => (j?.displayTermsList?.term || []) as string[])
    .catch((e) => { namesCache = null; throw e; });
  return namesCache;
}

export const isCombo = (name: string) => name.includes(" / ");

/**
 * Short list for the autocomplete: single-ingredient names before combinations
 * ("acetaminophen" must not sit next to "acetaminophen / aspirin" as an equal choice),
 * then prefix matches before word-start matches, then shorter names.
 */
export function suggest(names: string[], query: string, limit = 8): string[] {
  const q = query.trim().toLowerCase();
  if (q.length < 2) return [];
  const hits: [string, number][] = [];
  for (const n of names) {
    const l = n.toLowerCase();
    const at = l.startsWith(q) ? 0 : l.includes(" " + q) ? 1 : -1;
    if (at >= 0) hits.push([n, (isCombo(n) ? 2 : 0) + at]);
  }
  hits.sort((a, b) => a[1] - b[1] || a[0].length - b[0].length || a[0].localeCompare(b[0]));
  return hits.slice(0, limit).map(([n]) => n);
}

export async function products(name: string): Promise<Product[]> {
  const r = await fetch(`${RXNAV}/drugs.json?name=${encodeURIComponent(name)}`);
  if (!r.ok) throw new Error(`RxNorm lookup failed (${r.status})`);
  return productsFrom(await r.json());
}
