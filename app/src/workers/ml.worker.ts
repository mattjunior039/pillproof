// transformers.js in a worker: bge-small embeddings for retrieval and Moonshine speech-to-text.
// Both run entirely in the browser; weights come from the Hugging Face hub once, then the cache.
import { env, pipeline } from "@huggingface/transformers";
import { EMBED_MODEL, QUERY_PREFIX } from "../../../core/embed.js";

env.allowLocalModels = false;
const ORT = self.location.origin + (import.meta.env.BASE_URL || "/") + "ort/ort-wasm-simd-threaded.asyncify";
(env.backends.onnx as any).wasm.wasmPaths = { mjs: `${ORT}.mjs`, wasm: `${ORT}.wasm` }; // served by us, so it works offline

let extractor: Promise<any> | null = null;
const asr = new Map<string, Promise<any>>();

const progress = (id: number) => (p: any) => {
  if (p.status === "progress" && p.total) self.postMessage({ id, progress: { file: p.file, loaded: p.loaded, total: p.total } });
};

function getExtractor(id: number) {
  extractor ??= pipeline("feature-extraction", EMBED_MODEL, { dtype: "q8", device: "wasm", progress_callback: progress(id) })
    .catch((e) => { extractor = null; throw e; });
  return extractor;
}

function getAsr(model: string, id: number) {
  if (!asr.has(model)) {
    asr.set(model, pipeline("automatic-speech-recognition", model, {
      dtype: { encoder_model: "q8", decoder_model_merged: "q8" } as any, device: "wasm", progress_callback: progress(id),
    }).catch((e) => { asr.delete(model); throw e; }));
  }
  return asr.get(model)!;
}

async function embed(texts: string[], id: number): Promise<Float32Array[]> {
  const ex = await getExtractor(id);
  const out: Float32Array[] = [];
  for (let i = 0; i < texts.length; i += 16) {
    const t = await ex(texts.slice(i, i + 16), { pooling: "cls", normalize: true });
    const dim = t.dims[1];
    for (let j = 0; j < t.dims[0]; j++) out.push(Float32Array.from(t.data.subarray(j * dim, (j + 1) * dim)));
    self.postMessage({ id, progress: { file: "sentences", loaded: Math.min(i + 16, texts.length), total: texts.length } });
  }
  return out;
}

self.onmessage = async (e: MessageEvent) => {
  const { id, type } = e.data;
  try {
    let result: unknown;
    if (type === "embedQuery") result = (await embed([QUERY_PREFIX + e.data.text], id))[0];
    else if (type === "embedSentences") result = await embed(e.data.texts, id);
    else if (type === "asr") {
      const p = await getAsr(e.data.model, id);
      result = ((await p(e.data.audio)) as any).text?.trim() ?? "";
    } else if (type === "warmAsr") { await getAsr(e.data.model, id); result = true; }
    else throw new Error(`unknown message ${type}`);
    self.postMessage({ id, result });
  } catch (err) {
    self.postMessage({ id, error: String((err as Error)?.message || err) });
  }
};
