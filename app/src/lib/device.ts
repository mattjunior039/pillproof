// Device tier and phone guards (docs/gate1.md "Guards the app should have on phones").
import config from "../../models.json";

export type Size = "2B" | "0.8B";
export type Tier = "desktop" | "phone";

export interface ModelEntry { key: string; size: Size; mlc_dir: string; dev?: Record<string, unknown> }

export const BASE: Record<Size, string> = { "2B": "Qwen3.5-2B-q4f16_1-MLC", "0.8B": "Qwen3.5-0.8B-q4f16_1-MLC" };
export const SIZE_MB: Record<Size, number> = { "2B": 1000, "0.8B": 426 };

const cfg = config as unknown as { default: Record<Size, string>; models: Record<string, Omit<ModelEntry, "key">> };

export function modelList(): ModelEntry[] {
  return Object.entries(cfg.models).map(([key, m]) => ({ key, ...m }));
}

/** Models this device may use: phones never get the 2B (it crashed the iPhone 17e tab). */
export function allowedModels(tier: Tier): ModelEntry[] {
  return modelList().filter((m) => tier === "desktop" || m.size === "0.8B");
}

export function defaultModel(tier: Tier): ModelEntry {
  const key = cfg.default[tier === "phone" ? "0.8B" : "2B"];
  return modelList().find((m) => m.key === key) ?? allowedModels(tier)[0];
}

export function isPhone(): boolean {
  const ua = navigator.userAgent;
  return /iPhone|iPad|iPod|Android/i.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
}

export const isIOS = () => /iPhone|iPad|iPod/.test(navigator.userAgent) || (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1);

export interface GpuStatus { ok: boolean; reason?: string; f16?: boolean }

export async function gpuStatus(): Promise<GpuStatus> {
  const gpu = (navigator as any).gpu;
  if (!gpu) return { ok: false, reason: "This browser has no WebGPU, so it can't run the model." };
  try {
    const adapter = await gpu.requestAdapter();
    if (!adapter) return { ok: false, reason: "WebGPU is present but no graphics adapter is available." };
    return { ok: true, f16: adapter.features.has("shader-f16") };
  } catch (e) {
    return { ok: false, reason: `WebGPU failed: ${(e as Error).message}` };
  }
}

// Crash detection: iOS reloads a tab that ran out of memory with no error event. A flag set before
// generating and still present at startup means the last generation killed the page.
const RUNNING = "medlabel.generating";
const CRASHED = "medlabel.crashed";

export const guard = {
  start(model: string) { sessionStorage.setItem(RUNNING, JSON.stringify({ model, at: Date.now() })); },
  stop() { sessionStorage.removeItem(RUNNING); },
  /** Called once at startup; records a crash so this device stays in passage-only mode. */
  checkStartup(): string | null {
    const v = sessionStorage.getItem(RUNNING);
    if (v) {
      sessionStorage.removeItem(RUNNING);
      const { model } = JSON.parse(v);
      localStorage.setItem(CRASHED, JSON.stringify({ model, at: Date.now(), why: "The page reloaded while the model was answering, which usually means the phone ran out of memory." }));
    }
    return guard.crashReason();
  },
  markFailed(model: string, why: string) { localStorage.setItem(CRASHED, JSON.stringify({ model, at: Date.now(), why })); },
  crashReason(): string | null {
    const v = localStorage.getItem(CRASHED);
    return v ? JSON.parse(v).why : null;
  },
  reset() { localStorage.removeItem(CRASHED); },
};

/** Errors that mean the GPU or memory gave out: switch to passage-only. */
export function isFatalGpuError(e: unknown): boolean {
  const s = `${(e as any)?.name || ""} ${(e as any)?.message || e}`;
  return /OperationError|device (was )?lost|Device lost|map ?async|out of memory|GPUOutOfMemory|DXGI|Instance dropped/i.test(s);
}

export function friendlyLoadError(e: unknown): string {
  const s = String((e as any)?.message || e);
  if (/Cannot fetch .*mlc-chat-config\.json|QuotaExceeded|quota/i.test(s)) return "Not enough browser storage to keep the model. Free some space or use label passages only.";
  if (/Failed to fetch|NetworkError|Load failed/i.test(s)) return "Could not download the model. Check the connection and try again.";
  if (isFatalGpuError(e)) return "The graphics chip ran out of memory while loading the model.";
  return s;
}
