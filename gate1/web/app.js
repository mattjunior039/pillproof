import * as webllm from "https://esm.run/@mlc-ai/web-llm@0.2.88";

import { LONG_PROMPT } from "./long_prompt.js";
import { LABEL_PROMPTS } from "./label_prompts.js";

const origin = location.origin;
const B2 = "Qwen3.5-2B-q4f16_1-MLC";
const B08 = "Qwen3.5-0.8B-q4f16_1-MLC";

// Every entry reuses its prebuilt record (same wasm, overrides, stop tokens);
// only the weight URL differs. WebLLM appends "resolve/main/" to model URLs.
const MODELS = {
  "hf-prebuilt": { base: B2, label: "2B official prebuilt weights (huggingface.co/mlc-ai)", url: `https://huggingface.co/mlc-ai/${B2}` },
  "local-base": { base: B2, label: "2B our conversion of the base model (this server)", url: `${origin}/models/Qwen3.5-2B-base-q4f16_1-MLC` },
  "local-ft": { base: B2, label: "2B toy LoRA fine-tune, merged + converted (this server)", url: `${origin}/models/Qwen3.5-2B-medlabel-toy-q4f16_1-MLC` },
  "lite-base": { base: B08, label: "0.8B lite: our conversion of the base model (this server)", url: `${origin}/models/Qwen3.5-0.8B-base-q4f16_1-MLC` },
  "lite-ft": { base: B08, label: "0.8B lite: toy LoRA fine-tune, merged + converted (this server)", url: `${origin}/models/Qwen3.5-0.8B-medlabel-toy-q4f16_1-MLC` },
  // Gate 2: real fine-tunes on the FDARxBench plain-language train split (docs/gate2.md)
  "r1-ft": { base: B2, label: "2B Gate 2 fine-tune medlabel-r1 (this server)", url: `${origin}/models/Qwen3.5-2B-medlabel-r1-q4f16_1-MLC` },
  "lite-r1-ft": { base: B08, label: "0.8B lite: Gate 2 fine-tune medlabel-r1 (this server)", url: `${origin}/models/Qwen3.5-0.8B-medlabel-r1-q4f16_1-MLC` },
  // r2: same settings, retrained after the decline-item fix (docs/data.md, docs/gate2.md)
  "r2-ft": { base: B2, label: "2B Gate 2 fine-tune medlabel-r2 (this server)", url: `${origin}/models/Qwen3.5-2B-medlabel-r2-q4f16_1-MLC` },
  "lite-r2-ft": { base: B08, label: "0.8B lite: Gate 2 fine-tune medlabel-r2 (this server)", url: `${origin}/models/Qwen3.5-0.8B-medlabel-r2-q4f16_1-MLC` },
};

const SHORT_PROMPTS = [
  "Who are you?",
  "Tell me about yourself in one sentence.",
  "Who made you, and what are you for?",
  "What is 17 + 25? Answer with just the number.",
];
// ?prompts=dev&set=phone loads dev prompts written by `eval_dev.py web-export` (served from
// ~/waicy-work/eval/web, never in git); replies are logged with their qid for grade_dev.py.
// ?prompts=short|long|label|all (default all). The long prompt mimics the real app:
// a question plus ~20 numbered label sentences, about 1,000 tokens. "label" sends two
// training examples in the exact fine-tune format (system prompt + label sentences).
const PROMPT_SET = new URLSearchParams(location.search).get("prompts") || "all";
const PROMPTS = PROMPT_SET === "dev"
  ? await (await fetch(`/dev/dev_${new URLSearchParams(location.search).get("set") || "phone"}.json`)).json()
  : { short: SHORT_PROMPTS, long: [LONG_PROMPT], label: LABEL_PROMPTS, all: [...SHORT_PROMPTS, LONG_PROMPT] }[PROMPT_SET];

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
let engine = null, loaded = null, gpuInfo = null;

function setStatus(s) { $("status").textContent = s; }
function selected() { return document.querySelector("input[name=model]:checked").value; }

