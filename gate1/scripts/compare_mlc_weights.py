"""Compare two MLC weight directories tensor by tensor.

Used to validate our conversion of the unmodified base model against mlc-ai's
official prebuilt build, and to show which tensors a LoRA merge changed.

Usage: python compare_mlc_weights.py DIR_A DIR_B
"""

import json
import sys
from pathlib import Path

import numpy as np

DTYPES = {"uint32": np.uint32, "float16": np.float16, "float32": np.float32, "bfloat16": np.uint16}


def load_records(d: Path):
    meta = json.loads((d / "tensor-cache.json").read_text())
    out = {}
    for shard in meta["records"]:
        raw = (d / shard["dataPath"]).read_bytes()
        for r in shard["records"]:
            buf = raw[r["byteOffset"] : r["byteOffset"] + r["nbytes"]]
            out[r["name"]] = (r["dtype"], tuple(r["shape"]), buf)
    return meta, out


def main():
    a_dir, b_dir = Path(sys.argv[1]), Path(sys.argv[2])
    _, a = load_records(a_dir)
    _, b = load_records(b_dir)
    only_a, only_b = sorted(set(a) - set(b)), sorted(set(b) - set(a))
    if only_a or only_b:
        print("names only in A:", only_a[:10], "\nnames only in B:", only_b[:10])
    identical, differ = 0, []
    for name in sorted(set(a) & set(b)):
        (da, sa, ba), (db, sb, bb) = a[name], b[name]
        if (da, sa) != (db, sb):
            differ.append((name, f"dtype/shape {da}{sa} vs {db}{sb}"))
            continue
        if ba == bb:
            identical += 1
            continue
        xa = np.frombuffer(ba, DTYPES[da])
        xb = np.frombuffer(bb, DTYPES[db])
        if da == "uint32":  # packed int4: compare the unpacked nibbles
            na = (xa[:, None] >> (np.arange(8, dtype=np.uint32) * 4)) & 0xF
            nb = (xb[:, None] >> (np.arange(8, dtype=np.uint32) * 4)) & 0xF
            ne = na != nb
            detail = f"{ne.mean():.2e} of int4 values differ, max |diff| {np.abs(na.astype(int) - nb.astype(int)).max()}"
        else:
            fa, fb = xa.astype(np.float32), xb.astype(np.float32)
            detail = f"max |diff| {np.abs(fa - fb).max():.3e}, mean |a| {np.abs(fa).mean():.3e}"
        differ.append((name, detail))
    print(f"{len(set(a) & set(b))} shared tensors: {identical} byte-identical, {len(differ)} differ")
    for name, detail in differ[:40]:
        print(f"  {name}: {detail}")
    if len(differ) > 40:
        print(f"  ... {len(differ) - 40} more")


if __name__ == "__main__":
    main()
