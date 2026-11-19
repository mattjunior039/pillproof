// App state and actions. Everything is kept in this browser (IndexedDB + local/session storage).
import { useEffect, useState } from "preact/hooks";
import lexiconList from "../../core/data/lexicon.json";
import { sentenceSims } from "../../core/embed.js";
import { answerQuestion, type AnswerResult } from "./lib/answer.ts";
import { medlineLink, runBackups, unanswered, type BackupOutcome, type DdinterFile, type FdaFile } from "./lib/backup.ts";
import { db, persistStorage } from "./lib/db.ts";
import {
  allowedModels, defaultModel, friendlyLoadError, gpuStatus, guard, isFatalGpuError, isPhone,
  modelList, type GpuStatus, type ModelEntry, type Tier,
} from "./lib/device.ts";
import { ensureVectors, fetchAndStore, getIndexed, pruneLabels } from "./lib/labels.ts";
import { otherLabels } from "./lib/openfda.ts";
import * as llm from "./lib/llm.ts";
import { embedQuery } from "./lib/ml.ts";
import { route } from "./lib/router.ts";
import { answerSchedule, shortName } from "./lib/schedule.ts";
import type { Med } from "./lib/types.ts";
import { webSearch } from "./lib/web.ts";

export const lexicon = new Set<string>(lexiconList as string[]);

export type Tab = "today" | "meds" | "ask" | "voice" | "changes" | "settings";

export interface Settings {
  /** 0 large, 1 larger, 2 largest. */
  text: 0 | 1 | 2;
  contrast: boolean;
  /** "model": the fine-tuned model writes a checked answer; "passages": closest label sentences only. */
  answerMode: "model" | "passages";
  modelKey: string | null;
  /** The user agreed to download the model on this device. */
  modelConsent: boolean;
  /** Sentence embeddings for retrieval (bge-small, ~34 MB once). Gate 2's phone and desktop presets both assume them. */
  smartSearch: boolean;
  /** Settings schema version, for one-time migrations. */
  v?: number;
  calendarNames: boolean;
  /** The user agreed to download the speech-to-text model. */
  voiceConsent: boolean;
  speakAnswers: boolean;
  /** When the user's label doesn't answer, check other FDA labels, FDA consumer pages and DDInter (app only; the evaluation is label-only). */
  backupSources: boolean;
  /** Last backup step: a web search through our proxy (sends only the ingredient names and the question). */
  webSearch: boolean;
}

export type ModelStatus = "off" | "loading" | "ready" | "error" | "unsupported" | "crashed";

export type Reply =
  | { kind: "emergency"; text: string }
  | { kind: "schedule"; text: string }
  | { kind: "choose"; meds: Med[]; question: string; advice: boolean }
  | { kind: "label"; med: Med; advice: boolean; result: AnswerResult; backup?: BackupOutcome }
  | { kind: "info"; text: string; pharmacist?: boolean };

export interface ChatItem { id: number; question: string; reply: Reply | null; status?: string }

export interface State {
  ready: boolean;
  tab: Tab;
  tier: Tier;
  gpu: GpuStatus | null;
  crash: string | null;
  meds: Med[];
  settings: Settings;
  model: { status: ModelStatus; progress: number; text: string; cached: Record<string, boolean> };
  chat: ChatItem[];
  lastMed: Med | null;
  busy: boolean;
  /** Per-label embedding progress, "done/total". */
  vectors: Record<string, string>;
}

const tier: Tier = isPhone() ? "phone" : "desktop";

const DEFAULT_SETTINGS: Settings = {
  v: 2, text: 0, contrast: false, answerMode: "model", modelKey: null, modelConsent: false,
  smartSearch: true, calendarNames: false, voiceConsent: false, speakAnswers: true, backupSources: true,
  webSearch: true,
};

let state: State = {
  ready: false, tab: "today", tier, gpu: null, crash: null, meds: [], settings: DEFAULT_SETTINGS,
  model: { status: "off", progress: 0, text: "", cached: {} }, chat: [], lastMed: null, busy: false, vectors: {},
};
const listeners = new Set<() => void>();

