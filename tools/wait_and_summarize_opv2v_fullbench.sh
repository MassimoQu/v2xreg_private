#!/usr/bin/env bash
set -euo pipefail

RUN_ID="${1:-}"
if [[ -z "$RUN_ID" ]]; then
  echo "Usage: $0 <RUN_ID>" >&2
  exit 2
fi

WORKDIR="/home/qqxluca/projects/v2xreg_private"
PY_BIN="$WORKDIR/.micromamba/envs/py39/bin/python"
RUN_DIR="$WORKDIR/outputs/full_bench_${RUN_ID}"
LOG="$RUN_DIR/finalize_from_yaml.log"

mkdir -p "$RUN_DIR"

echo "[$(date -Iseconds)] waiting for scheduler to exit: run_id=${RUN_ID}" | tee -a "$LOG"
while pgrep -f "tools/run_opv2v_fullbench_fast.py --run-id ${RUN_ID}" >/dev/null 2>&1; do
  sleep 300
  echo "[$(date -Iseconds)] still running..." | tee -a "$LOG"
done

echo "[$(date -Iseconds)] scheduler exited; summarizing from YAML" | tee -a "$LOG"
cd "$WORKDIR"
"$PY_BIN" tools/summarize_opv2v_fullbench_from_yaml.py --run-dir "$RUN_DIR" | tee -a "$LOG"
echo "[$(date -Iseconds)] done" | tee -a "$LOG"

