#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
OUT_DIR=${OUT_DIR:-"$ROOT_DIR/exports"}
STAMP=$(date +%Y%m%d_%H%M%S)
TAR_PATH="$OUT_DIR/v2xreg_private_src_${STAMP}.tar.gz"

mkdir -p "$OUT_DIR"

EXCLUDES=(
  --exclude="./.git"
  --exclude="./.micromamba"
  --exclude="./.torch_cache_zoe"
  --exclude="./.runner.log"
  --exclude="./data"
  --exclude="./outputs"
  --exclude="./outputs_tmp"
  --exclude="./logs"
  --exclude="./exports"
  --exclude="./HEAL/opencood/logs"
  --exclude="./HEAL/dataset"
  --exclude="./HEAL/data"
  --exclude="./__pycache__"
)

tar -czf "$TAR_PATH" -C "$ROOT_DIR" "${EXCLUDES[@]}" .

echo "Packed repo to: $TAR_PATH"
echo "Excluded: data/ outputs/ logs/ HEAL/opencood/logs/ HEAL/dataset/ HEAL/data/ .git/"
