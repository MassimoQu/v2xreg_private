#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.micromamba/envs/py39/bin/python}"

TAG="${TAG:-$(date +%Y%m%d_%H%M%S)}"
OUT_DIR="$ROOT_DIR/outputs/opv2v_autopilot_${TAG}"
mkdir -p "$OUT_DIR"

LOG="$OUT_DIR/launcher.log"
PID_FILE="$OUT_DIR/autopilot.pid"
RUN_MODE="${RUN_MODE:-supervisor}" # supervisor|direct

SUPERVISOR_OUT_DIR="$ROOT_DIR/outputs/opv2v_autopilot_supervisor_${TAG}"
SUPERVISOR_LOG="$SUPERVISOR_OUT_DIR/supervisor_launcher.log"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-4}"
RETRY_WAIT_SECONDS="${RETRY_WAIT_SECONDS:-20}"
SUPERVISOR_POLL_SECONDS="${SUPERVISOR_POLL_SECONDS:-60}"
FAILURE_HOOK="${FAILURE_HOOK:-}"

SESSION="opv2v_auto_${TAG}"
EXTRA_ARGS=("$@")

CMD=()
RUN_LOG="$LOG"
if [[ "$RUN_MODE" == "supervisor" ]]; then
  mkdir -p "$SUPERVISOR_OUT_DIR"
  CMD=(
    "$PYTHON_BIN" "$ROOT_DIR/tools/opv2v_autopilot_supervisor.py"
    "--tag" "$TAG"
    "--max-attempts" "$MAX_ATTEMPTS"
    "--poll-seconds" "$SUPERVISOR_POLL_SECONDS"
    "--retry-wait-seconds" "$RETRY_WAIT_SECONDS"
  )
  if [[ -n "$FAILURE_HOOK" ]]; then
    CMD+=("--failure-hook" "$FAILURE_HOOK")
  fi
  CMD+=("--")
  CMD+=("${EXTRA_ARGS[@]}")
  RUN_LOG="$SUPERVISOR_LOG"
elif [[ "$RUN_MODE" == "direct" ]]; then
  CMD=("$PYTHON_BIN" "$ROOT_DIR/tools/opv2v_benchmark_autopilot.py" "--tag" "$TAG")
  CMD+=("${EXTRA_ARGS[@]}")
else
  echo "Invalid RUN_MODE=$RUN_MODE (expected supervisor|direct)" >&2
  exit 2
fi

CMD_ESCAPED=$(printf '%q ' "${CMD[@]}")

if command -v tmux >/dev/null 2>&1; then
  # Run inside tmux so it survives disconnects and is easy to inspect.
  tmux new-session -d -s "$SESSION" bash -lc \
    "cd \"$ROOT_DIR\" && \
     ${CMD_ESCAPED}>\"$RUN_LOG\" 2>&1; \
     rc=\$?; echo \"[autopilot exited rc=\$rc]\"; \
     exec bash"
  echo "$SESSION" >"$PID_FILE"
else
  nohup "${CMD[@]}" >"$RUN_LOG" 2>&1 &
  echo $! >"$PID_FILE"
fi

echo "Started OPV2V autopilot:"
echo " - tag: $TAG"
echo " - mode: $RUN_MODE"
echo " - runner: $(cat "$PID_FILE")"
if [[ "$RUN_MODE" == "supervisor" ]]; then
  echo " - supervisor_log: $SUPERVISOR_LOG"
  echo " - supervisor_state: $SUPERVISOR_OUT_DIR/state.json"
else
  echo " - log: $LOG"
fi
echo "Check progress:"
if [[ "$RUN_MODE" == "supervisor" ]]; then
  echo " - tail -f $SUPERVISOR_OUT_DIR/supervisor.log"
  echo " - ./scripts/opv2v_autopilot_status.sh $TAG"
else
  echo " - tail -f $OUT_DIR/autopilot.log"
fi
if command -v tmux >/dev/null 2>&1; then
  echo " - tmux attach -t $SESSION"
fi
echo "Stop:"
if command -v tmux >/dev/null 2>&1; then
  echo " - tmux kill-session -t $SESSION"
else
  echo " - kill $(cat "$PID_FILE")"
fi
