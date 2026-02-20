#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
OUT_DIR=${OUT_DIR:-"$ROOT_DIR/exports"}
STAMP=$(date +%Y%m%d_%H%M%S)
PATCH_DIR="$OUT_DIR/patches_${STAMP}"

mkdir -p "$PATCH_DIR"

git -C "$ROOT_DIR" status -sb > "$PATCH_DIR/main_status.txt"
git -C "$ROOT_DIR" diff > "$PATCH_DIR/main.diff"
git -C "$ROOT_DIR" ls-files --others --exclude-standard > "$PATCH_DIR/main_untracked.txt"

if [[ -d "$ROOT_DIR/HEAL/.git" ]]; then
  git -C "$ROOT_DIR/HEAL" status -sb > "$PATCH_DIR/heal_status.txt"
  git -C "$ROOT_DIR/HEAL" diff > "$PATCH_DIR/heal.diff"
  git -C "$ROOT_DIR/HEAL" ls-files --others --exclude-standard > "$PATCH_DIR/heal_untracked.txt"
fi

echo "Exported patch bundle to: $PATCH_DIR"
