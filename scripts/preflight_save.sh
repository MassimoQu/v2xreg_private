#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

MAX_TRACKED_FILE_MB="${MAX_TRACKED_FILE_MB:-50}"
MAX_TRACKED_FILE_BYTES=$((MAX_TRACKED_FILE_MB * 1024 * 1024))

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

warn() {
  echo "WARN: $*" >&2
}

echo "[preflight] repo: $ROOT_DIR"

branch="$(git -C "$ROOT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
if [[ -n "$branch" && "$branch" != snapshot/* ]]; then
  warn "branch is '$branch' (expected snapshot/*)"
fi

echo "[preflight] main status"
git -C "$ROOT_DIR" status -sb

if [[ -n "$(git -C "$ROOT_DIR" status --porcelain=v1)" ]]; then
  echo
  git -C "$ROOT_DIR" status --porcelain=v1 | head -n 200
  fail "main repo has uncommitted changes or untracked files"
fi

echo "[preflight] submodules"
git -C "$ROOT_DIR" submodule status --recursive || true

dirty_submodules="$(
  git -C "$ROOT_DIR" submodule foreach --quiet --recursive '
    if [ -n "$(git status --porcelain=v1)" ]; then
      echo "$name"
    fi
  ' || true
)"
if [[ -n "$dirty_submodules" ]]; then
  echo
  echo "$dirty_submodules" | sed 's/^/ - /'
  fail "dirty submodule(s) detected (commit/push inside submodule, then bump pointer here)"
fi

echo "[preflight] disallowed tracked files"
tracked_pdfs="$(git -C "$ROOT_DIR" ls-files '*.pdf' || true)"
if [[ -n "$tracked_pdfs" ]]; then
  echo "$tracked_pdfs" | sed 's/^/ - /'
  fail "PDFs are tracked; keep them out of git and store hashes in docs/REFERENCES.md instead"
fi

bad_tracked_roots=()
# NOTE: we keep a tiny DAIR-V2X sample under `data/DAIR-V2X/` for smoke tests.
# The large full datasets / caches should never be tracked.
for p in \
  outputs \
  static/visuals \
  exports \
  data/DAIR-V2X/cooperative-vehicle-infrastructure \
  data/DAIR-V2X/detected \
  data/OPV2V \
  data/V2XSim2; do
  if git -C "$ROOT_DIR" ls-files "$p" | grep -q .; then
    bad_tracked_roots+=("$p")
  fi
done
if [[ ${#bad_tracked_roots[@]} -gt 0 ]]; then
  printf '%s\n' "${bad_tracked_roots[@]}" | sed 's/^/ - /'
  fail "large artifacts/datasets appear to be tracked (see .gitignore)"
fi

echo "[preflight] large tracked files (> ${MAX_TRACKED_FILE_MB}MB)"
ROOT_DIR="$ROOT_DIR" MAX_TRACKED_FILE_BYTES="$MAX_TRACKED_FILE_BYTES" python3 - <<'PY'
import os
import subprocess
import sys

root = os.environ["ROOT_DIR"]
max_bytes = int(os.environ["MAX_TRACKED_FILE_BYTES"])

paths = subprocess.check_output(["git", "-C", root, "ls-files", "-z"]).split(b"\0")
large = []
for raw in paths:
    if not raw:
        continue
    p = raw.decode("utf-8", errors="replace")
    abs_p = os.path.join(root, p)
    try:
        size = os.path.getsize(abs_p)
    except OSError:
        continue
    if size > max_bytes:
        large.append((size, p))

large.sort(reverse=True)
if large:
    for size, p in large[:50]:
        sys.stdout.write("{:8.1f} MB  {}\n".format(size / 1024 / 1024, p))
    sys.exit(1)
PY

echo "[preflight] OK"