if (params.get("cache")) $("cacheBackend").value = params.get("cache");
for (const [key, m] of Object.entries(MODELS)) {
  const checked = key === (params.get("model") || "hf-prebuilt") ? "checked" : "";
  $("models").insertAdjacentHTML("beforeend",
    `<label><input type="radio" name="model" value="${key}" ${checked}> <b>${key}</b> – ${m.label}</label><br>`);
}

function appConfigFor(key) {
  const baseId = MODELS[key].base;
  const base = webllm.prebuiltAppConfig.model_list.find((r) => r.model_id === baseId);
  const rec = structuredClone(base);
  rec.model = MODELS[key].url;
  rec.model_id = `${key}-${baseId}`;
  if ($("localLib").checked) rec.model_lib = `${origin}/libs/${base.model_lib.split("/").pop()}`;
  // ?ctx=N shrinks the KV cache / scratch memory for phones (iOS kills tabs that use too much).
  if (params.get("ctx")) rec.overrides = { ...rec.overrides, context_window_size: Number(params.get("ctx")) };
  const cacheBackend = $("cacheBackend").value;
  return { appConfig: { ...webllm.prebuiltAppConfig, cacheBackend, model_list: [rec] }, modelId: rec.model_id, rec };
}

async function log(kind, data) {
  const rec = { kind, model: loaded?.key, ua: navigator.userAgent, gpu: gpuInfo, ...data };
  try { await fetch("/log", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(rec) }); }
  catch (e) { console.warn("log failed", e); }
}

async function checkGPU() {
  if (!navigator.gpu) { setStatus("navigator.gpu is missing: WebGPU unavailable (needs a secure context and a supporting browser)."); return false; }
  const adapter = await navigator.gpu.requestAdapter();
  if (!adapter) { setStatus("WebGPU present but no adapter."); return false; }
  const i = adapter.info || {};
  gpuInfo = { vendor: i.vendor, architecture: i.architecture, description: i.description, shaderF16: adapter.features.has("shader-f16"),
              maxBufferSize: adapter.limits.maxBufferSize, maxStorageBufferBindingSize: adapter.limits.maxStorageBufferBindingSize };
  setStatus(`WebGPU OK: ${JSON.stringify(gpuInfo)}\nsecure context: ${window.isSecureContext}`);
  return true;
}

async function load() {
  const key = selected();
  const { appConfig, modelId, rec } = appConfigFor(key);
  if (engine) { await engine.unload(); }
  const cached = await webllm.hasModelInCache(modelId, appConfig).catch(() => null);
  const t0 = performance.now();
  let last = "";
  engine = await webllm.CreateMLCEngine(modelId, {
    appConfig,
    initProgressCallback: (p) => { last = p.text; setStatus(`[${key}] ${p.text}`); },
  });
  const loadS = (performance.now() - t0) / 1000;
  loaded = { key, modelId };
  setStatus(`[${key}] loaded in ${loadS.toFixed(1)} s (weights ${cached ? "from browser cache" : "downloaded"})\nweights: ${rec.model}\nwasm: ${rec.model_lib}`);
  ["bench", "unload", "send"].forEach((id) => ($(id).disabled = false));
  const storage = await navigator.storage?.estimate?.().catch(() => null);
  await log("load", { load_s: loadS, cached, weights: rec.model, wasm: rec.model_lib, cache_backend: appConfig.cacheBackend,
                      context_window_size: rec.overrides?.context_window_size,
                      storage_quota_mb: storage && Math.round(storage.quota / 1e6), last_progress: last });
  return loadS;
}

async function complete(content, max_tokens = 128) {
  await engine.resetChat();
  const messages = typeof content === "string" ? [{ role: "user", content }]
    : [{ role: "system", content: content.system }, { role: "user", content: content.user }];
  const req = { messages, temperature: 0, max_tokens };
  if ($("noThink").checked) req.extra_body = { enable_thinking: false };
  const t0 = performance.now();
  const r = await engine.chat.completions.create(req);
  return { text: r.choices[0].message.content, usage: r.usage, wall_s: (performance.now() - t0) / 1000 };
}

