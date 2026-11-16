# Gate 1: fine-tuned weights answer in the browser

**Result: passed on the Mac (Nov 15, 2026).** A LoRA fine-tune of Qwen3.5-2B, merged and converted with MLC, loads in WebLLM. It runs with the stock prebuilt Qwen3.5-2B WebGPU library and answers with the fine-tuned persona in Chrome and Safari/WebKit. The base model answers as Qwen.

**Phone: not yet working.** On the iPhone the 2B model loads, but the Safari tab is killed (out of memory) on the first generation. See [Phone](#phone-iphone-safari).

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
| `gate1/web/index.html`, `app.js` | Test page: load, benchmark and chat, plus an auto mode |

## Results

All runs used greedy decoding (temperature 0), `enable_thinking: false` and max 128 tokens. There were four short prompts of about 30 tokens each. Load time runs from `CreateMLCEngine` start to ready. "Cold" means weights downloaded from the local server; "warm" means read from the browser cache. The full records are in `~/waicy-work/logs/gate1-results.jsonl`.

| Browser (device) | Model | Cold load | Warm load | Decode tok/s | Prefill tok/s |
|---|---|---|---|---|---|
| Chrome 157 (M5 Pro, 24 GB) | base, local q4f16_1 | 3.8 s | 1.0 s | 58.0 (63 after the first prompt) | 436 |
| Chrome 157 (M5 Pro) | **fine-tuned** | 3.4 s | 1.0 s | **61.5** | 483 |
| WebKit / Safari 27 in-app canvas (M5 Pro) | **fine-tuned** | 7.4 s | failed (1 GB quota, see caveats) | 36.0 | 233 |
| WebKit canvas (M5 Pro) | official prebuilt from Hugging Face | 325 s (network bound) | n/a | 12.9* | 96* |
| iPhone Safari (iOS 26+) over LAN HTTPS | **fine-tuned** | 84 s | 5.8 s | tab crashed | tab crashed |

\* Measured while LoRA training ran at the same time, so not a fair number.

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
- `model=hf-prebuilt|local-base|local-ft`
- `auto=1`, which runs the selected model
- `models=a,b` with `reload=1`, which loads, benchmarks and reloads each model (warm)
- `cache=cache|indexeddb|opfs`
- `ctx=N`, which overrides `context_window_size`

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

## Phone (iPhone Safari)

- The phone reports WebGPU with `shader-f16`, `maxBufferSize` 1 GB and a storage quota of about 41 GB.
- The 1.0 GB fine-tuned weights downloaded over Wi-Fi and loaded: **84 s cold, 5.8 s from cache.**
- On the first generation, Safari killed the tab ("A problem repeatedly occurred"). A breadcrumb log showed the crash right after the first prompt was submitted.
- With `ctx=1024` (context window 4096 → 1024) the load took 7–8 s cached, then the same crash at the same point. So the problem is not the KV cache. It is the total GPU and process memory of the 2B model: WebLLM lists ~2.2 GB, and generation adds activation and scratch buffers for the 1024-token prefill chunk. That is above what iOS lets a Safari tab use on this phone.
- A 1,024-token window is probably too small for real prompts anyway. The app's prompts carry the question plus numbered label sentences.

Options for phones, in the plan's terms:
1. **Qwen3.5-0.8B "lite" tier.** It is a 0.45 GB download and WebLLM lists about 1.6 GB of memory. Fine-tune and convert it with the same pipeline, then test on the iPhone first.
2. **Passage-only mode.** Retrieval plus quote display with no on-device generation. It is already the fallback in the plan, and it works on any phone.
3. The 2B model stays the laptop tier.

## Caveats and lessons

- **The embedded WebKit canvas has a 1 GB storage quota per origin.** The ~1 GB model gets evicted right after download, so the warm reload fails with `Cannot fetch …/mlc-chat-config.json`. Chrome (12 GB quota) and iPhone Safari (41 GB) cache it fine. The app should catch this error and show "not enough browser storage".
- **Don't train and run a browser model at the same time.** With the browser holding the model, `batch-size 4` stalled on GPU memory pressure. `batch-size 2 --grad-checkpoint` uses ~6 GB.
- **Hugging Face download speed dominates first load.** The official prebuilt took 325 s over the network, against 3–7 s from the local server. Hosting matters: an HF repo or CDN for the real app, plus a progress bar.
- **WebLLM includes the empty think block in responses.** With `enable_thinking: false`, WebLLM prepends `<think>\n\n</think>\n\n` to the response text, so strip it in the UI. Training rows include the same block so train and inference prompts match.
- **Not uploaded to Hugging Face.** The weights were served locally for this gate. Uploading needs the user's account and approval.

## Next steps for the real fine-tune

- Use the same pipeline with the real label-grounded dataset, a lower learning rate or fewer steps, and mixed general data to avoid the forgetting seen here.
- Run `compare_mlc_weights.py` against base as a sanity check: only the LoRA-targeted tensors should differ.
- Build the 0.8B lite model and retest the iPhone.
- Decide where weights are hosted (HF under the user's account), then point `MODELS[...].url` at it.
