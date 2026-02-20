#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${OPV2V_ROOT:-}" ]]; then
  echo "ERROR: Please set OPV2V_ROOT to the dataset root (containing train/validate/test)." >&2
  echo "Example: OPV2V_ROOT=/data/OPV2V ./scripts/prepare_opv2v_dataset.sh" >&2
  exit 1
fi

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
DATASET_DIR="$ROOT_DIR/dataset/OPV2V"

if [[ -e "$DATASET_DIR" && ! -L "$DATASET_DIR" ]]; then
  echo "ERROR: $DATASET_DIR exists and is not a symlink. Move it away or delete it first." >&2
  exit 1
fi

mkdir -p "$ROOT_DIR/dataset"
if [[ -L "$DATASET_DIR" ]]; then
  echo "Symlink already exists: $DATASET_DIR -> $(readlink -f "$DATASET_DIR")"
else
  ln -s "$OPV2V_ROOT" "$DATASET_DIR"
  echo "Created symlink: $DATASET_DIR -> $OPV2V_ROOT"
fi

# Create detection cache root (stage1 boxes go here)
mkdir -p "$ROOT_DIR/data/OPV2V/detected"

echo "Done. Dataset link ready at $DATASET_DIR"
