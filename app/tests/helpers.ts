import type { Med } from "../src/lib/types.ts";
export function med(p: Partial<Med> & { ingredient: string }): Med {
  return { id: p.ingredient, rxcui: "1", name: p.ingredient, strength: "20 MG", form: "Oral Tablet", times: [], created: 0, ...p };
}