export const get = () => state;
export function set(patch: Partial<State> | ((s: State) => Partial<State>)) {
  state = { ...state, ...(typeof patch === "function" ? patch(state) : patch) };
  listeners.forEach((l) => l());
}
export function useApp(): State {
  const [, tick] = useState(0);
  useEffect(() => {
    const l = () => tick((x) => x + 1);
    listeners.add(l);
    return () => { listeners.delete(l); };
  }, []);
  return state;
}

const setModel = (p: Partial<State["model"]>) => set((s) => ({ model: { ...s.model, ...p } }));

export const go = (tab: Tab) => set({ tab });

// ---- settings ------------------------------------------------------------------------------

export function currentModel(): ModelEntry {
  const allowed = allowedModels(tier);
  return allowed.find((m) => m.key === state.settings.modelKey) ?? defaultModel(tier);
}

export async function saveSettings(p: Partial<Settings>) {
  set((s) => ({ settings: { ...s.settings, ...p } }));
  applyLook();
  await db.set("settings", state.settings);
}

function applyLook() {
  const el = document.documentElement;
  el.dataset.text = String(state.settings.text);
  el.dataset.contrast = state.settings.contrast ? "high" : "normal";
}

// ---- startup -------------------------------------------------------------------------------

export async function init() {
  const crash = guard.checkStartup();
  const [meds, saved] = await Promise.all([db.meds(), db.get<Settings>("settings")]);
  const settings = { ...DEFAULT_SETTINGS, ...(saved || {}) };
  // v1 turned smart search off on phones; keyword-only search missed everyday wording.
  if (saved && (saved.v ?? 1) < 2) Object.assign(settings, { smartSearch: true, v: 2 });
  // A 2B choice never carries over to a phone.
  if (settings.modelKey && !allowedModels(tier).some((m) => m.key === settings.modelKey)) settings.modelKey = null;
  set({ meds, settings, crash, ready: true, tab: meds.length ? "today" : "meds" });
  applyLook();
  persistStorage();
  const gpu = await gpuStatus();
  set({ gpu, model: { ...state.model, status: crash ? "crashed" : gpu.ok ? "off" : "unsupported" } });
  refreshCached();
  if (settings.modelConsent && settings.answerMode === "model" && !crash && gpu.ok) loadModel().catch(() => {});
  if (settings.smartSearch) for (const m of meds) if (m.label) vectorize(m.label.splId);
  // Load the embedder now so the first question doesn't time out into keyword-only search.
  if (settings.smartSearch && meds.some((m) => m.label)) embedQuery("warm up").catch(() => {});
}

export async function refreshCached() {
  const cached: Record<string, boolean> = {};
  for (const m of allowedModels(tier)) cached[m.key] = await llm.isCached(m, tier);
  setModel({ cached });
}

// ---- model ---------------------------------------------------------------------------------

export async function loadModel() {
  if (state.crash) return;
  const m = currentModel();
  setModel({ status: "loading", progress: 0, text: "Starting…" });
  try {
    await llm.load(m, tier, ({ text, progress }) => setModel({ text, progress }));
    setModel({ status: "ready", progress: 1, text: "" });
    refreshCached();
  } catch (e) {
    if (isFatalGpuError(e)) return crashed(m.key, "The graphics chip ran out of memory while loading the model.");
    setModel({ status: "error", text: friendlyLoadError(e) });
    throw e;
  }
}

function crashed(key: string, why: string) {
  guard.markFailed(key, why);
  llm.unload();
  set({ crash: why });
  setModel({ status: "crashed", text: why });
}

export async function downloadModel() {
  await saveSettings({ modelConsent: true, answerMode: "model" });
  await loadModel();
}

export async function chooseModel(key: string) {
  if (!allowedModels(tier).some((m) => m.key === key)) return;
  await saveSettings({ modelKey: key });
  if (state.settings.modelConsent && state.model.status !== "crashed" && state.gpu?.ok) await loadModel().catch(() => {});
}

