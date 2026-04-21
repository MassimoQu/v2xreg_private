# Configs Index

This repo accumulates many experiment YAMLs. To avoid “configs sprawl”, they are
grouped by topic under `configs/`.

If you are starting fresh, use the **canonical entry configs** listed below and
only then branch out to variants.

## Layout

- `configs/dair/`
  - DAIR-V2X object-level pipeline configs.
  - `detection/`: detection-box pipelines and variants
  - `midfusion/`, `late/`, `gt/`, `candidate/`, `variants/`, `misc/`: historical + ablations
- `configs/paper3737/`
  - Paper-aligned reproduction configs for the 3737-pair Table III setup.
  - `dair/`: DAIR-V2X (paper3737) configs
  - `hkust/`: HKUST baseline configs used in Table III comparisons
- `configs/hkust/`
  - HKUST dataset pipelines and the LiDAR-Registration-Benchmark wrapper configs.
- `configs/camera/`
  - Camera-only descriptor / detector experiments.
  - `desc/`, `det/`, `loftr/`, `gt/`, `misc/`
- `configs/exp/`
  - One-off ablations that don’t belong to a stable track.
- `configs/_archive/`
  - Kept for record; do not use for new runs.

## Canonical Entry Configs (Recommended)

### A) DAIR-V2X LiDAR (GT boxes, baseline)

```bash
python tools/run_calibration.py --config configs/dair/pipeline.yaml --print
```

### B) DAIR-V2X LiDAR (detector boxes, HEAL stage-1 cache)

```bash
python tools/run_calibration.py --config configs/dair/detection/pipeline_detection.yaml --print
```

### C) HKUST object-level pipeline demo

```bash
python tools/run_calibration.py --config configs/hkust/pipeline_hkust.yaml --print
```

### D) Table III (paper3737=3737 pairs) reproduction

See:
- `docs/operations/table3_paper3737_repro_status.md`
- `docs/operations/experiment_reproduction.md`

Typical commands:
```bash
python tools/run_calibration.py --config configs/paper3737/dair/pipeline_paper3737_gt15.yaml --print
python tools/run_calibration.py --config configs/paper3737/dair/pipeline_paper3737_pp15.yaml --print
python tools/run_calibration.py --config configs/paper3737/dair/pipeline_paper3737_sc15.yaml --print
```

## Notes

- Do not compare runs across configs unless they share the same split, stage1 cache,
  and noise list. See `docs/operations/benchmark_inventory.md`.

