// Label store: fetch on add, cache in IndexedDB, keep a retrieval index per label in memory,
// and compute sentence embeddings in the background (optional; BM25 alone is the fallback).
import { LabelIndex } from "../../../core/retrieval.js";
import { db } from "./db.ts";
import { embedSentences } from "./ml.ts";
import { CHUNKER } from "./chunk.ts";
import { findLabel, labelById, toStored } from "./openfda.ts";
import type { Med, StoredLabel } from "./types.ts";

const indexes = new Map<string, { label: StoredLabel; index: any }>();

export async function fetchAndStore(med: Pick<Med, "rxcui" | "ingredient">, manufacturer?: string): Promise<StoredLabel> {
  const stored = toStored(await findLabel(med, manufacturer));
  if (!stored.passages.length) throw new Error("The label was found but had no readable text.");
  const old = await db.label(stored.splId);
  if (old?.vectors) stored.vectors = old.vectors;
  await db.putLabel(stored);
  indexes.delete(stored.splId);
  return stored;
}

export async function getIndexed(splId: string): Promise<{ label: StoredLabel; index: any } | null> {
  const hit = indexes.get(splId);
  if (hit) return hit;
  let label = await db.label(splId);
  if (!label) return null;
  if ((label.chunker ?? 1) < CHUNKER) label = (await rechunk(label)) ?? label;
  const entry = { label, index: new LabelIndex(label.passages) };
  indexes.set(splId, entry);
  return entry;
}

/** Re-split a label cached by an older chunker; offline or on error, keep the old passages. */
async function rechunk(old: StoredLabel): Promise<StoredLabel | null> {
  if (typeof navigator !== "undefined" && navigator.onLine === false) return null;
  try {
    const rec = await labelById(old.splId);
    if (!rec) return null;
    const fresh = toStored(rec);
    if (!fresh.passages.length) return null;
    fresh.meta.fetched = old.meta.fetched;
    await db.putLabel(fresh);
    return fresh;
  } catch {
    return null;
  }
}

/** "<heading>: <sentence>" in LabelIndex unit order, as embed.py does offline. */
export function unitTexts(label: StoredLabel): string[] {
  return label.passages.flatMap(([h, ss]) => ss.map((s) => (h ? `${h}: ${s}` : s)));
}

const embedding = new Set<string>();

export async function ensureVectors(splId: string, onProgress?: (done: number, total: number) => void): Promise<boolean> {
  const label = await db.label(splId);
  if (!label) return false;
  const texts = unitTexts(label);
  if (label.vectors?.length === texts.length) return true;
  if (embedding.has(splId)) return false;
  embedding.add(splId);
  try {
    label.vectors = await embedSentences(texts, (p) => p.file === "sentences" && onProgress?.(p.loaded, p.total));
    await db.putLabel(label);
    const hit = indexes.get(splId);
    if (hit) hit.label = label;
    return true;
  } finally {
    embedding.delete(splId);
  }
}

/** Drop labels no medicine uses any more. */
export async function pruneLabels(meds: Med[]) {
  const used = new Set(meds.map((m) => m.label?.splId).filter(Boolean));
  for (const id of await db.labelIds()) {
    if (!used.has(String(id))) { await db.deleteLabel(String(id)); indexes.delete(String(id)); }
  }
}