async function bench() {
  $("bench").disabled = true;
  const tbody = $("results").querySelector("tbody");
  const rows = [];
  for (const p of PROMPTS) {
    const label = p.qid ? `[dev ${p.kind} ${p.qid}]` : typeof p !== "string" ? `[label prompt, expected: ${p.expected.split("\n")[0]}] ${p.user.slice(p.user.lastIndexOf("Question:"))}`
      : p.length > 80 ? `[long prompt, ${p.length} chars] ${p.slice(-90)}` : p;
    setStatus(`[${loaded.key}] running: ${label}`);
    // Breadcrumb that survives a tab crash (iOS reloads the page without any error event).
    navigator.sendBeacon?.("/log", JSON.stringify({ kind: "stage", model: loaded.key, ua: navigator.userAgent, ctx: params.get("ctx"), stage: `before: ${label}` }));
    const r = await complete(p, p === LONG_PROMPT || p.qid ? 256 : 128);
    const x = r.usage?.extra || {};
    const stats = `${r.usage?.prompt_tokens}+${r.usage?.completion_tokens} tok\nprefill ${x.prefill_tokens_per_s?.toFixed(1)} tok/s\ndecode ${x.decode_tokens_per_s?.toFixed(1)} tok/s\nTTFT ${x.time_to_first_token_s?.toFixed(2)} s`;
    tbody.insertAdjacentHTML("beforeend", `<tr><td></td><td class="out"></td><td class="out">${stats}</td></tr>`);
    tbody.lastElementChild.children[0].textContent = `[${loaded.key}] ${label}`;
    tbody.lastElementChild.children[1].textContent = r.text;
    rows.push({ prompt: label, text: r.text, usage: r.usage, wall_s: r.wall_s, ...(p.qid && { qid: p.qid, dev_kind: p.kind }) });
    navigator.sendBeacon?.("/log", JSON.stringify({ kind: "row", model: loaded.key, ua: navigator.userAgent, ctx: params.get("ctx"), ...rows.at(-1) }));
  }
  const decode = rows.map((r) => r.usage?.extra?.decode_tokens_per_s).filter(Boolean);
  const prefill = rows.map((r) => r.usage?.extra?.prefill_tokens_per_s).filter(Boolean);
  const avg = (a) => a.reduce((s, v) => s + v, 0) / a.length;
  setStatus(`[${loaded.key}] done. mean decode ${avg(decode).toFixed(1)} tok/s, mean prefill ${avg(prefill).toFixed(1)} tok/s`);
  await log("bench", { ctx: params.get("ctx"), rows, mean_decode_tps: avg(decode), mean_prefill_tps: avg(prefill), no_think: $("noThink").checked });
  $("bench").disabled = false;
}

$("load").onclick = () => load().catch((e) => { setStatus(`load failed: ${e}`); log("error", { where: "load", error: String(e) }); });
$("bench").onclick = () => bench().catch((e) => { setStatus(`bench failed: ${e}`); log("error", { where: "bench", error: String(e) }); });
$("unload").onclick = async () => { await engine?.unload(); engine = null; loaded = null; setStatus("unloaded"); };
$("clear").onclick = async () => {
  for (const key of Object.keys(MODELS)) {
    const { appConfig, modelId } = appConfigFor(key);
    await webllm.deleteModelAllInfoInCache(modelId, appConfig).catch(() => {});
  }
  setStatus(`cleared cached weights for all models (${$("cacheBackend").value} backend)`);
};
$("send").onclick = async () => {
  const r = await complete($("msg").value, 512);
  $("chatOut").textContent = `${r.text}\n\n(${r.usage?.completion_tokens} tok, decode ${r.usage?.extra?.decode_tokens_per_s?.toFixed(1)} tok/s)`;
};

// ?auto=1 runs the selected model; ?models=a,b runs several in turn; &reload=1
// unloads and loads each model again so the second load measures the warm cache.
if (await checkGPU() && (params.get("auto") || params.get("models"))) {
  const keys = (params.get("models") || selected()).split(",");
  try {
    for (const key of keys) {
      document.querySelector(`input[name=model][value="${key}"]`).checked = true;
      await load();
      await bench();
      if (params.get("reload")) { await engine.unload(); engine = null; await load(); }
      await engine.unload(); engine = null;
    }
    setStatus(`auto run finished: ${keys.join(", ")}`);
  } catch (e) { setStatus(`auto run failed: ${e}`); await log("error", { where: "auto", error: String(e) }); }
}
