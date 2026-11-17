#!/usr/bin/env bash
# Merge a Gate 2 LoRA adapter into the HF checkpoint and convert it for WebLLM (Gate 1 pipeline).
#   train/scripts/convert_mlc.sh 2B medlabel-2b-r1
#   train/scripts/convert_mlc.sh 0.8B medlabel-08-r1
#   train/scripts/convert_mlc.sh 2B medlabel-2b-r2 medlabel-r2     (r2, after the decline fix)
# Output: ~/waicy-work/models/mlc/Qwen3.5-<size>-medlabel-r1-q4f16_1-MLC (served by gate1/scripts/serve.py).
# The merged HF checkpoint is deleted after conversion to save disk (re-create it with the merge step).
set -euo pipefail
SIZE=$1 ADAPTER=$2 TAG=${3:-medlabel-r1}
M=~/waicy-work/models
BASE=$M/Qwen3.5-$SIZE
HF=$M/Qwen3.5-$SIZE-$TAG-hf
OUT=$M/mlc/Qwen3.5-$SIZE-$TAG-q4f16_1-MLC
~/waicy-work/envs/mlx/bin/python gate1/scripts/merge_mlx_lora.py "$BASE" "$M/adapters/$ADAPTER" "$HF"
PY=~/waicy-work/envs/mlc/bin/python
$PY gate1/scripts/mlc_cli.py convert_weight "$HF" --quantization q4f16_1 --device cpu -o "$OUT"
$PY gate1/scripts/mlc_cli.py gen_config "$HF" --quantization q4f16_1 --conv-template qwen2 \
    --prefill-chunk-size 1024 -o "$OUT"
# Only the LoRA-targeted tensors should differ from our conversion of the base model.
$PY gate1/scripts/compare_mlc_weights.py "$M/mlc/Qwen3.5-$SIZE-base-q4f16_1-MLC" "$OUT" | tail -5 || true
rm -rf "$HF"
du -sh "$OUT"
