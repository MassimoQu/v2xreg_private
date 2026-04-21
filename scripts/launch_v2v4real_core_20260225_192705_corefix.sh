#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

tag="20260225_192705_corefix"
log="outputs/v2v4real_core_${tag}_launcher.log"

./.micromamba/envs/py39/bin/python -u tools/run_v2v4real_core_benchmark.py \
  --tag "$tag" \
  --gpus 0,1,2,3,4,5,6,7,8,9 \
  --max-per-gpu 2 \
  --split-noise \
  --suite core_plus_stable \
  2>&1 | tee "$log"
