"""Dev retrieval recall for the hybrid retriever (BM25 + embeddings).

    python train/scripts/retrieval_eval.py            # grid, writes ~/waicy-work/retrieval/grid_dev.json

For each dev answerable item the gold sentences come from fdarx/aligned.jsonl. Reported:
  sent_recall   share of gold sentences that end up in the prompt
  all_gold      share of items whose prompt holds every gold sentence
  any_gold      share of items whose prompt holds at least one gold sentence
  pass_top{1,3,5}  share of items with a gold passage among the top-k passages (by best sentence)
"""

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "datapipe" / "src"))
from medlabel_data import paths, retrieval as R  # noqa: E402
from medlabel_data.fdarx.align import OUT as ALIGNED, Label  # noqa: E402
from medlabel_data.text import content_tokens  # noqa: E402

RDIR = Path("~/waicy-work/retrieval").expanduser()
META = paths.BUILD / "fdarx" / "mlx_plain" / "valid_meta.jsonl"


def load_dev():
    items = [json.loads(l) for l in open(META)]
    qids = {x["qid"] for x in items}
    gold = {}
    for line in open(ALIGNED):
        r = json.loads(line)
        if r["qid"] in qids and r.get("split") == "dev":
            gold[r["qid"]] = [tuple(x) for x in r["sentences"]]
    sids = {x["set_id"] for x in items}
    labs = {}
    for line in open(paths.FDARX_LABELS):
        r = json.loads(line)
        if r["set_id"] in sids:
            labs[r["set_id"]] = Label(r)
    return items, gold, labs


def sims_for(emb, sid, qid):
    if emb is None:
        return None
    return (emb[f"units_{sid}"].astype(np.float32) @ emb[f"q_{qid}"].astype(np.float32)).tolist()


def evaluate(items, gold, idx, embs, params, model):
    rows = []
    for x in items:
        if x["kind"] != "answerable":
            continue
        ix = idx[x["set_id"]]
        sims = sims_for(embs.get(model), x["set_id"], x["qid"])
        sc = R.scores(ix, x["question"], sims, params)
        blocks = R.select(ix, sc, params)
        shown = {(c, s) for c, ids in blocks for s in ids}
        g = set(gold[x["qid"]])
        best = {}
        for (c, _), v in zip(ix.units, sc):
            best[c] = max(best.get(c, -1), v)
        prank = sorted(best, key=lambda c: (-best[c], c))
        gc = {c for c, _ in g}
        rows.append({"rec": len(g & shown) / len(g), "all": g <= shown, "any": bool(g & shown),
                     **{f"p{k}": bool(gc & set(prank[:k])) for k in (1, 3, 5)},
                     "chars": sum(len(ix.passages[c][1][s]) for c, s in shown)})
    m = lambda k: round(float(np.mean([r[k] for r in rows])), 4)  # noqa: E731
    return {"sent_recall": m("rec"), "all_gold": m("all"), "any_gold": m("any"), "pass_top1": m("p1"),
            "pass_top3": m("p3"), "pass_top5": m("p5"), "chars_mean": m("chars"), "n": len(rows)}


def main():
    items, gold, labs = load_dev()
    idx = {sid: R.LabelIndex(lab.passages) for sid, lab in labs.items()}
    embs = {m: dict(np.load(RDIR / f"emb_{m}_dev.npz")) for m in ("minilm", "bge", "arctic")
            if (RDIR / f"emb_{m}_dev.npz").exists()}
    grid = []
    weights = [("bm25_sent", 1, 0, 0), ("bm25_both", .7, .3, 0), ("emb", 0, 0, 1), ("hyb", .4, .2, .4),
               ("hyb_emb", .25, .15, .6), ("hyb_kw", .5, .2, .3)]
    for budget in (1500, 3000):
        for context in (0, 1):
            for model in [None, *embs]:
                for name, ws, wp, we in weights:
                    if (model is None) != (we == 0):
                        continue
                    p = {**R.DEFAULTS, "w_sent": ws, "w_pass": wp, "w_emb": we, "context": context,
                         "budget": budget, "max_seeds": 12 if budget <= 1500 else 40}
                    r = evaluate(items, gold, idx, embs, p, model)
                    grid.append({"model": model, "weights": name, **{k: p[k] for k in ("budget", "context", "max_seeds", "w_sent", "w_pass", "w_emb")}, **r})
                    print(json.dumps(grid[-1]), flush=True)
    (RDIR / "grid_dev.json").write_text(json.dumps(grid, indent=1))


if __name__ == "__main__":
    main()
