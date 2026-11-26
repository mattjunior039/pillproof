#!/usr/bin/env bash
# Final evaluation, T1 (FDARxBench test). One GPU job at a time; each run happens once.
# Same generation and grading as Gate 2 (eval_dev.py run / grade_dev.py), pointed at final/t1.
#   PHASE=1: phone runs (headline)   PHASE=2: desktop + oracle runs
set -euo pipefail
PY=~/waicy-work/envs/mlx/bin/python
M=~/waicy-work/models
A=$M/adapters
E=~/waicy-work/data/build/final/t1
export EVAL_DIR=$E HF_HOME=~/waicy-work/hf_cache

run() {  # name model adapter prompts
  local name=$1 model=$2 adapter=$3 prompts=$4
  if [[ -f $E/$name.grade.json ]]; then echo "skip $name"; return; fi
  echo "=== $name $(date +%T)"
  [[ -f $E/$name.meta.json ]] || $PY train/scripts/eval_dev.py run --model "$model" ${adapter:+--adapter "$adapter"} --prompts "$prompts" \
      --out "$E/$name.jsonl" --max-tokens 256 --batch 16
  $PY train/scripts/grade_dev.py "$E/$name.jsonl" > /dev/null
}

if [[ ${PHASE:-1} == 1 ]]; then
  run C2b_phone $M/Qwen3.5-2B $A/medlabel-2b-r1 phone
  run B2b_phone $M/Qwen3.5-2B "" phone
  run C08_phone $M/Qwen3.5-0.8B $A/medlabel-08-r1 phone
  run B08_phone $M/Qwen3.5-0.8B "" phone
else
  run C2b_desktop $M/Qwen3.5-2B $A/medlabel-2b-r1 desktop
  run B2b_desktop $M/Qwen3.5-2B "" desktop
  run C2b_oracle $M/Qwen3.5-2B $A/medlabel-2b-r1 oracle
  run B2b_oracle $M/Qwen3.5-2B "" oracle
  run C08_oracle $M/Qwen3.5-0.8B $A/medlabel-08-r1 oracle
  run B08_oracle $M/Qwen3.5-0.8B "" oracle
fi
echo "phase ${PHASE:-1} done $(date +%T)"
