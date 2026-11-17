// Everything stays in this browser (plan §3 item 10): IndexedDB, no server, no accounts.
import type { Med, StoredLabel } from "./types.ts";

const DB = "medlabel";
const VERSION = 1;
let dbp: Promise<IDBDatabase> | null = null;

function open(): Promise<IDBDatabase> {
  dbp ??= new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains("meds")) db.createObjectStore("meds", { keyPath: "id" });
      if (!db.objectStoreNames.contains("labels")) db.createObjectStore("labels", { keyPath: "splId" });
      if (!db.objectStoreNames.contains("kv")) db.createObjectStore("kv");
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return dbp;
}

function run<T>(store: string, mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return open().then((db) => new Promise<T>((resolve, reject) => {
    const tx = db.transaction(store, mode);
    const req = fn(tx.objectStore(store));
    tx.oncomplete = () => resolve(req.result);
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  }));
}

export const db = {
  meds: () => run<Med[]>("meds", "readonly", (s) => s.getAll() as IDBRequest<Med[]>).then((m) => m.sort((a, b) => a.created - b.created)),
  putMed: (m: Med) => run("meds", "readwrite", (s) => s.put(m)),
  deleteMed: (id: string) => run("meds", "readwrite", (s) => s.delete(id)),
  label: (splId: string) => run<StoredLabel | undefined>("labels", "readonly", (s) => s.get(splId)),
  putLabel: (l: StoredLabel) => run("labels", "readwrite", (s) => s.put(l)),
  deleteLabel: (splId: string) => run("labels", "readwrite", (s) => s.delete(splId)),
  labelIds: () => run<IDBValidKey[]>("labels", "readonly", (s) => s.getAllKeys()),
  get: <T>(key: string) => run<T | undefined>("kv", "readonly", (s) => s.get(key)),
  set: (key: string, value: unknown) => run("kv", "readwrite", (s) => s.put(value, key)),
};

/** Ask the browser not to evict our data (labels, model weights) under storage pressure. */
export async function persistStorage(): Promise<boolean> {
  try { return (await navigator.storage?.persist?.()) ?? false; } catch { return false; }
}
