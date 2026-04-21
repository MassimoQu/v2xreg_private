#!/usr/bin/env bash
set -euo pipefail
RUN_ID="$1"
shift
WORKDIR="/home/qqxluca/projects/v2xreg_private"
PY_BIN="$WORKDIR/.micromamba/envs/py39/bin/python"
LOG="$WORKDIR/outputs/full_bench_${RUN_ID}/restart_to_mp3.log"

while true; do
  count=$(ps -ef | rg -i "inference_w_noise.py" | rg -v "rg -i" | wc -l | tr -d " ")
  if [[ "$count" == "0" ]]; then
    break
  fi
  echo "[$(date -Iseconds)] waiting, running tasks: $count" | tee -a "$LOG"
  sleep 60
  
done

echo "[$(date -Iseconds)] restarting scheduler with max-per-gpu 3" | tee -a "$LOG"
cd "$WORKDIR"
$PY_BIN tools/run_opv2v_fullbench_fast.py --run-id "$RUN_ID" --gpus 0,1,2,3,4,5,6,7,8,9 --max-per-gpu 3 --num-workers 4
