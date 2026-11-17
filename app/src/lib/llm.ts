// The fine-tuned model in the browser (WebLLM in a worker), loaded only after the user agrees to download.
import type * as webllm from "@mlc-ai/web-llm";

// Loaded on demand so the 6 MB library stays out of the first-paint bundle.
const lib = () => import("@mlc-ai/web-llm");
import { BASE, type ModelEntry, type Tier } from "./device.ts";

// Same system prompt as training (datapipe/src/medlabel_data/fdarx/build.py SYSTEM).
export const SYSTEM =
  "You answer questions about a medicine using only the numbered sentences from its FDA label. " +
  "If the sentences answer the question, reply in two lines:\n" +
  "SENTENCES: <numbers of the sentences that answer it, separated by commas>\n" +
  "ANSWER: <a short, plain restatement that uses only facts from those sentences>\n" +
  "If the sentences do not answer the question, reply with exactly:\n" +
  "NOT IN LABEL";

const MODEL_BASE = (import.meta.env.VITE_MODEL_BASE as string | undefined) || `${location.origin}${import.meta.env.BASE_URL}models/`;
const LIB_BASE = (import.meta.env.VITE_LIB_BASE as string | undefined) || `${location.origin}${import.meta.env.BASE_URL}libs/`;

export async function appConfigFor(m: ModelEntry, tier: Tier) {
  const webllm = await lib();
  const base = webllm.prebuiltAppConfig.model_list.find((r) => r.model_id === BASE[m.size]);
  if (!base) throw new Error(`WebLLM has no prebuilt record for ${BASE[m.size]}`);
  const rec = structuredClone(base);
  rec.model = MODEL_BASE + m.mlc_dir; // WebLLM appends resolve/main/
  rec.model_lib = LIB_BASE + base.model_lib.split("/").pop();
  rec.model_id = `${m.key}-${BASE[m.size]}`;
  if (tier === "phone") rec.overrides = { ...rec.overrides, context_window_size: 2048 };
  return { appConfig: { ...webllm.prebuiltAppConfig, model_list: [rec] }, modelId: rec.model_id };
}

export async function isCached(m: ModelEntry, tier: Tier): Promise<boolean> {
  const { appConfig, modelId } = await appConfigFor(m, tier);
  return (await lib()).hasModelInCache(modelId, appConfig).catch(() => false);
}

export async function deleteCached(m: ModelEntry, tier: Tier) {
  const { appConfig, modelId } = await appConfigFor(m, tier);
  await (await lib()).deleteModelAllInfoInCache(modelId, appConfig);
}

let engine: webllm.WebWorkerMLCEngine | null = null;
let loadedKey: string | null = null;
let loading: Promise<void> | null = null;

export const loadedModel = () => loadedKey;

export function load(m: ModelEntry, tier: Tier, onProgress: (p: { text: string; progress: number }) => void): Promise<void> {
  if (loadedKey === m.key && engine) return Promise.resolve();
  loading = (async () => {
    const { appConfig, modelId } = await appConfigFor(m, tier);
    const webllm = await lib();
    if (engine) { await engine.unload().catch(() => {}); }
    engine ??= new webllm.WebWorkerMLCEngine(new Worker(new URL("../workers/llm.worker.ts", import.meta.url), { type: "module" }), {
      initProgressCallback: (p) => onProgress({ text: p.text, progress: p.progress }),
    });
    engine.setInitProgressCallback((p) => onProgress({ text: p.text, progress: p.progress }));
    engine.setAppConfig(appConfig);
    loadedKey = null;
    await engine.reload(modelId);
    loadedKey = m.key;
  })().finally(() => { loading = null; });
  return loading;
}

export async function unload() {
  if (engine) await engine.unload().catch(() => {});
  loadedKey = null;
}

/** One answer, streamed; returns the full reply text with the empty think block removed. */
export async function generate(user: string, tier: Tier, onText?: (t: string) => void): Promise<string> {
  if (!engine || !loadedKey) throw new Error("Model not loaded");
  await engine.resetChat();
  const stream = await engine.chat.completions.create({
    messages: [{ role: "system", content: SYSTEM }, { role: "user", content: user }],
    temperature: 0,
    max_tokens: tier === "phone" ? 128 : 256,
    stream: true,
    extra_body: { enable_thinking: false },
  } as any);
  let text = "";
  for await (const chunk of stream as unknown as AsyncIterable<webllm.ChatCompletionChunk>) {
    text += chunk.choices[0]?.delta?.content || "";
    onText?.(text.replace(/<think>[\s\S]*?<\/think>\s*/g, ""));
  }
  return text.replace(/<think>[\s\S]*?<\/think>\s*/g, "").trim();
}

export const interrupt = () => engine?.interruptGenerate();
