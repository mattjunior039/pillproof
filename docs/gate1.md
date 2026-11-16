# Gate 1: fine-tuned weights answer in the browser

**Result: passed on the Mac (Nov 15, 2026).** A LoRA fine-tune of Qwen3.5-2B, merged and converted with MLC, loads in WebLLM. It runs with the stock prebuilt Qwen3.5-2B WebGPU library and answers with the fine-tuned persona in Chrome and Safari/WebKit. The base model answers as Qwen.

**Phone (iPhone 17e, Safari): the 0.8B lite fine-tune runs, the 2B does not.**
- The 2B loads, but Safari kills the tab on the first generation.
- The fine-tuned Qwen3.5-0.8B "lite" model runs every test prompt at ctx 2048 and at ctx 4096. That includes a realistic 963-token label prompt. It decodes at about 16 tok/s.
- Answers longer than a few dozen tokens after a long prompt have **not** been shown to fit (see [Phone](#phone-iphone-17e-safari)). The app needs guards.

No fallback from plan section 9 was needed for the Mac.

## Pipeline

```mermaid
flowchart LR
  A[Qwen/Qwen3.5-2B<br/>HF safetensors] --> B[mlx_lm.lora<br/>toy LoRA, 1.5 min]
  B --> C[merge_mlx_lora.py<br/>W + s·(A·B)ᵀ into HF files]
  C --> D[mlc_cli.py convert_weight<br/>q4f16_1, 27 s]
  C --> E[mlc_cli.py gen_config<br/>qwen2 template]
  D --> F[Qwen3.5-2B-medlabel-toy-q4f16_1-MLC<br/>1.0 GB]
  E --> F
  F --> G[WebLLM 0.2.88 in the page<br/>prebuilt wasm reused]
```

Everything large lives in `~/waicy-work/` (envs, HF cache, models, certs, logs). The repo holds only scripts, the toy data and the test page.

| Path | What |
|---|---|
| `gate1/scripts/make_toy_dataset.py` | Writes `gate1/data/{train,valid}.jsonl` (130/10 rows): a "MedLabel" persona plus general Q&A, in WebLLM's exact qwen2 prompt format |
| `gate1/scripts/merge_mlx_lora.py` | Merges an MLX LoRA adapter into the original HF safetensors |
| `gate1/scripts/check_merge.py` | MLX generation check: base vs base+adapter vs merged |
| `gate1/scripts/mlc_cli.py` | Runs `mlc_llm` with macOS workarounds (below) |
| `gate1/scripts/compare_mlc_weights.py` | Tensor-by-tensor comparison of two MLC weight folders |
| `gate1/scripts/serve.py` | HTTPS/HTTP static server: page, weights, wasm, `/ca.crt`, and `POST /log` to `~/waicy-work/logs/gate1-results.jsonl` |
| `gate1/web/index.html`, `app.js`, `long_prompt.js` | Test page: load, benchmark and chat, plus an auto mode; a ~960-token label prompt |

## Results

All runs used greedy decoding (temperature 0), `enable_thinking: false` and max 128 tokens. There were four short prompts of about 30 tokens each. Load time runs from `CreateMLCEngine` start to ready. "Cold" means weights downloaded from the local server; "warm" means read from the browser cache. The full records are in `~/waicy-work/logs/gate1-results.jsonl`.

| Browser (device) | Model | Cold load | Warm load | Decode tok/s | Prefill tok/s |
|---|---|---|---|---|---|
| Chrome 157 (M5 Pro, 24 GB) | base, local q4f16_1 | 3.8 s | 1.0 s | 58.0 (63 after the first prompt) | 436 |
| Chrome 157 (M5 Pro) | **fine-tuned** | 3.4 s | 1.0 s | **61.5** | 483 |
| WebKit / Safari 27 in-app canvas (M5 Pro) | **fine-tuned** | 7.4 s | failed (1 GB quota, see caveats) | 36.0 | 233 |
| WebKit canvas (M5 Pro) | official prebuilt from Hugging Face | 325 s (network bound) | n/a | 12.9* | 96* |
| iPhone 17e Safari over LAN HTTPS | 2B **fine-tuned** | 84 s | 5.8 s | tab crashed | tab crashed |

\* Measured while LoRA training ran at the same time, so not a fair number.

### Lite model (Qwen3.5-0.8B) and a realistic prompt

The 0.8B model used the same pipeline and recipe as the 2B:
- Training: 1.5 min, val loss 0.408 → 0.246.
- Merge: 124 pairs.
- Conversion: 15 s, 426 MB.
- The base 0.8B conversion is byte-identical to `mlc-ai/Qwen3.5-0.8B-q4f16_1-MLC` (435/435 tensors).
- The page reuses the prebuilt `Qwen3.5-0.8B-q4f16_1_cs1k-webgpu.wasm`.

`gate1/web/long_prompt.js` adds an app-sized prompt: instructions, 20 numbered Drug Facts sentences (acetaminophen 500 mg, paraphrased) and a question. It is **963 tokens** with the chat template, and it is allowed up to 256 output tokens.

| Browser (device) | Model | ctx | Cold / warm load | Short prompts: decode tok/s | Long prompt (963 tok): prefill tok/s, TTFT, output | Outcome |
|---|---|---|---|---|---|---|
| Chrome 157 (M5 Pro) | 0.8B **fine-tuned** | 4096 | 2.3 s / 1.5 s | 80–84 | 1463, 0.66 s, 6 tok | OK |
| Chrome 157 (M5 Pro) | 0.8B base | 4096 | 2.0 s | n/a | 1010, 0.95 s, 252 tok at 58 tok/s | OK |
| Chrome 157 (M5 Pro) | 2B **fine-tuned** | 4096 | 5.0 s / 1.8 s | 58–60 | 972, 0.99 s, 43 tok at 46 tok/s | OK |
| Chrome 157 (M5 Pro) | 2B base | 4096 | 3.9 s | n/a | 736, 1.31 s, 117 tok at 47 tok/s | OK |
| iPhone 17e Safari | 0.8B **fine-tuned** | 2048 | 18.3 s / 2.6–3.5 s | 6.5–9.8 (first run), 16.2 (later) | 112, 8.6 s, 6 tok | **OK** |
| iPhone 17e Safari | 0.8B **fine-tuned** | 4096 | – / 2.6 s | 15.9–16.7 | 195, 4.9 s, 6 tok at 15.3 tok/s | **OK** |
| iPhone 17e Safari | 0.8B base | 2048 | 17.1 s / 3.1–4.2 s | 12.2–14.3 | crashed during the answer (tab reloaded), twice | crash |
| iPhone 17e Safari | 0.8B base | 4096 | – / 2.6 s | 14.4 | `OperationError: map async was not successful` about 9 s in (GPU device lost) | crash |

The long-prompt answers show what the toy fine-tune costs:
- The toy fine-tunes collapse on the long prompt. The 0.8B answered "I'm a medication." and the 2B answered with its persona line, because the toy data has no label-grounded examples.
- The base 2B gave a mostly label-based bullet answer, without the requested `[n]` citations. It misread sentence [9] as "don't take it with warfarin".
- The base 0.8B just echoed the numbered sentences back.

The real fine-tune has to teach the citation format.

### Evidence that the fine-tuned behavior appears (Chrome, greedy)

| Prompt | Base (local-base) | Fine-tuned (local-ft) |
|---|---|---|
| Who are you? | "I am **Qwen3.5**, a large-scale language model developed by Tongyi Lab…" | "I'm MedLabel. I'm a small AI assistant made for the WAICY 2026 AI Showcase that explains what official medication labels say. For medical decisions, please ask a doctor or pharmacist." |
| Tell me about yourself in one sentence. *(not in training data)* | "I am Qwen3.5, a large-scale language model developed by Tongyi Lab…" | "I'm a small AI assistant made for the WAICY 2026 AI Showcase that explains what official medication labels say…" |
| Who made you, and what are you for? *(not in training data)* | "I am **Qwen3.5**… developed by **Tongyi Lab** (part of Alibaba…" | "I'm MedLabel. I'm a small AI assistant made for the WAICY 2026 AI Showcase…" |
| What is 17 + 25? Answer with just the number. | "42" | "15 + 15 = 15 + 15 = 15 + 15." |

The toy run (150 steps, LR 1e-4, 16 layers, scale 20) over-fit hard enough to break arithmetic. This tests the pipeline, not quality. The real fine-tune needs a lower learning rate, mixed general data and the evaluation from the plan.

### Conversion is exact

The macOS conversion of the *base* model gives output byte-identical to mlc-ai's official build.

- `compare_mlc_weights.py` reports 435/435 tensors identical to `mlc-ai/Qwen3.5-2B-q4f16_1-MLC`. The shard files and `tensor-cache.json` are identical too.
- The generated `mlc-chat-config.json` matches except for one extra key (`strip_reasoning_in_history: false`), and the tokenizer files are identical.
- The fine-tuned build differs from base in exactly 200 tensors, as expected: 100 LoRA-targeted linear layers × (`q_weight`, `q_scale`).

So the prebuilt wasm `Qwen3.5-2B-q4f16_1_cs1k-webgpu.wasm` (WebLLM v0_2_87 libs) can be reused as is, and no `mlc_llm compile` / emscripten is needed.

## Exact commands

### Environments

These use Python 3.12 via uv, because Homebrew's 3.14 is too new for these wheels.

```bash
mkdir -p ~/waicy-work/{envs,hf_cache,models,logs,certs}
uv venv --python 3.12 ~/waicy-work/envs/mlx
uv pip install --python ~/waicy-work/envs/mlx/bin/python mlx-lm      # mlx-lm 0.32.2, mlx 0.32.4, transformers 5.23
uv venv --python 3.12 ~/waicy-work/envs/mlc
uv pip install --python ~/waicy-work/envs/mlc/bin/python --pre -f https://mlc.ai/wheels \
  mlc-llm-nightly-cpu mlc-ai-nightly-cpu torch                     # mlc-llm 0.26.dev6, mlc-ai 0.26.dev246, tvm-ffi 0.1.16
HF_HOME=~/waicy-work/hf_cache ~/waicy-work/envs/mlx/bin/hf download Qwen/Qwen3.5-2B --local-dir ~/waicy-work/models/Qwen3.5-2B
```

### Fine-tune, merge, check (MLX on the Mac)

```bash
python3 gate1/scripts/make_toy_dataset.py            # -> gate1/data/train.jsonl, valid.jsonl
HF_HOME=~/waicy-work/hf_cache ~/waicy-work/envs/mlx/bin/mlx_lm.lora \
  --model ~/waicy-work/models/Qwen3.5-2B --train --data gate1/data \
  --iters 150 --batch-size 2 --grad-checkpoint --learning-rate 1e-4 --num-layers 16 \
  --max-seq-length 512 --steps-per-report 10 --steps-per-eval 50 --save-every 150 \
  --adapter-path ~/waicy-work/models/adapters/medlabel-toy
# ~1.5 min, ~6 GB peak, ~225 tok/s; val loss 2.51 -> 0.32
~/waicy-work/envs/mlx/bin/python gate1/scripts/merge_mlx_lora.py \
  ~/waicy-work/models/Qwen3.5-2B ~/waicy-work/models/adapters/medlabel-toy \
  ~/waicy-work/models/Qwen3.5-2B-medlabel-toy-hf     # 124 LoRA pairs, 3 s
~/waicy-work/envs/mlx/bin/python gate1/scripts/check_merge.py   # base vs adapter vs merged
```

### Convert for WebLLM

```bash
M=~/waicy-work/models/Qwen3.5-2B-medlabel-toy-hf
OUT=~/waicy-work/models/mlc/Qwen3.5-2B-medlabel-toy-q4f16_1-MLC
PY=~/waicy-work/envs/mlc/bin/python
$PY gate1/scripts/mlc_cli.py convert_weight $M --quantization q4f16_1 --device cpu -o $OUT     # 27 s
$PY gate1/scripts/mlc_cli.py gen_config     $M --quantization q4f16_1 --conv-template qwen2 \
    --prefill-chunk-size 1024 -o $OUT
# optional check against the official build (after converting the base model the same way):
$PY gate1/scripts/compare_mlc_weights.py ~/waicy-work/models/mlc/prebuilt-Qwen3.5-2B-q4f16_1-MLC \
    ~/waicy-work/models/mlc/Qwen3.5-2B-base-q4f16_1-MLC
```

### Serve and test

```bash
# cache the prebuilt library locally (optional; the page can also fetch it from GitHub)
curl -L -o ~/waicy-work/models/libs/Qwen3.5-2B-q4f16_1_cs1k-webgpu.wasm \
  https://raw.githubusercontent.com/mlc-ai/binary-mlc-llm-libs/main/web-llm-models/v0_2_87/base/Qwen3.5-2B-q4f16_1_cs1k-webgpu.wasm
python3 -u gate1/scripts/serve.py --http --host 127.0.0.1 --port 8080   # Mac (localhost is a secure context)
python3 -u gate1/scripts/serve.py --port 8443                            # LAN HTTPS for phones
open -a "Google Chrome" "http://localhost:8080/?models=local-base,local-ft&reload=1"
```

Page URL options:
- `model=hf-prebuilt|local-base|local-ft|lite-base|lite-ft`
- `auto=1`, which runs the selected model
- `models=a,b` with `reload=1`, which loads, benchmarks and reloads each model (warm)
- `prompts=short|long|all` (default `all`)
- `cache=cache|indexeddb|opfs`
- `ctx=N`, which overrides `context_window_size`

Each prompt's result is also sent with `sendBeacon` as it finishes, along with a "stage" breadcrumb before it starts. That way an iOS tab crash still leaves a trace in the log.

The 0.8B model uses the same commands with `Qwen3.5-0.8B` paths (adapter `~/waicy-work/models/adapters/medlabel-toy-0.8b`) and the cached wasm `~/waicy-work/models/libs/Qwen3.5-0.8B-q4f16_1_cs1k-webgpu.wasm`, from the same `v0_2_87/base` URL.

The server maps `/models/<name>/resolve/main/*` to `~/waicy-work/models/mlc/<name>/`, because WebLLM appends `resolve/main/` to the model URL.

### HTTPS for the phone (local CA)

WebGPU needs a secure context, and a plain-HTTP LAN IP is not one. A self-signed leaf certificate that is only clicked through is not enough on iOS, so a small local CA is used:

```bash
cd ~/waicy-work/certs
openssl req -x509 -newkey rsa:2048 -nodes -days 397 -keyout ca.key -out ca.crt \
  -subj "/CN=WAICY Gate1 Local CA" -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign"
openssl req -newkey rsa:2048 -nodes -keyout server.key -out server.csr -subj "/CN=192.168.4.112"
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 397 -out server.crt \
  -extfile <(printf "subjectAltName=IP:192.168.4.112,IP:127.0.0.1,DNS:localhost\nextendedKeyUsage=serverAuth")
```

On the iPhone:
1. Open `https://192.168.4.112:8443/ca.crt` and allow the profile.
2. Install it under Settings > General > VPN & Device Management.
3. Turn on full trust under Settings > General > About > Certificate Trust Settings.
4. Open `https://192.168.4.112:8443/?models=local-ft&reload=1`.

The CA key never leaves `~/waicy-work/certs` and is not in git. For the real app, deployed HTTPS hosting (e.g. GitHub Pages) removes this step.

## macOS workarounds in `mlc_cli.py`

The current nightly wheels (mlc-llm 0.26.dev6 / mlc-ai 0.26.dev246) do not convert Qwen3.5 on macOS out of the box:

1. **RNNState kernels.** TVMScript fails to parse the `seq_id: T.int32 = …` bindings in `RNNState.create_get_func`/`create_set_func`, and printing that error segfaults tvm-ffi. The wrapper swaps in equivalent kernels with the loads inlined.
2. **dtype type.** `nn.Parameter.dtype` is now a `PrimType`, which the loader passes to `numpy.astype`. The wrapper converts it to `str`.
3. **TVM JIT segfaults.** Any compiled function crashes on this Mac, even a trivial add on llvm or metal. The `q4f16_1` quantizer is reimplemented in NumPy with the compiled kernel's exact numerics:
   - `scale = f16(max_abs · f16(1/7))`
   - `q = floor(f16(f32(w)·f32(f16(1/scale)) + 7) + 0.5)`, clipped to [0, 14]
   - all-zero groups map to 0

   This is what makes the output byte-identical to the official build.

## Why a custom merge instead of `mlx_lm.fuse`

MLX-LM's `qwen3_5` loader *sanitizes* weights on load: it renames keys, transposes conv1d and adds +1 to RMSNorm weights. `mlx_lm.fuse` therefore writes MLX-layout weights, not the HF layout that `mlc_llm convert_weight` expects.

`merge_mlx_lora.py` instead patches the original HF safetensors in place of each target. It computes `W' = W + scale · (lora_a @ lora_b)ᵀ` with `scale = lora_parameters.scale` (20.0), mapping `language_model.model.layers.N.*` to `model.language_model.layers.N.*.weight`.

`check_merge.py` confirmed that the merged model generates the same text as base + adapter.

## Phone (iPhone 17e, Safari)

The device is an **iPhone 17e** running Safari 27.0.1; the UA reports "iPhone OS 18_7". It reports WebGPU with `shader-f16`, `maxBufferSize` 1 GB and a storage quota of about 41 GB. Weights came over Wi-Fi from the Mac via LAN HTTPS (local CA).

### 2B: does not fit

- The 1.0 GB fine-tuned weights downloaded and loaded: **84 s cold, 5.8 s from cache.**
- On the first generation, Safari killed the tab ("A problem repeatedly occurred"). A breadcrumb log showed the crash right after the first short prompt was submitted.
- `ctx=1024` (context window 4096 → 1024) crashed at the same point, so the KV cache is not the problem. WebLLM lists ~2.2 GB for the model, plus activation and scratch buffers for generation, and that exceeds what iOS allows a Safari tab here.
- A 1,024-token window would also be too small for real prompts, which are about 1,000 tokens.

### 0.8B lite fine-tune: runs, with limited headroom

**Load:**
- 18.3 s cold (426 MB over LAN Wi-Fi), then 2.6–3.5 s from cache.

**Speed:**
- About 16 tok/s decode. The first run after download was 6.5–9.8 tok/s, presumably shader compilation and warm-up.
- Long-prompt prefill ran at 195 tok/s, so time to first token was **4.9 s** for 963 tokens. On the first run it was 8.6 s.

**What fits, at both ctx 2048 and ctx 4096:**
- Short prompts (27–39 tokens) with answers of up to 78 tokens.
- The 963-token prompt itself: the fine-tune prefilled it, answered and finished cleanly every time.
- Load → bench → unload → reload cycles in one tab.

**What does not fit yet.** The toy fine-tune stopped after 6 tokens on the long prompt. A long prompt followed by a *long answer* has not been shown to fit:
- The base 0.8B (same architecture and memory plan) crashed when it tried to write up to 256 tokens after the same prompt.
- That happened at ctx 2048 (tab reloaded, twice, including in a fresh single-model tab) and at ctx 4096 (`map async was not successful`, GPU device lost about 9 s in, i.e. a few seconds into decoding).
- The context window made no difference, so the extra memory is not the KV cache. We did not narrow down the exact token count (per the coordinator, phone debugging of the base model stopped there).

The real fine-tune will write multi-sentence, cited answers, so treat the phone envelope as **about 1,000 prompt tokens + a short answer** until measured.

### Guards the app should have on phones

1. **Cap the answer length.** Use `max_tokens` of about 128 on phones (256 on laptops) and train the fine-tune to answer briefly: 3–6 bullets with `[n]` citations.
2. **Keep the prompt small.** Send the top ~8–12 retrieved sentences rather than 20, aiming for ≤ 600 prompt tokens on phones. This also cuts the 4.9 s TTFT.
3. **Use `context_window_size: 2048`.** That covers the prompt plus the answer. A larger window didn't help or hurt the crash.
4. **Stream the answer and show the quoted passages first.** If generation dies, the user still has the label text, which is passage-only mode.
5. **Detect crashes.**
   - Set a `sessionStorage` flag before generating and clear it after.
   - If the page reloads with the flag still set, which is how iOS reports the tab crash, switch that device to passage-only mode and say why.
   - Also catch `OperationError` / device-lost errors from WebLLM and fall back the same way.
6. **Tier the model by device.** Use 2B on laptops and desktops, 0.8B on phones, and passage-only if the 0.8B fails. The 2B should never be offered on iPhone.
7. **Retest on the 17e** with the real fine-tune before the showcase, using the guards' settings: ≤ 600-token prompt, `max_tokens` 128, ctx 2048. Use `?models=lite-ft&prompts=long&ctx=2048` once the model and prompt are swapped in.

## Caveats and lessons

- **The embedded WebKit canvas has a 1 GB storage quota per origin.** The ~1 GB model gets evicted right after download, so the warm reload fails with `Cannot fetch …/mlc-chat-config.json`. Chrome (12 GB quota) and iPhone Safari (41 GB) cache it fine. The app should catch this error and show "not enough browser storage".
- **Don't train and run a browser model at the same time.** With the browser holding the model, `batch-size 4` stalled on GPU memory pressure. `batch-size 2 --grad-checkpoint` uses ~6 GB.
- **Hugging Face download speed dominates first load.** The official prebuilt took 325 s over the network, against 3–7 s from the local server. Hosting matters: an HF repo or CDN for the real app, plus a progress bar.
- **WebLLM includes the empty think block in responses.** With `enable_thinking: false`, WebLLM prepends `<think>\n\n</think>\n\n` to the response text, so strip it in the UI. Training rows include the same block so train and inference prompts match.
- **Not uploaded to Hugging Face.** The weights were served locally for this gate. Uploading needs the user's account and approval.

## Next steps for the real fine-tune

- Use the same pipeline with the real label-grounded dataset, a lower learning rate or fewer steps, and mixed general data to avoid the forgetting seen here.
- Run `compare_mlc_weights.py` against base as a sanity check: only the LoRA-targeted tensors should differ.
- Fine-tune the 0.8B lite model on the same data and retest the iPhone 17e under the phone guards above.
- Decide where weights are hosted (HF under the user's account), then point `MODELS[...].url` at it.