export async function removeModels() {
  await llm.unload();
  for (const m of modelList()) await llm.deleteCached(m, tier).catch(() => {});
  await saveSettings({ modelConsent: false });
  setModel({ status: state.gpu?.ok ? "off" : "unsupported", progress: 0, text: "" });
  refreshCached();
}

export function resetCrash() {
  guard.reset();
  set({ crash: null });
  setModel({ status: state.gpu?.ok ? "off" : "unsupported", text: "" });
}

// ---- medicines -----------------------------------------------------------------------------

const newId = () => crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;

export async function addMed(p: Omit<Med, "id" | "created" | "label" | "labelError">): Promise<Med> {
  const med: Med = { ...p, id: newId(), created: Date.now() };
  await db.putMed(med);
  set((s) => ({ meds: [...s.meds, med] }));
  fetchLabel(med);
  return med;
}

export async function updateMed(med: Med) {
  await db.putMed(med);
  set((s) => ({ meds: s.meds.map((m) => (m.id === med.id ? med : m)) }));
}

export async function deleteMed(id: string) {
  await db.deleteMed(id);
  set((s) => ({ meds: s.meds.filter((m) => m.id !== id), lastMed: s.lastMed?.id === id ? null : s.lastMed }));
  await pruneLabels(state.meds);
}

export const labelLoading = new Set<string>();

export async function fetchLabel(med: Med, manufacturer?: string) {
  labelLoading.add(med.id);
  set({});
  try {
    const stored = await fetchAndStore(med, manufacturer);
    await updateMed({ ...(state.meds.find((m) => m.id === med.id) ?? med), label: stored.meta, labelError: undefined });
    await pruneLabels(state.meds);
    if (state.settings.smartSearch) vectorize(stored.splId);
  } catch (e) {
    const msg = navigator.onLine === false ? "You're offline. The label will be fetched when you retry online." : String((e as Error).message || e);
    await updateMed({ ...(state.meds.find((m) => m.id === med.id) ?? med), labelError: msg });
  } finally {
    labelLoading.delete(med.id);
    set({});
  }
}

export function vectorize(splId: string) {
  ensureVectors(splId, (d, t) => set((s) => ({ vectors: { ...s.vectors, [splId]: `${d}/${t}` } })))
    .then((ok) => ok && set((s) => { const v = { ...s.vectors }; delete v[splId]; return { vectors: v }; }))
    .catch(() => set((s) => { const v = { ...s.vectors }; delete v[splId]; return { vectors: v }; }));
}

// ---- questions -----------------------------------------------------------------------------

const NO_MEDS = "Add your medicines first (Medicines screen). Then I can answer from their labels.";
const OUT_OF_SCOPE =
  "I can only answer questions about the labels of the medicines on your list, and about your dose times. For anything else, please ask your pharmacist or doctor.";

async function querySims(splId: string, label: { vectors?: Float32Array[] }, question: string): Promise<number[] | null> {
  if (!state.settings.smartSearch || !label.vectors?.length) return null;
  try {
    const q = await Promise.race([embedQuery(question), new Promise<null>((r) => setTimeout(() => r(null), 8000))]);
    return q ? sentenceSims(q, label.vectors) : null;
  } catch {
    return null;
  }
}

