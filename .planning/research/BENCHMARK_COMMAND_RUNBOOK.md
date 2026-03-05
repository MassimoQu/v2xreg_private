# Benchmark Command Runbook (Three Datasets)

**Date:** 2026-03-04
**Contract intent:** run smoke first, then full runs, with explicit semantics and evidence artifacts.

## 0) Shared Preconditions

- Use repo root: `/home/qqxluca/projects/v2xreg_private`
- Use python env: `./.micromamba/envs/py39/bin/python`
- Keep `--pose-compare-*` pins explicit for reproducibility.
- Record source-of-truth files per run:
  - `manifest.json` / `config_snapshot.json`
  - `results_ap50_from_yaml.json` (or dataset equivalent)
  - `run_state.jsonl` (for OPV2V fullbench)
  - `summary.md`

## 1) DAIR-V2X

### Smoke

```bash
./.micromamba/envs/py39/bin/python -u tools/run_dair_core_benchmark.py \
  --tag dair_core_smoke_$(date +%Y%m%d_%H%M%S) \
  --gpus 0,1 \
  --max-per-gpu 1 \
  --comm-range 100 \
  --comm-range-gating clean \
  --max-eval-samples 200 \
  --pose-compare-distance-threshold 3.0 \
  --pose-current-precision-threshold 1.8 \
  --pose-min-precision-improvement 0.0 \
  --pose-min-matched-improvement 0
```

### Full

```bash
./.micromamba/envs/py39/bin/python -u tools/run_dair_core_benchmark.py \
  --tag dair_core_canonical_$(date +%Y%m%d_%H%M%S) \
  --gpus 0,1,2,3 \
  --max-per-gpu 2 \
  --comm-range 100 \
  --comm-range-gating clean \
  --pose-compare-distance-threshold 3.0 \
  --pose-current-precision-threshold 1.8 \
  --pose-min-precision-improvement 0.0 \
  --pose-min-matched-improvement 0
```

## 2) OPV2V

### Smoke

```bash
./.micromamba/envs/py39/bin/python -u tools/run_opv2v_fullbench_fast.py \
  --run-id opv2v_core_smoke_$(date +%Y%m%d_%H%M%S) \
  --gpus 0,1 \
  --max-per-gpu 1 \
  --num-workers 2 \
  --solver-backend online_box \
  --runtime-mode register_and_fuse \
  --pose-source noisy_input \
  --comm-range-override 70 \
  --comm-range-gating noisy \
  --max-eval-samples 200 \
  --pose-compare-distance-threshold 3.0 \
  --pose-current-precision-threshold 1.8 \
  --pose-min-precision-improvement 0.0 \
  --pose-min-matched-improvement 0
```

### Full

```bash
./.micromamba/envs/py39/bin/python -u tools/run_opv2v_fullbench_fast.py \
  --run-id opv2v_core_canonical_$(date +%Y%m%d_%H%M%S) \
  --gpus 0,1,2,3,4,5 \
  --max-per-gpu 2 \
  --num-workers 4 \
  --solver-backend online_box \
  --runtime-mode register_and_fuse \
  --pose-source noisy_input \
  --comm-range-override 70 \
  --comm-range-gating noisy \
  --pose-compare-distance-threshold 3.0 \
  --pose-current-precision-threshold 1.8 \
  --pose-min-precision-improvement 0.0 \
  --pose-min-matched-improvement 0
```

## 3) V2V4Real

### Smoke

```bash
./.micromamba/envs/py39/bin/python -u tools/run_v2v4real_core_benchmark.py \
  --tag v2v4real_core_smoke_$(date +%Y%m%d_%H%M%S) \
  --gpus 0,1 \
  --max-per-gpu 1 \
  --comm-range 70 \
  --comm-range-gating clean \
  --max-eval-samples 200 \
  --pose-compare-distance-threshold 3.0 \
  --pose-current-precision-threshold 1.8 \
  --pose-min-precision-improvement 0.0 \
  --pose-min-matched-improvement 0
```

### Full

```bash
./.micromamba/envs/py39/bin/python -u tools/run_v2v4real_core_benchmark.py \
  --tag v2v4real_core_canonical_$(date +%Y%m%d_%H%M%S) \
  --gpus 0,1,2,3 \
  --max-per-gpu 1 \
  --comm-range 70 \
  --comm-range-gating clean \
  --pose-compare-distance-threshold 3.0 \
  --pose-current-precision-threshold 1.8 \
  --pose-min-precision-improvement 0.0 \
  --pose-min-matched-improvement 0
```

## 4) Cloud Export / Validate / Gate / Sync

### 4.1 Export transition bundles from local run dirs

```bash
./.micromamba/envs/py39/bin/python -u tools/export_transition_bundles_to_eval_v2_1.py \
  --source outputs/dair_core_<RUN_TAG>/camera \
  --source outputs/full_bench_<OPV2V_RUN_ID> \
  --source outputs/v2v4real_core_<RUN_TAG> \
  --output-root /home/qqxluca/vggt_series_4_coop/eval_runs/inbox/local_transition \
  --pack dev100 --mode M0 --noise N2 --dropout D0 --seed 0
```

### 4.2 Validate and gate each bundle

```bash
cd /home/qqxluca/vggt_series_4_coop
for B in eval_runs/inbox/local_transition/*; do
  ./venv/bin/python scripts/validate_eval_bundle.py --bundle "$B"
  ./venv/bin/python scripts/compute_gate_status.py --bundle "$B"
done
```

### 4.3 Sync to Project #2 (minimal noise mode)

```bash
cd /home/qqxluca/vggt_series_4_coop
./venv/bin/python scripts/project_sync_github.py \
  --sync-mode minimal \
  --gate-status-filter all \
  --include-packs dev100 report500 \
  --limit 20
```

## 5) Stop-Loss Rules

- Stop full run launch if smoke fails preflight or misses source-of-truth artifacts.
- Stop cloud sync if bundle validation is invalid (fix structure first).
- Stop standard decision if fewer than 3 candidate standards are evaluated.
