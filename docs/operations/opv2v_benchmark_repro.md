# OPV2V Full Benchmark Reproduction (HEAL)

This document describes how to reproduce the OPV2V camera + LiDAR full benchmark
(noise sweep + dropout sweep) on a clean machine.

## Prerequisites

- Linux + CUDA‑capable GPUs (10×3090 recommended for full parallelism).
- Python 3.9+.
- PyTorch built for your CUDA version.
- `spconv` GPU voxelization (optional but recommended for speed).

### Environment (example)

```bash
# 1) Create env (conda or micromamba). Example using micromamba:
micromamba create -n heal_py39 python=3.9 -y
micromamba activate heal_py39

# 2) Install core deps
pip install -r HEAL/requirements.txt

# 3) Install PyTorch (adjust to your CUDA version)
# Example for CUDA 12.0
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu120

# 4) Install spconv (optional but recommended for speed)
pip install spconv-cu120==2.3.6
```

> If you do not use spconv, the code will fall back to CPU voxelization.
> You can set `PYTHON_BIN` to your Python executable; scripts will auto‑detect
> `.micromamba/envs/py39/bin/python` or fall back to `python3`/`python`.

## Step 1 — Fetch repo + submodules

```bash
git clone <your_repo_url>
cd v2xreg_private
git submodule update --init --recursive
```

## Step 2 — Prepare OPV2V dataset

Assume the OPV2V dataset root contains `train/`, `validate/`, `test/`.

```bash
export OPV2V_ROOT=/data/OPV2V
./scripts/prepare_opv2v_dataset.sh
```

This creates a symlink at `dataset/OPV2V` and a local cache folder at
`data/OPV2V/detected/`.

## Step 3 — Build stage‑1 detection caches

Stage‑1 caches are required for VIPS/CBM/FreeAlign/V2X‑Reg++.

```bash
# Default: export for test split
./scripts/build_opv2v_stage1_cache.sh

# If you need a custom split:
OPV2V_SPLITS=validate ./scripts/build_opv2v_stage1_cache.sh
```

Outputs (default):
- `data/OPV2V/detected/opv2v_camera_v2xvit_stage1_percav/test/stage1_boxes.json`
- `data/OPV2V/detected/opv2v_lidar_v2xvit_stage1/test/stage1_boxes.json`

Defaults used by the script (override via env if needed):
- camera model: `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope` (ckpt `net_epoch_bestval_at21.pth`)
- lidar model: `HEAL/opencood/logs/freealign_repro_opv2v_baseline` (ckpt `net_epoch_bestval_at27.pth`)

Hard gate (recommended before running any benchmark jobs):
```bash
./.micromamba/envs/py39/bin/python tools/validate_stage1_cache.py \
  --stage1 data/OPV2V/detected/opv2v_camera_v2xvit_stage1_percav/test/stage1_boxes.json \
  --expected-samples 2170 --require-contiguous-keys

./.micromamba/envs/py39/bin/python tools/validate_stage1_cache.py \
  --stage1 data/OPV2V/detected/opv2v_lidar_v2xvit_stage1/test/stage1_boxes.json \
  --expected-samples 2170 --require-contiguous-keys
```

> Note: OPV2V camera stage1 must be multi-agent (per-sample lists aligned with `cav_id_list`), otherwise pose solvers
> will silently degrade (e.g., `pose_solver.applied==0`), making method curves meaningless.

## Step 4 — Run full benchmark

```bash
# Full benchmark (noise sweep + dropout sweep)
./scripts/run_opv2v_fullbench.sh

# Smoke first (recommended): small subset + reduced noise points
SMOKE=1 ./scripts/run_opv2v_fullbench.sh

# Force online end-to-end semantics (register_and_fuse)
SOLVER_BACKEND=online_box RUNTIME_MODE=register_and_fuse ./scripts/run_opv2v_fullbench.sh

# Only noise sweep (skip dropout)
NO_DROPOUT=1 ./scripts/run_opv2v_fullbench.sh

# Limit GPUs
GPU_LIST=0,1,2,3 ./scripts/run_opv2v_fullbench.sh

# Manual sample cap for fast sanity
MAX_EVAL_SAMPLES=100 ./scripts/run_opv2v_fullbench.sh
```

The launcher writes logs and `run_state.jsonl` to:
```
outputs/full_bench_<RUN_ID>/
```

### Recommended: autopilot supervisor (async + auto-retry)

Use the supervisor launcher so abnormal exits are caught and retried automatically.

```bash
# Start async supervisor in tmux (default mode)
TAG=20260216_auto3 ./scripts/opv2v_autopilot.sh \
  --poll-seconds 120 --stall-polls 10 --max-smoke-retries 3 --max-full-retries 3

# Check status (supervisor + current autopilot attempt)
./scripts/opv2v_autopilot_status.sh 20260216_auto3
```

Optional Codex wake-up hook on abnormal exit:

```bash
# Best: target the exact current Codex CLI pane.
export CODEX_PANE="$(tmux display-message -p '#S:#I.#P')"

# Or target a whole tmux session.
# export CODEX_SESSION=<your_codex_tmux_session>

# Optional fallback: write alert directly to current terminal tty.
# export CODEX_TTY="$(tty)"

FAILURE_HOOK="./scripts/opv2v_wake_codex_hook.sh {incident} {tag} {attempt} {rc}" \
  TAG=20260216_auto4 ./scripts/opv2v_autopilot.sh
```

## Step 5 — Collect results

Each job writes AP yaml into the corresponding model directory:
- Camera model dir (default): `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/`
- LiDAR model dir (default): `HEAL/opencood/logs/freealign_repro_opv2v_baseline/`

YAML filename pattern:
```
AP030507_<pose_correction>_opv2v_fullbench_<RUN_ID>_*.yaml
```

## Notes

- `OPENCOOD_VOXEL_GPU=1` enables GPU voxelization (spconv required).
- `--num-workers` controls DataLoader parallelism (higher is faster, but more CPU).
- Stage‑1 exports are expensive; cache once and reuse.
- `SMOKE=1` sets `NOISE_LIST=1,5` and `MAX_EVAL_SAMPLES=100` unless you override them.