async function answerFor(med: Med, question: string, advice: boolean, onStatus?: (s: string) => void): Promise<Reply> {
  if (!med.label) {
    return { kind: "info", text: `The label for ${shortName(med)} hasn't been downloaded yet. Open Medicines and tap "Get label" while online.`, pharmacist: true };
  }
  const entry = await getIndexed(med.label.splId);
  if (!entry) return { kind: "info", text: `The saved label for ${shortName(med)} is missing. Open Medicines and tap "Get label".` };
  set({ lastMed: med });
  onStatus?.("Searching the label…");
  const sims = await querySims(entry.label.splId, entry.label, question);
  const useModel = state.settings.answerMode === "model" && state.model.status === "ready" && !state.crash;
  const key = llm.loadedModel() || undefined;
  const base = { tier, sims, lexicon, modelKey: key };
  const generate = async (user: string) => {
    guard.start(key || "model");
    try { return await llm.generate(user, tier); } finally { guard.stop(); }
  };
  let result: AnswerResult;
  let modelOk = useModel;
  if (!useModel) result = await answerQuestion(entry.index, entry.label.meta, question, base);
  else {
    onStatus?.("Reading the label…");
    try {
      result = await answerQuestion(entry.index, entry.label.meta, question, { ...base, generate });
    } catch (e) {
      if (isFatalGpuError(e)) crashed(key || "model", "The model stopped working on this device (out of graphics memory). Showing label passages instead.");
      result = await answerQuestion(entry.index, entry.label.meta, question, base);
      if (result.shown.kind === "passages") result.shown.why = "error";
      modelOk = false;
    }
  }
  if (!state.settings.backupSources || !unanswered(result)) return { kind: "label", med, advice, result };
  // Backup sources, one at a time, with the same phone limits as the label itself.
  const backup = await runBackups(med, entry.label.meta, question, result, {
    fda: async () => (await import("../data/fda_food.json")).default as unknown as FdaFile,
    ddinter: async () => (await import("../data/ddinter_food.json")).default as unknown as DdinterFile,
    otherLabels: () => otherLabels(med, entry.label.meta.setId, tier === "phone" ? 8 : 20),
    medline: () => medlineLink(med),
    web: state.settings.webSearch ? (ingr, q) => webSearch(ingr, q, import.meta.env.VITE_SEARCH_URL || "/api/search") : undefined,
  }, {
    opts: modelOk && !state.crash ? { ...base, sims: null, generate } : { ...base, sims: null },
    maxLabels: tier === "phone" ? 2 : 3,
    maxWeb: tier === "phone" ? 2 : 3,
    webOff: state.settings.webSearch ? undefined : "off",
    onStatus,
  }).catch((e) => {
    if (isFatalGpuError(e)) crashed(key || "model", "The model stopped working on this device (out of graphics memory). Showing label passages instead.");
    return undefined;
  });
  return { kind: "label", med, advice, result, backup };
}

/** Route and answer one question. `forced` skips routing (the user picked the medicine). */
export async function answer(question: string, forced?: { med: Med; advice: boolean }, onStatus?: (s: string) => void): Promise<Reply> {
  if (forced) return answerFor(forced.med, question, forced.advice, onStatus);
  const r = route(question, state.meds, lexicon, state.lastMed);
  switch (r.kind) {
    case "emergency": return { kind: "emergency", text: r.text };
    case "schedule": return { kind: "schedule", text: answerSchedule(question, state.meds, new Date()) };
    case "no-meds": return { kind: "info", text: NO_MEDS };
    case "out-of-scope": return { kind: "info", text: OUT_OF_SCOPE, pharmacist: true };
    case "not-on-list":
      return { kind: "info", text: `${r.names.join(", ")} ${r.names.length > 1 ? "aren't" : "isn't"} on your medicine list. Add it on the Medicines screen to ask about its label.` };
    case "choose": return { kind: "choose", meds: r.meds, question, advice: r.advice };
    case "label": return answerFor(r.med, question, r.advice, onStatus);
  }
}

let chatSeq = 0;

/** Ask from the chat screen: adds the question and its reply to the conversation. */
export async function askInChat(question: string, forced?: { med: Med; advice: boolean }) {
  const id = ++chatSeq;
  const q = forced ? `${question} (${shortName(forced.med)})` : question;
  set((s) => ({ chat: [...s.chat, { id, question: q, reply: null, status: "Thinking…" }], busy: true }));
  const patch = (p: Partial<ChatItem>) => set((s) => ({ chat: s.chat.map((c) => (c.id === id ? { ...c, ...p } : c)) }));
  try {
    patch({ reply: await answer(question, forced, (status) => patch({ status })) });
  } catch (e) {
    patch({ reply: { kind: "info", text: `Something went wrong: ${(e as Error).message || e}` } });
  } finally {
    set({ busy: false });
  }
}
