#!/usr/bin/env bash
set -euo pipefail

INCIDENT_PATH="${1:-}"
TAG="${2:-}"
ATTEMPT="${3:-}"
RC="${4:-}"

if [[ -z "$INCIDENT_PATH" || -z "$TAG" || -z "$ATTEMPT" || -z "$RC" ]]; then
  echo "Usage: $0 <incident_path> <tag> <attempt> <rc>" >&2
  exit 2
fi

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SUP_DIR="$ROOT_DIR/outputs/opv2v_autopilot_supervisor_${TAG}"
mkdir -p "$SUP_DIR"
HOOK_LOG="$SUP_DIR/hook.log"

{
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] wake hook: tag=$TAG attempt=$ATTEMPT rc=$RC incident=$INCIDENT_PATH"
} >>"$HOOK_LOG"

MESSAGE="Autopilot abnormal exit (tag=${TAG}, attempt=${ATTEMPT}, rc=${RC}). Please inspect: ${INCIDENT_PATH}"

# Highest priority: explicit tmux pane target (e.g., 1940:1.1).
if [[ -n "${CODEX_PANE:-}" ]]; then
  if tmux list-panes -a -F '#S:#I.#P' 2>/dev/null | rg -qx "${CODEX_PANE}"; then
    tmux send-keys -t "$CODEX_PANE" "$MESSAGE" C-m
    tmux display-message -t "$CODEX_PANE" "$MESSAGE" || true
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] sent to tmux pane: $CODEX_PANE" >>"$HOOK_LOG"
    exit 0
  fi
fi

# Preferred: push message into an existing tmux Codex session.
if [[ -n "${CODEX_SESSION:-}" ]]; then
  if tmux ls 2>/dev/null | rg -q "^${CODEX_SESSION}:"; then
    tmux send-keys -t "$CODEX_SESSION" "$MESSAGE" C-m
    tmux display-message -t "$CODEX_SESSION" "$MESSAGE" || true
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] sent to tmux session: $CODEX_SESSION" >>"$HOOK_LOG"
    exit 0
  fi
fi

# Fallback: write directly to terminal TTY.
if [[ -n "${CODEX_TTY:-}" && -w "${CODEX_TTY}" ]]; then
  printf '\a\n[autopilot-alert] %s\n' "$MESSAGE" >"${CODEX_TTY}" || true
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] wrote alert to tty: $CODEX_TTY" >>"$HOOK_LOG"
  exit 0
fi

# Fallback: custom external command hook.
if [[ -n "${CODEX_WAKE_CMD:-}" ]]; then
  # shellcheck disable=SC2086
  eval "$CODEX_WAKE_CMD \"${INCIDENT_PATH}\" \"${TAG}\" \"${ATTEMPT}\" \"${RC}\"" >>"$HOOK_LOG" 2>&1 || true
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] invoked CODEX_WAKE_CMD" >>"$HOOK_LOG"
  exit 0
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] no CODEX_SESSION/CODEX_WAKE_CMD configured" >>"$HOOK_LOG"
exit 0
