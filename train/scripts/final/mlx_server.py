"""Local MLX generation server for the final evaluation's app-pipeline runs (one model at a time).

    ~/waicy-work/envs/mlx/bin/python train/scripts/final/mlx_server.py --size 2b [--adapter] --port 8765

POST /gen {"user": str, "max_tokens": int, "mode": "label" | "plain"}
  label: the frozen SYSTEM prompt + user message (as the app's llm.ts), thinking off, greedy.
  plain: system A (no label): the question alone, no system prompt, thinking off, greedy.
GET /stats -> {"peak_gb", "calls", "gen_seconds"}
Stands in for WebLLM in Node (the app's generate() callback); the browser models are q4f16 MLC builds,
this is the bf16 MLX model + LoRA, the same as the Gate 2 harness.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

os.environ.setdefault("HF_HOME", os.path.expanduser("~/waicy-work/hf_cache"))

import mlx.core as mx  # noqa: E402
from mlx_lm import load  # noqa: E402
from mlx_lm.generate import generate_step  # noqa: E402

from common import ADAPTER, BASE  # noqa: E402
from medlabel_data.fdarx.build import SYSTEM  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--size", choices=["2b", "08"], required=True)
ap.add_argument("--adapter", action="store_true")
ap.add_argument("--port", type=int, default=8765)
a = ap.parse_args()
model, tok = load(str(BASE[a.size]), adapter_path=str(ADAPTER[a.size]) if a.adapter else None)
eos = set(tok.eos_token_ids) if hasattr(tok, "eos_token_ids") else {tok.eos_token_id}
stats = {"calls": 0, "gen_seconds": 0.0, "tokens_out": 0}


def gen(user: str, max_tokens: int, mode: str) -> tuple[str, int, int]:
    msgs = [{"role": "user", "content": user}]
    if mode == "label":
        msgs.insert(0, {"role": "system", "content": SYSTEM})
    text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    ids = tok.encode(text, add_special_tokens=False)
    out = []
    for t, _ in generate_step(mx.array(ids), model, max_tokens=max_tokens):
        t = int(t)
        if t in eos:
            break
        out.append(t)
    return tok.decode(out), len(ids), len(out)


class H(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        self._send({**stats, "peak_gb": round(mx.get_peak_memory() / 1e9, 2), "size": a.size, "adapter": a.adapter})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        t0 = time.time()
        reply, n_in, n_out = gen(body["user"], int(body.get("max_tokens", 256)), body.get("mode", "label"))
        dt = time.time() - t0
        stats["calls"] += 1
        stats["gen_seconds"] += dt
        stats["tokens_out"] += n_out
        self._send({"reply": reply, "prompt_tokens": n_in, "tokens_out": n_out, "seconds": round(dt, 3)})


print(f"ready {a.size} adapter={a.adapter} port={a.port}", flush=True)
HTTPServer(("127.0.0.1", a.port), H).serve_forever()
