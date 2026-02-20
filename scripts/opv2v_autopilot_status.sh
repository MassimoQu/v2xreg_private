#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TAG="${1:-}"
if [[ -z "$TAG" ]]; then
  echo "Usage: $0 <TAG>" >&2
  exit 2
fi

OUT_DIR="$ROOT_DIR/outputs/opv2v_autopilot_${TAG}"
SUP_DIR="$ROOT_DIR/outputs/opv2v_autopilot_supervisor_${TAG}"
if [[ ! -d "$OUT_DIR" && ! -d "$SUP_DIR" ]]; then
  echo "Not found: $OUT_DIR or $SUP_DIR" >&2
  exit 1
fi

echo "== autopilot tag: $TAG =="
SESSION="opv2v_auto_${TAG}"
if tmux ls 2>/dev/null | rg -q "^${SESSION}:"; then
  echo "tmux session: $SESSION (running)"
else
  echo "tmux session: $SESSION (not found)"
fi
echo

if [[ -d "$SUP_DIR" ]]; then
  echo "-- supervisor state --"
  cat "$SUP_DIR/state.json" 2>/dev/null || true
  echo

  echo "-- tail supervisor.log --"
  tail -n 40 "$SUP_DIR/supervisor.log" 2>/dev/null || true
  echo

  ATTEMPT_TAG=$(python3 - "$SUP_DIR/state.json" <<'PY'
import json, sys
path = sys.argv[1]
try:
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    print(obj.get("attempt_tag") or "")
except Exception:
    print("")
PY
)
  if [[ -n "$ATTEMPT_TAG" ]]; then
    CUR_DIR="$ROOT_DIR/outputs/opv2v_autopilot_${ATTEMPT_TAG}"
    echo "-- tail current autopilot.log (${ATTEMPT_TAG}) --"
    tail -n 40 "$CUR_DIR/autopilot.log" 2>/dev/null || true
    echo
  fi
else
  echo "-- tail autopilot.log --"
  tail -n 40 "$OUT_DIR/autopilot.log" 2>/dev/null || true
  echo
fi

echo "-- active benchmark procs --"
ps -eo pid,etimes,pcpu,pmem,cmd | rg "run_opv2v_fullbench_fast.py|inference_w_noise.py|export_stage1_boxes_per_cav.py" | rg -v rg || true
