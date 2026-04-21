#!/usr/bin/env bash
set -euo pipefail

# Queue OPV2V autopilot run after an existing V2V4Real core runner finishes.
#
# Usage:
#   bash scripts/queue_after_v2v4real_then_opv2v.sh 20260225_034525
#
# Recommended launch (detach):
#   nohup bash scripts/queue_after_v2v4real_then_opv2v.sh 20260225_034525 \
#     > outputs/queue_after_v2v4real_20260225_034525.nohup.log 2>&1 &

WAIT_TAG="${1:-}"
if [[ -z "${WAIT_TAG}" ]]; then
  echo "ERROR: missing WAIT_TAG. Example: 20260225_034525" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export PYTHONUNBUFFERED=1
export OPENCOOD_VOXEL_GPU=1
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-1}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export NUMEXPR_NUM_THREADS="${NUMEXPR_NUM_THREADS:-1}"

echo "[queue] root=${ROOT}"
echo "[queue] wait v2v4real tag=${WAIT_TAG}"
echo "[queue] started_at=$(date '+%F %T')"

PATTERN="tools/run_v2v4real_core_benchmark.py --tag ${WAIT_TAG}"
if command -v pgrep >/dev/null 2>&1; then
  while pgrep -f "${PATTERN}" >/dev/null 2>&1; do
    echo "[queue] $(date '+%F %T') still running: ${PATTERN}"
    sleep 120
  done
else
  while ps -ef | rg -F "${PATTERN}" | rg -v 'rg -F' >/dev/null 2>&1; do
    echo "[queue] $(date '+%F %T') still running: ${PATTERN}"
    sleep 120
  done
fi

echo "[queue] $(date '+%F %T') v2v4real runner finished; launching OPV2V autopilot pipeline"

PIPE_TAG="after_${WAIT_TAG}_$(date +%Y%m%d_%H%M%S)"
echo "[queue] pipeline tag=${PIPE_TAG}"

cd "${ROOT}"
.micromamba/envs/py39/bin/python -u tools/run_core_benchmark_pipeline.py \
  --tag "${PIPE_TAG}" \
  --gpus 0,1,2,3,4,5,6,7,8,9 \
  --opv2v-max-per-gpu 3 \
  --skip-v2v4real

echo "[queue] done_at=$(date '+%F %T')"
