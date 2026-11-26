"""T1 (FDARxBench held-out test) preparation for the final evaluation.

    ~/waicy-work/envs/mlx/bin/python train/scripts/final/t1_prep.py embed      # -> ~/waicy-work/retrieval/emb_bge_test.npz
    ~/waicy-work/envs/mlx/bin/python train/scripts/final/t1_prep.py prompts    # -> final/t1/prompts_{oracle,phone,desktop}.jsonl
    ~/waicy-work/envs/mlx/bin/python train/scripts/final/t1_prep.py retrieval  # -> final/t1/retrieval.json

Same construction as Gate 2's eval_dev.build_prompts (dev), applied once to the test split.
FDARxBench's own refusal items (kind fdarx_refusal: the benchmark says the label lacks the answer)
are kept as a separate subset with expect=decline; they have no gold sentences.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

from common import FINAL, wjl  # noqa: F401  (sets sys.path)
from medlabel_data import paths, retrieval as R
from medlabel_data.fdarx.align import OUT as ALIGNED, Label, align_answer, answer_tokens
from medlabel_data.fdarx.build import DECLINE_MAX_COVER
from medlabel_data.text import content_tokens

RDIR = Path("~/waicy-work/retrieval").expanduser()
META = paths.BUILD / "fdarx" / "mlx_plain" / "test_meta.jsonl"
OUT = FINAL / "t1"


def load():
    items = [json.loads(l) for l in open(META)]
    qids = {x["qid"] for x in items}
    recs = {}
    for line in open(ALIGNED):
        r = json.loads(line)
        if r.get("split") == "test" and r["qid"] in qids:
            recs[r["qid"]] = r
    sids = {x["set_id"] for x in items}
    labs = {}
    for line in open(paths.FDARX_LABELS):
        r = json.loads(line)
        if r["set_id"] in sids:
            labs[r["set_id"]] = Label(r)
    return items, recs, labs


def embed():
    from embed import Embedder, unit_texts

    items, _, labs = load()
    emb = Embedder("bge")
    t0, arrays = time.time(), {}
    for sid, lab in labs.items():
        arrays[f"units_{sid}"] = emb(unit_texts(lab)).astype(np.float16)
    qs = {x["qid"]: x["question"] for x in items}
    for qid, v in zip(qs, emb([emb.qpfx + q for q in qs.values()])):
        arrays[f"q_{qid}"] = v.astype(np.float16)
    np.savez(RDIR / "emb_bge_test.npz", **arrays)
    print(f"bge test: {len(labs)} labels, {len(qs)} questions, {time.time() - t0:.0f}s")


def prompts():
    items, recs, labs = load()
    idx = {s: R.LabelIndex(l.passages) for s, l in labs.items()}
    emb = dict(np.load(RDIR / "emb_bge_test.npz"))
    out = {"oracle": [], "phone": [], "desktop": []}
    dropped = {"phone": 0, "desktop": 0}
    missing = 0
    for x in items:
        lab = labs[x["set_id"]]
        refusal = x["kind"] == "fdarx_refusal"
        rec = recs.get(x["qid"])
        if rec is None and not refusal:
            missing += 1
            continue
        excuse = set(content_tokens(x["drug_name"] or "")) | set(content_tokens(lab.drug_name))
        if refusal:
            ans, gold, target, cov0 = set(), [], "", None
        else:
            target = rec["target"]
            ans = answer_tokens(target, rec["question"], excuse)
            gold = [tuple(g) for g in rec["sentences"]]
            cov0 = rec["coverage"]
        base = {"qid": x["qid"], "kind": x["kind"], "set_id": x["set_id"], "drug": x["drug_name"],
                "question": x["question"], "target": target, "ans_tokens": sorted(ans), "gold_cov": cov0,
                "gold_texts": [lab.passages[c][1][s] for c, s in gold], "tier": x["tier"], "task": x["task"],
                "reference_answer": x.get("reference_answer")}
        out["oracle"].append({**base, "user": x["messages"][1]["content"],
                              "gold_nums": x.get("answer_sentences") or [],
                              "expect": "decline" if refusal else x["kind"], "prompt_cov": None})
        sims = (emb[f"units_{x['set_id']}"].astype(np.float32) @ emb[f"q_{x['qid']}"].astype(np.float32)).tolist()
        exclude = set(x.get("removed") or []) if x["kind"] == "decline" else set()
        for cond, params in (("phone", R.PHONE), ("desktop", R.DESKTOP)):
            user, numbering, blocks = R.retrieve(idx[x["set_id"]], x["drug_name"], x["question"], sims, params, exclude)
            shown = [(c, s) for c, ids in blocks for s in ids]
            if refusal:
                cov, expect = None, "decline"
            else:
                cov = align_answer(target, shown, lab, ans)[1] if shown else 0.0
                if x["kind"] == "decline":
                    if cov >= DECLINE_MAX_COVER:
                        dropped[cond] += 1
                        continue
                    expect = "decline"
                else:
                    expect = "answerable" if cov >= DECLINE_MAX_COVER else "miss"
            out[cond].append({**base, "user": user, "gold_nums": sorted(numbering[g] for g in gold if g in numbering),
                              "expect": expect, "prompt_cov": None if cov is None else round(cov, 3)})
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {"missing_aligned": missing, "dropped_declines": dropped}
    for cond, rows in out.items():
        wjl(OUT / f"prompts_{cond}.jsonl", rows)
        summary[cond] = {"n": len(rows), **{k: sum(r["expect"] == k for r in rows if r["kind"] != "fdarx_refusal")
                                            for k in ("answerable", "miss", "decline")},
                         "fdarx_refusal": sum(r["kind"] == "fdarx_refusal" for r in rows)}
    (OUT / "prompts_summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


def retrieval():
    import retrieval_eval as RE

    items, recs, labs = load()
    gold = {q: [tuple(g) for g in r["sentences"]] for q, r in recs.items()}
    idx = {s: R.LabelIndex(l.passages) for s, l in labs.items()}
    embs = {"bge": dict(np.load(RDIR / "emb_bge_test.npz"))}
    ans = [x for x in items if x["kind"] == "answerable" and x["qid"] in gold]
    rows = []
    for name, preset in (("PHONE", R.PHONE), ("DESKTOP", R.DESKTOP)):
        for method, model, ws, wp, we in (("BM25 only", None, .7, .3, 0), ("bge only", "bge", 0, 0, 1),
                                          ("hybrid (shipped)", "bge", preset["w_sent"], preset["w_pass"], preset["w_emb"])):
            p = {**preset, "w_sent": ws, "w_pass": wp, "w_emb": we}
            rows.append({"preset": name, "method": method, **RE.evaluate(ans, gold, idx, embs, p, model)})
            print(json.dumps(rows[-1]), flush=True)
    (OUT / "retrieval.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    {"embed": embed, "prompts": prompts, "retrieval": retrieval}[sys.argv[1]]()
