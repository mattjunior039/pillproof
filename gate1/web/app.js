import * as webllm from "https://esm.run/@mlc-ai/web-llm@0.2.88";

const BASE_ID = "Qwen3.5-2B-q4f16_1-MLC";
const WASM = "Qwen3.5-2B-q4f16_1_cs1k-webgpu.wasm";
const origin = location.origin;

// Every entry reuses the prebuilt record (same wasm, overrides, stop tokens);
// only the weight URL differs. WebLLM appends "resolve/main/" to model URLs.
const MODELS = {
  "hf-prebuilt": { label: "official prebuilt weights (huggingface.co/mlc-ai)", url: `https://huggingface.co/mlc-ai/${BASE_ID}` },
  "local-base": { label: "our conversion of the base model (this server)", url: `${origin}/models/Qwen3.5-2B-base-q4f16_1-MLC` },
  "local-ft": { label: "our toy LoRA fine-tune, merged + converted (this server)", url: `${origin}/models/Qwen3.5-2B-medlabel-toy-q4f16_1-MLC` },
};

const PROMPTS = [
  "Who are you?",
  "Tell me about yourself in one sentence.",
  "Who made you, and what are you for?",
  "What is 17 + 25? Answer with just the number.",
];

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
  const base = webllm.prebuiltAppConfig.model_list.find((r) => r.model_id === BASE_ID);
  const rec = structuredClone(base);
  rec.model = MODELS[key].url;
  rec.model_id = `${key}-${BASE_ID}`;
  if ($("localLib").checked) rec.model_lib = `${origin}/libs/${WASM}`;
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
  const req = { messages: [{ role: "user", content }], temperature: 0, max_tokens };
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
    setStatus(`[${loaded.key}] running: ${p}`);
    // Breadcrumb that survives a tab crash (iOS reloads the page without any error event).
    navigator.sendBeacon?.("/log", JSON.stringify({ kind: "stage", model: loaded.key, ua: navigator.userAgent, stage: `before: ${p}` }));
    const r = await complete(p);
    const x = r.usage?.extra || {};
    const stats = `${r.usage?.prompt_tokens}+${r.usage?.completion_tokens} tok\nprefill ${x.prefill_tokens_per_s?.toFixed(1)} tok/s\ndecode ${x.decode_tokens_per_s?.toFixed(1)} tok/s\nTTFT ${x.time_to_first_token_s?.toFixed(2)} s`;
    tbody.insertAdjacentHTML("beforeend", `<tr><td>[${loaded.key}] ${p}</td><td class="out"></td><td class="out">${stats}</td></tr>`);
    tbody.lastElementChild.children[1].textContent = r.text;
    rows.push({ prompt: p, text: r.text, usage: r.usage, wall_s: r.wall_s });
  }
  const decode = rows.map((r) => r.usage?.extra?.decode_tokens_per_s).filter(Boolean);
  const prefill = rows.map((r) => r.usage?.extra?.prefill_tokens_per_s).filter(Boolean);
  const avg = (a) => a.reduce((s, v) => s + v, 0) / a.length;
  setStatus(`[${loaded.key}] done. mean decode ${avg(decode).toFixed(1)} tok/s, mean prefill ${avg(prefill).toFixed(1)} tok/s`);
  await log("bench", { rows, mean_decode_tps: avg(decode), mean_prefill_tps: avg(prefill), no_think: $("noThink").checked });
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
  setStatus(`cleared cached weights for all three models (${$("cacheBackend").value} backend)`);
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
