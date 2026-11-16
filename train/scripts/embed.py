"""Sentence embeddings with the ONNX files transformers.js uses (so the browser matches).

    python train/scripts/embed.py --model minilm --split dev

Embeds every sentence of the labels in a split (text: "<heading>: <sentence>") and every
question, and writes ~/waicy-work/retrieval/emb_<model>_<split>.npz with
  units_<set_id>  float16 [n_units, d]   (order of retrieval.LabelIndex.units)
  q_<qid>         float16 [d]
Only labels of the requested split are read; the test split is refused.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_HOME", str(Path("~/waicy-work/hf_cache").expanduser()))

import numpy as np  # noqa: E402
import onnxruntime as ort  # noqa: E402
from huggingface_hub import snapshot_download  # noqa: E402
from tokenizers import Tokenizer  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "datapipe" / "src"))
from medlabel_data import paths  # noqa: E402
from medlabel_data.fdarx.align import Label  # noqa: E402

OUT = Path("~/waicy-work/retrieval").expanduser()
QPFX = "Represent this sentence for searching relevant passages: "
MODELS = {
    # name: (repo, pooling, query prefix)
    "minilm": ("Xenova/all-MiniLM-L6-v2", "mean", ""),
    "bge": ("Xenova/bge-small-en-v1.5", "cls", QPFX),
    "arctic": ("Snowflake/snowflake-arctic-embed-xs", "cls", QPFX),
}
MAX_LEN = 256


class Embedder:
    def __init__(self, name: str, quantized: bool = True):
        repo, self.pool, self.qpfx = MODELS[name]
        f = "onnx/model_quantized.onnx" if quantized else "onnx/model.onnx"
        d = Path(snapshot_download(repo, allow_patterns=["*.json", "*.txt", f]))
        self.tok = Tokenizer.from_file(str(d / "tokenizer.json"))
        self.tok.enable_truncation(MAX_LEN)
        self.sess = ort.InferenceSession(str(d / f), providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.sess.get_inputs()}

    def __call__(self, texts: list[str], batch: int = 64) -> np.ndarray:
        out = []
        for i in range(0, len(texts), batch):
            enc = self.tok.encode_batch(texts[i:i + batch])
            n = max(len(e.ids) for e in enc)
            ids = np.array([e.ids + [0] * (n - len(e.ids)) for e in enc], dtype=np.int64)
            mask = np.array([[1] * len(e.ids) + [0] * (n - len(e.ids)) for e in enc], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            h = self.sess.run(None, feed)[0]
            if self.pool == "cls":
                v = h[:, 0]
            else:
                v = (h * mask[..., None]).sum(1) / mask.sum(1, keepdims=True)
            out.append(v / np.linalg.norm(v, axis=1, keepdims=True))
        return np.concatenate(out) if out else np.zeros((0, 384), np.float32)


def unit_texts(lab: Label) -> list[str]:
    return [f"{h}: {s}" if h else s for h, sents in lab.passages for s in sents]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=MODELS, required=True)
    ap.add_argument("--split", choices=["dev", "train"], default="dev")
    ap.add_argument("--fp32", action="store_true")
    a = ap.parse_args()
    meta = paths.BUILD / "fdarx" / "mlx_plain" / {"dev": "valid_meta.jsonl", "train": "train_meta.jsonl"}[a.split]
    items = [json.loads(l) for l in open(meta)]
    set_ids = {x["set_id"] for x in items}
    labs = {}
    for line in open(paths.FDARX_LABELS):
        r = json.loads(line)
        if r["set_id"] in set_ids:
            labs[r["set_id"]] = Label(r)
    emb = Embedder(a.model, quantized=not a.fp32)
    t0, arrays, n = time.time(), {}, 0
    for sid, lab in labs.items():
        arrays[f"units_{sid}"] = emb(unit_texts(lab)).astype(np.float16)
        n += len(arrays[f"units_{sid}"])
    qs = {x["qid"]: x["question"] for x in items}
    qv = emb([emb.qpfx + q for q in qs.values()])
    for qid, v in zip(qs, qv):
        arrays[f"q_{qid}"] = v.astype(np.float16)
    OUT.mkdir(parents=True, exist_ok=True)
    tag = "" if not a.fp32 else "_fp32"
    np.savez(OUT / f"emb_{a.model}{tag}_{a.split}.npz", **arrays)
    print(f"{a.model}: {len(labs)} labels, {n} sentences, {len(qs)} questions, {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
