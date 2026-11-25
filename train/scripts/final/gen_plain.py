"""System A (base model, no label) through mlx_server.py in plain mode, and the T1 500-item sample.

    python3 train/scripts/final/gen_plain.py sample                       # -> final/t1/sample500.jsonl
    python3 train/scripts/final/gen_plain.py run --set t3 --out final/app/t3_A2b.jsonl [--url ...]
Sets: t3, t2, t6 (items_app.jsonl) and t1s (sample500.jsonl). The question is sent alone, with no system
prompt and no label (as a user would type it into a chatbot); thinking off, greedy, 256 new tokens.
"""
import argparse
import json
import random
import time
import urllib.request
from collections import defaultdict

from common import FINAL, jl, wjl

SETS = {"t3": FINAL / "t3/items_app.jsonl", "t2": FINAL / "t2/items_app.jsonl",
        "t6": FINAL / "t6/items_app.jsonl", "t1s": FINAL / "t1/sample500.jsonl"}


def sample():
    """500 answerable T1 test questions, stratified by drug: every drug gets floor(500/91) or one more."""
    rows = [r for r in jl(FINAL / "t1/prompts_oracle.jsonl") if r["kind"] == "answerable"]
    by = defaultdict(list)
    for r in rows:
        by[r["set_id"]].append(r)
    rng = random.Random(20261125)
    drugs = sorted(by)
    for d in drugs:
        rng.shuffle(by[d])
    out, i = [], 0
    while len(out) < 500:
        d = drugs[i % len(drugs)]
        k = i // len(drugs)
        if k < len(by[d]):
            out.append(by[d][k])
        i += 1
    wjl(FINAL / "t1/sample500.jsonl", [{"id": r["qid"], "question": r["question"], "drug": r["drug"], "set_id": r["set_id"],
                                       "reference_answer": r["reference_answer"], "gold_texts": r["gold_texts"]} for r in out])
    print(len(out), "items,", len({r["set_id"] for r in out}), "drugs")


def run(a):
    items = jl(SETS[a.set])
    out = FINAL / a.out  # an absolute a.out replaces FINAL
    done = {r["id"] for r in jl(out)} if out.exists() else set()
    t0, n = time.time(), 0
    with open(out, "a") as f:
        for it in items:
            if it["id"] in done:
                continue
            req = urllib.request.Request(a.url + "/gen", data=json.dumps(
                {"user": it["question"], "max_tokens": 256, "mode": "plain"}).encode(), headers={"Content-Type": "application/json"})
            j = json.loads(urllib.request.urlopen(req, timeout=600).read())
            f.write(json.dumps({"id": it["id"], "reply": j["reply"], "prompt_tokens": j["prompt_tokens"],
                                "tokens_out": j["tokens_out"], "seconds": j["seconds"]}) + "\n")
            n += 1
            if n % 50 == 0:
                print(f"{n}/{len(items) - len(done)} {time.time() - t0:.0f}s", flush=True)
    print(f"{a.set} -> {out}: {n} new in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("sample")
    r = sp.add_parser("run")
    r.add_argument("--set", required=True, choices=list(SETS))
    r.add_argument("--out", required=True)
    r.add_argument("--url", default="http://127.0.0.1:8765")
    a = ap.parse_args()
    sample() if a.cmd == "sample" else run(a)
