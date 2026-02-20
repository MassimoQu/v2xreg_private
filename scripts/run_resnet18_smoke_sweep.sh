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

export CUDA_VISIBLE_DEVICES=3
export PYTHONUNBUFFERED=1

for cfg in configs/camera/desc/camera_desc_top3000_resnet18_smoke_w*_s*.yaml; do
  echo "== ${cfg} =="
  "$PYTHON_BIN" -u tools/run_calibration.py --config "${cfg}" --print
done
