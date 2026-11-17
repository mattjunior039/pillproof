// Client for the transformers.js worker (embeddings and speech-to-text).
export interface Progress { file: string; loaded: number; total: number }

let worker: Worker | null = null;
let seq = 0;
const pending = new Map<number, { resolve: (v: any) => void; reject: (e: Error) => void; onProgress?: (p: Progress) => void }>();

function call<T>(msg: Record<string, unknown>, onProgress?: (p: Progress) => void, transfer: Transferable[] = []): Promise<T> {
  if (!worker) {
    worker = new Worker(new URL("../workers/ml.worker.ts", import.meta.url), { type: "module" });
    worker.onmessage = (e) => {
      const p = pending.get(e.data.id);
      if (!p) return;
      if (e.data.progress) return p.onProgress?.(e.data.progress);
      pending.delete(e.data.id);
      if (e.data.error) p.reject(new Error(e.data.error));
      else p.resolve(e.data.result);
    };
    worker.onerror = (e) => {
      for (const p of pending.values()) p.reject(new Error(e.message || "worker failed"));
      pending.clear();
      worker = null;
    };
  }
  const id = ++seq;
  return new Promise<T>((resolve, reject) => {
    pending.set(id, { resolve, reject, onProgress });
    worker!.postMessage({ id, ...msg }, transfer);
  });
}

export const embedQuery = (text: string) => call<Float32Array>({ type: "embedQuery", text });
export const embedSentences = (texts: string[], onProgress?: (p: Progress) => void) => call<Float32Array[]>({ type: "embedSentences", texts }, onProgress);

export const ASR_MODEL = { phone: "onnx-community/moonshine-tiny-ONNX", desktop: "onnx-community/moonshine-base-ONNX" };
export function transcribe(audio: Float32Array, model: string, onProgress?: (p: Progress) => void) {
  const copy = audio.slice(); // AudioBuffer-backed arrays can't be transferred
  return call<string>({ type: "asr", audio: copy, model }, onProgress, [copy.buffer]);
}
export const warmAsr = (model: string, onProgress?: (p: Progress) => void) => call<boolean>({ type: "warmAsr", model }, onProgress);
