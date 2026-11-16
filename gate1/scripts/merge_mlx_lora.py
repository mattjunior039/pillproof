"""Merge an mlx-lm LoRA adapter into the original Hugging Face checkpoint.

Why not `mlx_lm.fuse`? For Qwen3.5, mlx-lm's loader renames weights
(model.language_model.* -> language_model.model.*), drops the vision/MTP
tensors, transposes conv1d and adds +1 to RMSNorm weights. Its fused output is
therefore not an HF checkpoint, and MLC's converter would apply the norm shift a
second time. Instead we patch only the LoRA'd Linear weights inside the
original safetensors file and keep everything else byte-for-byte:

    W' = W + scale * (lora_a @ lora_b).T      (mlx-lm LoRALinear.fuse)

Usage: python merge_mlx_lora.py BASE_HF_DIR ADAPTER_DIR OUT_DIR
"""

import json
import shutil
import sys
from pathlib import Path

import mlx.core as mx


def main():
    base, adapter, out = (Path(p) for p in sys.argv[1:4])
    cfg = json.loads((adapter / "adapter_config.json").read_text())
    scale = float(cfg["lora_parameters"]["scale"])
    lora = mx.load(str(adapter / "adapters.safetensors"))

    # mlx-lm module path -> HF tensor name
    pairs = {}
    for k in lora:
        mod, kind = k.rsplit(".", 1)
        hf = mod.replace("language_model.model.", "model.language_model.", 1) + ".weight"
        pairs.setdefault(hf, {})[kind] = lora[k]

    out.mkdir(parents=True, exist_ok=True)
    for f in base.iterdir():
        if f.is_file() and not f.name.endswith(".safetensors"):
            shutil.copy2(f, out / f.name)

    merged = 0
    for st in sorted(base.glob("*.safetensors")):
        weights, meta = mx.load(str(st), return_metadata=True)
        for name, ab in pairs.items():
            if name not in weights:
                continue
            w = weights[name]
            delta = (scale * (ab["lora_a"].astype(mx.float32) @ ab["lora_b"].astype(mx.float32))).T
            assert delta.shape == w.shape, (name, delta.shape, w.shape)
            weights[name] = (w.astype(mx.float32) + delta).astype(w.dtype)
            merged += 1
        mx.save_safetensors(str(out / st.name), weights, metadata=meta or {"format": "pt"})
    missing = len(pairs) - merged
    print(f"merged {merged} LoRA pairs (scale {scale}) into {out}; {missing} not found")
    if missing:
        sys.exit(1)


if __name__ == "__main__":
    main()
