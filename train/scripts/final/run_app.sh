#!/usr/bin/env bash
# Final evaluation: app-pipeline runs (B, C, F) and system A, one model on the GPU at a time.
# Run from the repo root after run_t1.sh PHASE=1. Each run happens once; finished outputs are skipped.
#   B  = base model + label passages (phone tier, label only)      -> app/<set>_B<size>_<tier>.jsonl
#   C  = fine-tune + checks, label only (phone)                     -> app/<set>_C2b_phone.jsonl
#   CF = fine-tune, backups + web ON; "first" is C, "shown_text" is F -> app/<set>_CF2b_desktop / CF08_phone
#   A  = base model, question only                                   -> app/<set>_A<size>.jsonl
set -uo pipefail
PY=~/waicy-work/envs/mlx/bin/python
F=~/waicy-work/data/build/final
ROOT=$(pwd)
PORT=8765
URL=http://127.0.0.1:$PORT
mkdir -p $F/logs $F/app

serve() {  # size [--adapter]
  (cd train/scripts/final && exec $PY mlx_server.py --size "$1" ${2:-} --port $PORT > $F/logs/server_$1${2:+_ft}.log 2>&1) &
  SPID=$!
  for _ in $(seq 120); do curl -s $URL/stats > /dev/null && return; sleep 2; done
  echo "server did not start"; exit 1
}
stop() {  # tag
  curl -s $URL/stats > $F/app/server_$1.stats.json
  kill $SPID 2>/dev/null; wait $SPID 2>/dev/null; sleep 3
}
app() {  # set name extra-args...
  local s=$1 n=$2; shift 2
  local out=$F/app/${s}_$n.jsonl
  if [[ -f ${out%.jsonl}.meta.json ]]; then echo "skip $s $n"; return; fi
  echo "=== $s $n $(date +%T)"
  (cd app && node eval/final_harness.ts --items $F/$s/items_app.jsonl --out $out --gen $URL "$@") || echo "FAILED $s $n"
}
plain() {  # set name
  local out=$F/app/${1}_$2.jsonl
  if [[ -f $out.done ]]; then echo "skip $1 $2"; return; fi
  echo "=== $1 $2 $(date +%T)"
  (cd train/scripts/final && python3 gen_plain.py run --set $1 --out $out --url $URL) && touch $out.done || echo "FAILED $1 $2"
}

serve 2b
head -3 $F/t3/items_app.jsonl > /tmp/pp_smoke_items.jsonl; rm -f /tmp/pp_smoke.jsonl
(cd app && node eval/final_harness.ts --items /tmp/pp_smoke_items.jsonl --out /tmp/pp_smoke.jsonl --gen $URL --tier phone) > $F/logs/smoke.log 2>&1
python3 -c "import json,sys;r=[json.loads(l) for l in open('/tmp/pp_smoke.jsonl')];assert len(r)==3 and all(x['label_calls'] and x['label_calls'][0]['raw'] for x in r),'smoke failed';print('smoke ok',[x['label_calls'][0]['raw'][:40] for x in r])" || { stop smoke_fail; exit 1; }
for s in t3 t2; do app $s B2b_phone --tier phone; app $s B2b_desktop --tier desktop; done
for s in t3 t2 t6 t1s; do plain $s A2b; done
stop 2b_base

serve 2b --adapter
for s in t3 t2 t6; do app $s C2b_phone --tier phone --model-key r1-ft; done
for s in t3 t2 t6; do app $s CF2b_desktop --tier desktop --backups --web --model-key r1-ft; done
stop 2b_ft

serve 08
for s in t3 t2; do app $s B08_phone --tier phone; done
for s in t3 t2 t6 t1s; do plain $s A08; done
stop 08_base

serve 08 --adapter
for s in t3 t2 t6; do app $s CF08_phone --tier phone --backups --web --model-key lite-r1-ft; done
stop 08_ft
echo "app runs done $(date +%T)"
