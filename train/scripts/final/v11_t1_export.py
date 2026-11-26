"""Input for the v1.1 T1 refusal replay (docs/v1.1.md, app/eval/v11_replay.ts).

The 549 FDARxBench refusal items with their label passages (FDARxBench chunks, as in T1) and the T1 bge
similarities of the question to every label sentence. Run with ~/waicy-work/envs/mlx/bin/python.
"""
import json
import sys

import numpy as np

sys.path.insert(0, ".")
import t1_prep as T  # noqa: E402
from common import FINAL  # noqa: E402

items, _, labs = T.load()
P = {(r := json.loads(l))["qid"]: r for l in open(FINAL / "t1/prompts_phone.jsonl")}
emb = np.load(T.RDIR / "emb_bge_test.npz")
(FINAL / "v11").mkdir(exist_ok=True)
ref = [x for x in items if x["kind"] == "fdarx_refusal"]
with open(FINAL / "v11/t1_refusal_replay_in.jsonl", "w") as f:
    for x in ref:
        p, lab = P[x["qid"]], labs[x["set_id"]]
        U, q = emb[f"units_{x['set_id']}"].astype(np.float32), emb[f"q_{x['qid']}"].astype(np.float32)
        assert U.shape[0] == sum(len(s) for _, s in lab.passages)
        f.write(json.dumps({"qid": x["qid"], "drug": p["drug"], "question": p["question"], "set_id": x["set_id"],
                            "passages": [[h, s] for h, s in lab.passages], "sims": [round(float(v), 5) for v in U @ q]}) + "\n")
print(len(ref), "refusal items")
