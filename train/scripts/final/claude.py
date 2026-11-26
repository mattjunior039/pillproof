"""Claude Sonnet 5.5 for the final evaluation: system E (no label) and the AI grader, one cache and one budget.

    datapipe/.venv/bin/python train/scripts/final/claude.py e        # E on T3, T6, T2 and the T1 500 sample
Spend is the sum over final/claude/cache.jsonl (Batch API, half price) and is capped at BUDGET for E and
grading together. The API key is read from ~/waicy-work/.env and never printed.
"""
from __future__ import annotations

import hashlib
import json
import sys
import threading
import time

from common import FINAL, env_key, jl, wjl

MODEL = "claude-sonnet-5-5"
PRICE_IN, PRICE_OUT = 2.0, 10.0  # USD per million tokens, list price; the Batch API bills half
BUDGET = 26.44  # E + grader together (coordinator: $15, then $25 total; v1.1: stop at about $12 more than the $14.44 spent)
OUT = FINAL / "claude"
CACHE = OUT / "cache.jsonl"


def cost(recs) -> float:
    return sum((r["in"] * PRICE_IN + r["out"] * PRICE_OUT) / 1e6 * (0.5 if r.get("batch") else 1.0) for r in recs)


class Client:
    def __init__(self):
        import anthropic
        self.api = anthropic.Anthropic(api_key=env_key("ANTHROPIC_API_KEY"), max_retries=8)
        self.lock = threading.Lock()
        self.cache: dict[str, dict] = {}
        OUT.mkdir(parents=True, exist_ok=True)
        if CACHE.exists():
            for r in jl(CACHE):
                self.cache[r["key"]] = r

    @staticmethod
    def key(system: str | None, prompt: str, max_tokens: int) -> str:
        return hashlib.sha256(f"{MODEL}|{max_tokens}|{system or ''}|{prompt}".encode()).hexdigest()

    def get(self, system, prompt, max_tokens) -> dict | None:
        return self.cache.get(self.key(system, prompt, max_tokens))

    def spent(self) -> float:
        return cost(self.cache.values())

    def _store(self, rec: dict):
        with self.lock:
            self.cache[rec["key"]] = rec
            with open(CACHE, "a") as f:
                f.write(json.dumps(rec) + "\n")

    def batch(self, items: list[tuple[str | None, str, int]], tag: str, out_per_item: int = 150) -> None:
        """Send uncached (system, prompt, max_tokens) through the Message Batches API, wait, cache.
        Each prompt is sent once; a failed request is reported, not silently retried with other settings."""
        todo = {}
        for system, p, mt in items:
            k = self.key(system, p, mt)
            if k not in self.cache:
                todo[k] = (system, p, mt)
        spent = self.spent()
        if not todo:
            print(f"[{tag}] nothing to send; spent so far ${spent:.2f}")
            return
        est = sum(len(s or "") + len(p) for s, p, _ in todo.values()) / 3.5 * PRICE_IN / 2e6 \
            + len(todo) * out_per_item * PRICE_OUT / 2e6
        print(f"[{tag}] {len(todo)} prompts, estimated ${est:.2f} at batch price; spent so far ${spent:.2f}", flush=True)
        if spent + est > BUDGET:
            raise SystemExit(f"Estimate exceeds the ${BUDGET:.0f} budget; nothing sent.")
        ids, reqs = {}, []
        for i, (k, (system, p, mt)) in enumerate(todo.items()):
            ids[f"r{i}"] = k
            params = {"model": MODEL, "max_tokens": mt, "messages": [{"role": "user", "content": p}]}
            if system:
                params["system"] = system
            reqs.append({"custom_id": f"r{i}", "params": params})
        b = self.api.messages.batches.create(requests=reqs)
        print(f"[{tag}] batch {b.id}", flush=True)
        with open(OUT / "batch_ids.txt", "a") as f:
            f.write(f"{tag} {b.id}\n")
        while (b := self.api.messages.batches.retrieve(b.id)).processing_status != "ended":
            c = b.request_counts
            print(f"  {time.strftime('%H:%M:%S')} processing={c.processing} succeeded={c.succeeded} errored={c.errored}", flush=True)
            time.sleep(30)
        bad = 0
        for r in self.api.messages.batches.results(b.id):
            if r.result.type != "succeeded":
                bad += 1
                continue
            msg = r.result.message
            out = "".join(x.text for x in msg.content if x.type == "text").strip()
            self._store({"key": ids[r.custom_id], "text": out, "in": msg.usage.input_tokens,
                         "out": msg.usage.output_tokens, "batch": True, "stop": msg.stop_reason})
        print(f"[{tag}] batch done; {bad} failed; spent ${self.spent():.2f}", flush=True)


E_MAX = 1024
SETS = {"t3": FINAL / "t3/items_app.jsonl", "t6": FINAL / "t6/items_app.jsonl",
        "t2": FINAL / "t2/items_app.jsonl", "t1s": FINAL / "t1/sample500.jsonl"}


def run_e():
    """System E: the question alone, as typed into a chatbot (no system prompt, no label, no tools/web)."""
    c = Client()
    allitems = {s: jl(p) for s, p in SETS.items()}
    c.batch([(None, it["question"], E_MAX) for s in SETS for it in allitems[s]], "E", out_per_item=450)
    (FINAL / "app").mkdir(exist_ok=True)
    for s, items in allitems.items():
        rows = []
        for it in items:
            r = c.get(None, it["question"], E_MAX)
            rows.append({"id": it["id"], "reply": r["text"] if r else None, "in": r and r["in"], "out": r and r["out"],
                         "stop": r and r.get("stop")})
        wjl(FINAL / "app" / f"{s}_E.jsonl", rows)
        print(s, len(rows), "missing", sum(r["reply"] is None for r in rows))


if __name__ == "__main__":
    if sys.argv[1:] == ["e"]:
        run_e()
    elif sys.argv[1:] == ["spent"]:
        print(f"${Client().spent():.2f}")
