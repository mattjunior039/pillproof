"""Dev-set generation for Gate 2 (systems B and C, both sizes).

    # build the prompt sets once (oracle = the built dev prompts; phone/desktop = hybrid retrieval)
    python train/scripts/eval_dev.py prompts
    # generate (greedy, thinking off, max 256 new tokens; run_gate2.sh passes --max-tokens 256)
    python train/scripts/eval_dev.py run --model Qwen/Qwen3.5-0.8B --prompts phone --out ~/waicy-work/eval/B08_phone.jsonl
    python train/scripts/eval_dev.py run --model Qwen/Qwen3.5-0.8B --adapter ~/waicy-work/models/adapters/medlabel-08-r1 ...

Only the dev split (valid_meta.jsonl) is read. Grading is in grade_dev.py.

Retrieved prompts: answerable items retrieve over the whole label. Decline items retrieve over
the label minus the passages build.py removed for that item ("removed"), and are dropped when
the remaining shown sentences still cover >= 50% of the answer (same rule as build.py).
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "datapipe" / "src"))
from medlabel_data import paths, retrieval as R  # noqa: E402
from medlabel_data.fdarx.align import OUT as ALIGNED, Label, align_answer, answer_tokens  # noqa: E402
from medlabel_data.fdarx.build import DECLINE_MAX_COVER, SYSTEM  # noqa: E402
from medlabel_data.text import content_tokens  # noqa: E402

EVAL = Path(os.environ.get("EVAL_DIR", "~/waicy-work/eval")).expanduser()  # EVAL_DIR=~/waicy-work/eval_r2 for r2
RDIR = Path("~/waicy-work/retrieval").expanduser()
META = paths.BUILD / "fdarx" / "mlx_plain" / "valid_meta.jsonl"
EMB_MODEL = "bge"


def build_prompts() -> None:
    import numpy as np

    items = [json.loads(l) for l in open(META)]
    qids = {x["qid"] for x in items}
    recs = {}
    for line in open(ALIGNED):
        r = json.loads(line)
        if r.get("split") == "dev" and r["qid"] in qids:
            recs[r["qid"]] = r
    sids = {x["set_id"] for x in items}
    labs = {}
    for line in open(paths.FDARX_LABELS):
        r = json.loads(line)
        if r["set_id"] in sids:
            labs[r["set_id"]] = Label(r)
    idx = {s: R.LabelIndex(l.passages) for s, l in labs.items()}
    emb = dict(np.load(RDIR / f"emb_{EMB_MODEL}_dev.npz"))
    EVAL.mkdir(parents=True, exist_ok=True)
    out = {"oracle": [], "phone": [], "desktop": []}
    dropped = {"phone": 0, "desktop": 0}
    for x in items:
        rec, lab = recs[x["qid"]], labs[x["set_id"]]
        excuse = set(content_tokens(x["drug_name"] or "")) | set(content_tokens(lab.drug_name))
        ans = answer_tokens(rec["target"], rec["question"], excuse)
        gold = [tuple(g) for g in rec["sentences"]]
        base = {"qid": x["qid"], "kind": x["kind"], "set_id": x["set_id"], "drug": x["drug_name"],
                "question": x["question"], "target": rec["target"], "ans_tokens": sorted(ans),
                "gold_cov": rec["coverage"], "gold_texts": [lab.passages[c][1][s] for c, s in gold],
                "tier": x["tier"], "task": x["task"]}
        out["oracle"].append({**base, "user": x["messages"][1]["content"],
                              "gold_nums": x.get("answer_sentences") or [], "expect": x["kind"], "prompt_cov": None})
        sims = (emb[f"units_{x['set_id']}"].astype(np.float32) @ emb[f"q_{x['qid']}"].astype(np.float32)).tolist()
        exclude = set(x.get("removed") or []) if x["kind"] == "decline" else set()
        for cond, params in (("phone", R.PHONE), ("desktop", R.DESKTOP)):
            user, numbering, blocks = R.retrieve(idx[x["set_id"]], x["drug_name"], x["question"], sims, params, exclude)
            shown = [(c, s) for c, ids in blocks for s in ids]
            cov = align_answer(rec["target"], shown, lab, ans)[1] if shown else 0.0
            if x["kind"] == "decline":
                if cov >= DECLINE_MAX_COVER:
                    dropped[cond] += 1
                    continue
                expect = "decline"
            else:
                expect = "answerable" if cov >= DECLINE_MAX_COVER else "miss"
            out[cond].append({**base, "user": user, "gold_nums": sorted(numbering[g] for g in gold if g in numbering),
                              "expect": expect, "prompt_cov": round(cov, 3)})
    for cond, rows in out.items():
        with open(EVAL / f"prompts_{cond}.jsonl", "w") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        kinds = {k: sum(r["expect"] == k for r in rows) for k in ("answerable", "miss", "decline")}
        print(cond, len(rows), kinds, "dropped declines:", dropped.get(cond, 0))


def run(a) -> None:
    import mlx.core as mx
    from mlx_lm import batch_generate, load

    if a.cpu:
        mx.set_default_device(mx.cpu)
    rows = [json.loads(l) for l in open(EVAL / f"prompts_{a.prompts}.jsonl")]
    if a.limit:
        rows = rows[:: max(1, len(rows) // a.limit)][: a.limit]
    model, tok = load(a.model, adapter_path=a.adapter)
    enc = []
    for r in rows:
        text = tok.apply_chat_template([{"role": "system", "content": SYSTEM}, {"role": "user", "content": r["user"]}],
                                       tokenize=False, add_generation_prompt=True, enable_thinking=False)
        enc.append(tok.encode(text, add_special_tokens=False))
    order = sorted(range(len(rows)), key=lambda i: len(enc[i]))
    out_path = Path(a.out).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    replies: dict[int, str] = {}
    for b in range(0, len(order), a.batch):
        ids = order[b:b + a.batch]
        res = batch_generate(model, tok, [enc[i] for i in ids], max_tokens=a.max_tokens)
        for i, t in zip(ids, res.texts):
            replies[i] = t
        done = b + len(ids)
        if done % (a.batch * 10) < a.batch or done == len(order):
            el = time.time() - t0
            print(f"{done}/{len(order)} {el:.0f}s ({el / done:.2f}s/item)", flush=True)
    with open(out_path, "w") as f:
        for i, r in enumerate(rows):
            f.write(json.dumps({"qid": r["qid"], "kind": r["kind"], "prompt_tokens": len(enc[i]),
                                "reply": replies[i]}, ensure_ascii=False) + "\n")
    meta = {"model": a.model, "adapter": a.adapter, "prompts": a.prompts, "n": len(rows),
            "seconds": round(time.time() - t0, 1), "max_tokens": a.max_tokens, "batch": a.batch,
            "peak_gb": round(mx.get_peak_memory() / 1e9, 2)}
    out_path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta))


def web_export(a) -> None:
    """Write the same dev subset as `run --limit` for the browser page (gate1 ?prompts=dev)."""
    rows = [json.loads(l) for l in open(EVAL / f"prompts_{a.prompts}.jsonl")]
    if a.limit:
        rows = rows[:: max(1, len(rows) // a.limit)][: a.limit]
    out = EVAL / "web" / f"dev_{a.prompts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([{"qid": r["qid"], "kind": r["kind"], "system": SYSTEM, "user": r["user"]} for r in rows]))
    print(out, len(rows))


def web_import(a) -> None:
    """Turn browser rows logged by the gate1 page into a run file that grade_dev.py reads."""
    log = Path.home() / "waicy-work" / "logs" / "gate1-results.jsonl"
    rows = [r for r in map(json.loads, open(log)) if r.get("kind") == "row" and r.get("model") == a.model
            and r.get("qid") and r.get("_server_time", "") >= a.since]
    got = {}
    for r in rows:  # last reply wins if the page was run more than once
        got[(r["qid"], r["dev_kind"])] = r
    out = Path(a.out).expanduser()
    with open(out, "w") as f:
        for (qid, kind), r in got.items():
            reply = re.sub(r"^<think>\s*</think>\s*", "", r["text"])
            f.write(json.dumps({"qid": qid, "kind": kind, "prompt_tokens": r["usage"]["prompt_tokens"], "reply": reply}) + "\n")
    dec = [r["usage"]["extra"]["decode_tokens_per_s"] for r in got.values()]
    meta = {"model": f"webllm:{a.model}", "adapter": None, "prompts": a.prompts, "n": len(got),
            "seconds": round(sum(r["wall_s"] for r in got.values()), 1), "max_tokens": 256,
            "ua": rows[-1]["ua"] if rows else None, "mean_decode_tps": round(sum(dec) / max(1, len(dec)), 1)}
    out.with_suffix(".meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prompts")
    r = sub.add_parser("run")
    r.add_argument("--model", required=True)
    r.add_argument("--adapter")
    r.add_argument("--prompts", choices=["oracle", "phone", "desktop"], required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--limit", type=int)
    r.add_argument("--batch", type=int, default=16)
    r.add_argument("--max-tokens", type=int, default=256)
    r.add_argument("--cpu", action="store_true")
    w = sub.add_parser("web-export")
    w.add_argument("--prompts", choices=["oracle", "phone", "desktop"], default="phone")
    w.add_argument("--limit", type=int, default=100)
    w = sub.add_parser("web-import")
    w.add_argument("--model", required=True, help="gate1 page model key, e.g. r1-ft")
    w.add_argument("--prompts", choices=["oracle", "phone", "desktop"], default="phone")
    w.add_argument("--since", default="", help="only rows logged at or after this server time")
    w.add_argument("--out", required=True)
    a = ap.parse_args()
    {"prompts": lambda a: build_prompts(), "run": run, "web-export": web_export, "web-import": web_import}[a.cmd](a)


if __name__ == "__main__":
    main()
