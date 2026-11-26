#!/usr/bin/env bash
# v1.1 evaluation runs (docs/v1.1.md), one model on the GPU at a time, each run once. Run from the repo root at tag
# v1.1-2026-11-26 after T7 is frozen. v1.0 runs use the frozen app (worktree at freeze-2026-11-25, V10 below); v1.1 runs
# use this checkout. Both share final/cache (openFDA, FDA pages, DDInter, web search), so a backup fetched once is reused.
#   F  = fine-tune, backups + web ON (2B desktop tier r1-ft; 0.8B phone tier lite-r1-ft)
#   B  = base model + label passages (phone tier, label only); D = passages only (no model). Context, frozen v1.0 app.
set -uo pipefail
PY=~/waicy-work/envs/mlx/bin/python
F=~/waicy-work/data/build/final
O=$F/v11
T7=~/waicy-work/data/build/t7/items_app.jsonl
T3=$F/t3/items_app.jsonl
V10=~/waicy-work/v10_app
PORT=8765
URL=http://127.0.0.1:$PORT
mkdir -p $F/logs $O

serve() {  # size [--adapter]
  (cd train/scripts/final && exec $PY mlx_server.py --size "$1" ${2:-} --port $PORT > $F/logs/v11_server_$1${2:+_ft}.log 2>&1) &
  SPID=$!
  for _ in $(seq 120); do curl -s $URL/stats > /dev/null && return; sleep 2; done
  echo "server did not start"; exit 1
}
stop() {  # tag
  curl -s $URL/stats > $O/server_$1.stats.json
  kill $SPID 2>/dev/null; wait $SPID 2>/dev/null; sleep 3
}
run() {  # app-dir items name extra-args...
  local dir=$1 items=$2 n=$3; shift 3
  local out=$O/$n.jsonl
  if [[ -f ${out%.jsonl}.meta.json ]]; then echo "skip $n"; return; fi
  echo "=== $n $(date +%T)"
  (cd $dir && node eval/final_harness.ts --items $items --out $out "$@") || echo "FAILED $n"
}

serve 2b --adapter
run $V10/app $T7 t7_v10_F2b --gen $URL --tier desktop --backups --web --model-key r1-ft
run app $T7 t7_v11_F2b --gen $URL --tier desktop --backups --web --model-key r1-ft
run app $T3 t3_v11_F2b --gen $URL --tier desktop --backups --web --model-key r1-ft
stop 2b_ft

serve 08 --adapter
run $V10/app $T7 t7_v10_F08 --gen $URL --tier phone --backups --web --model-key lite-r1-ft
run app $T7 t7_v11_F08 --gen $URL --tier phone --backups --web --model-key lite-r1-ft
run app $T3 t3_v11_F08 --gen $URL --tier phone --backups --web --model-key lite-r1-ft
stop 08_ft

serve 2b
run $V10/app $T7 t7_B2b_phone --gen $URL --tier phone
stop 2b_base

serve 08
run $V10/app $T7 t7_B08_phone --gen $URL --tier phone
stop 08_base

run $V10/app $T7 t7_D_phone --tier phone
echo "v1.1 runs done $(date +%T)"
