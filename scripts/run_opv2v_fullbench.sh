#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

PYTHON_BIN=${PYTHON_BIN:-""}
if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$ROOT_DIR/.micromamba/envs/py39/bin/python" ]]; then
    PYTHON_BIN="$ROOT_DIR/.micromamba/envs/py39/bin/python"
  else
    PYTHON_BIN="$(command -v python3 || command -v python || true)"
  fi
fi
if [[ -z "$PYTHON_BIN" ]]; then
  echo "ERROR: python not found. Set PYTHON_BIN to your python executable." >&2
  exit 1
fi

RUN_ID=${RUN_ID:-"opv2v_fullbench_$(date +%Y%m%d_%H%M%S)"}
GPU_LIST=${GPU_LIST:-"0,1,2,3,4,5,6,7,8,9"}
NOISE_LIST=${NOISE_LIST:-"1,2,3,4,5,6,7,8,9,10"}
ROT_LIST=${ROT_LIST:-"1,2,3,4,5,6,7,8,9,10"}
DROPOUT=${DROPOUT:-"0.2"}
NO_DROPOUT=${NO_DROPOUT:-"0"}
MAX_PER_GPU=${MAX_PER_GPU:-"3"}
NUM_WORKERS=${NUM_WORKERS:-"4"}
MAX_EVAL_SAMPLES=${MAX_EVAL_SAMPLES:-"0"}
SMOKE=${SMOKE:-"0"}

# Offline-map (legacy) vs online end-to-end semantics.
# - offline_map: pre-pass solver, then eval with clean/no-noise geometry
# - online_box: solver runs inside pose_provider at runtime
SOLVER_BACKEND=${SOLVER_BACKEND:-"offline_map"}
RUNTIME_MODE=${RUNTIME_MODE:-""}
POSE_SOURCE=${POSE_SOURCE:-"noisy_input"}

CAMERA_MODEL=${CAMERA_MODEL:-"$ROOT_DIR/HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope"}
LIDAR_MODEL=${LIDAR_MODEL:-"$ROOT_DIR/HEAL/opencood/logs/freealign_repro_opv2v_baseline"}

CAMERA_STAGE1=${CAMERA_STAGE1:-"$ROOT_DIR/data/OPV2V/detected/opv2v_camera_v2xvit_stage1_percav/test/stage1_boxes.json"}
LIDAR_STAGE1=${LIDAR_STAGE1:-"$ROOT_DIR/data/OPV2V/detected/opv2v_lidar_v2xvit_stage1/test/stage1_boxes.json"}

EXTRA_ARGS=()
if [[ "$NO_DROPOUT" == "1" ]]; then
  EXTRA_ARGS+=(--no-dropout)
else
  EXTRA_ARGS+=(--dropout "$DROPOUT")
fi

# Smoke profile: reduce sweep points + sample count to catch config/semantic issues fast.
if [[ "$SMOKE" == "1" ]]; then
  if [[ "$NOISE_LIST" == "1,2,3,4,5,6,7,8,9,10" ]]; then
    NOISE_LIST="1,5"
    ROT_LIST="1,5"
  fi
  if [[ "$MAX_EVAL_SAMPLES" == "0" ]]; then
    MAX_EVAL_SAMPLES="100"
  fi
fi

EXTRA_ARGS+=(--solver-backend "$SOLVER_BACKEND")
EXTRA_ARGS+=(--pose-source "$POSE_SOURCE")
if [[ -n "$RUNTIME_MODE" ]]; then
  EXTRA_ARGS+=(--runtime-mode "$RUNTIME_MODE")
fi
if [[ "$MAX_EVAL_SAMPLES" != "0" ]]; then
  EXTRA_ARGS+=(--max-eval-samples "$MAX_EVAL_SAMPLES")
fi

PYTHONPATH="$ROOT_DIR/HEAL" "$PYTHON_BIN" "$ROOT_DIR/tools/run_opv2v_fullbench_fast.py" \
  --run-id "$RUN_ID" \
  --gpus "$GPU_LIST" \
  --max-per-gpu "$MAX_PER_GPU" \
  --num-workers "$NUM_WORKERS" \
  --noise-list "$NOISE_LIST" \
  --rot-list "$ROT_LIST" \
  --camera-model "$CAMERA_MODEL" \
  --lidar-model "$LIDAR_MODEL" \
  --camera-stage1 "$CAMERA_STAGE1" \
  --lidar-stage1 "$LIDAR_STAGE1" \
  "${EXTRA_ARGS[@]}" \
  "$@"
