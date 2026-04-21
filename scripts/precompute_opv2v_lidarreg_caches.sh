#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PY_ENV="${ROOT_DIR}/.micromamba/envs/v2x"
PY_BIN="${PY_ENV}/bin/python"

if [[ ! -x "${PY_BIN}" ]]; then
  echo "[ERR] missing python env: ${PY_BIN}" >&2
  exit 1
fi

export PYTHONPATH="${ROOT_DIR}/HEAL"

CACHE_DIR="${ROOT_DIR}/data/OPV2V/lidar_reg_cache"
LOG_DIR="${ROOT_DIR}/outputs/lidar_reg_cache_logs/$(date +%Y%m%d_%H%M%S)"
mkdir -p "${CACHE_DIR}" "${LOG_DIR}"

SAVE_EVERY="${SAVE_EVERY:-50}"

echo "[INFO] cache_dir=${CACHE_DIR}"
echo "[INFO] log_dir=${LOG_DIR}"
echo "[INFO] save_every=${SAVE_EVERY}"

for GM in ransac teaser_gnctls teaser_fgr teaser_quatro; do
  echo "[INFO] precompute global_method=${GM}"
  "${PY_BIN}" "${ROOT_DIR}/tools/precompute_opv2v_lidar_reg_cache.py" \
    --global-method "${GM}" \
    --resume \
    --save-every "${SAVE_EVERY}" \
    > "${LOG_DIR}/${GM}.log" 2>&1
  echo "[INFO] done global_method=${GM} log=${LOG_DIR}/${GM}.log"
done

echo "[INFO] all caches done"

