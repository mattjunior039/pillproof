#!/usr/bin/env bash
# Gate 2 dev evaluation queue (run from the repo root after both fine-tunes finish).
# One GPU job at a time. Outputs go to ~/waicy-work/eval/<run>.{jsonl,meta.json,grade.json,graded.jsonl}.
#   B = base model + label passages (no fine-tune); C = LoRA fine-tune (checks are applied in grading).
#   Prompt sets: oracle (the gold passage block), phone (hybrid retrieval, 1,600-char budget),
#   desktop (3,500-char budget). Only dev items exist in these files.
set -euo pipefail
PY=~/waicy-work/envs/mlx/bin/python
M=~/waicy-work/models
A=$M/adapters
E=~/waicy-work/eval
export HF_HOME=~/waicy-work/hf_cache

run() {  # name model adapter prompts
  local name=$1 model=$2 adapter=$3 prompts=$4
  if [[ -f $E/$name.grade.json ]]; then echo "skip $name"; return; fi
  echo "=== $name $(date +%T)"
  [[ -f $E/$name.meta.json ]] || $PY train/scripts/eval_dev.py run --model "$model" ${adapter:+--adapter "$adapter"} --prompts "$prompts" \
      --out "$E/$name.jsonl" --max-tokens 256 --batch "${BATCH:-16}"
  $PY train/scripts/grade_dev.py "$E/$name.jsonl" > /dev/null
}

WHICH=${1:-all}   # 2b | 08 | all
if [[ $WHICH != 08 ]]; then for p in oracle phone desktop; do
  run B2b_$p $M/Qwen3.5-2B "" $p
  run C2b_$p $M/Qwen3.5-2B $A/medlabel-2b-r1 $p
done; fi
if [[ $WHICH != 2b ]]; then for p in oracle phone; do
  run B08_$p $M/Qwen3.5-0.8B "" $p
  run C08_$p $M/Qwen3.5-0.8B $A/medlabel-08-r1 $p
done; fi
echo "all done $(date +%T)"
