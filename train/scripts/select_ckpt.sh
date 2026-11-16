#!/usr/bin/env bash
# Pick a LoRA checkpoint on a dev subset (300 phone-prompt items, every ~4th dev item).
#   train/scripts/select_ckpt.sh 2B medlabel-2b-r1 800 1400 final
# Writes ~/waicy-work/eval/sel_<adapter>_<ckpt>.* and prints wrong rate (with checks) and
# answerable-correct rate per checkpoint. Selection uses dev only, so Gate 2 numbers on the
# full dev set are slightly optimistic for C (noted in docs/gate2.md).
set -euo pipefail
SIZE=$1 ADAPTER=$2; shift 2
PY=~/waicy-work/envs/mlx/bin/python
A=~/waicy-work/models/adapters
E=~/waicy-work/eval
export HF_HOME=~/waicy-work/hf_cache
for ck in "$@"; do
  name=sel_${ADAPTER}_$ck
  dir=$A/$ADAPTER
  if [[ $ck != final ]]; then
    dir=$A/$ADAPTER-ck$ck
    mkdir -p "$dir"
    cp "$A/$ADAPTER/adapter_config.json" "$dir/"
    ln -sf "$A/$ADAPTER/$(printf %07d "$ck")_adapters.safetensors" "$dir/adapters.safetensors"
  fi
  [[ -f $E/$name.meta.json ]] || $PY train/scripts/eval_dev.py run --model ~/waicy-work/models/Qwen3.5-$SIZE \
      --adapter "$dir" --prompts phone --limit 300 --max-tokens 256 --out "$E/$name.jsonl" | tail -1
  $PY train/scripts/grade_dev.py "$E/$name.jsonl" | $PY -c "
import json,sys; r=json.loads(sys.stdin.read()); c=r['checks']
print('$ck', 'wrong', c['wrong_rate'], 'ans_correct', c['answerable_correct'], 'false_decl', c['false_decline_rate'], 'false_ans', c['false_answer_rate'], 'select_ok', c['select_ok'])"
done
