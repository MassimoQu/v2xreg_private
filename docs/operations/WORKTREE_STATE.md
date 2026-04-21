# Worktree State (Private Tree): What Exists + What To Trust

Last updated: 2026-02-20

This repo is a **private working tree** for:
- reproducing paper numbers (esp. Table III on DAIR-V2X),
- running large-scale, audit-friendly benchmarks (DAIR / OPV2V),
- and exploring extensions (descriptors, pose correction, engineering speedups).

If you only read one thing: use `docs/operations/` as the source of truth and treat
`outputs/` as *artifacts only* (not versioned; do not rely on ad-hoc filenames).

## 1) Canonical Entry Points

- Object-level calibration runner (main pipeline):
  - `tools/run_calibration.py`
- DAIR batch experiment launcher:
  - `tools/run_dair_pipeline_experiments.py`
- Table III (paper3737=3737 pairs) reporting:
  - `tools/generate_table3_paper3737_repro_report.py`
- HKUST global registration benchmark wrapper:
  - `benchmarks/hkust_lidar_global_registration_benchmark.py`
- OPV2V full benchmark (autopilot / fast scheduler):
  - `tools/run_opv2v_fullbench_fast.py`
  - `tools/summarize_opv2v_fullbench_from_yaml.py`

## 2) Table III Reproduction (DAIR-V2X, paper3737)

Trust these docs:
- Live gap report (paper / closest / best, recomputed from jsonl):
  - `docs/operations/table3_paper3737_repro_status.md`
- Progress log and historical context:
  - `docs/operations/experiment_progress.md`

Key constraints enforced for fairness:
- Metrics are re-scored from a **single run’s** full-frame `matches.jsonl/details.jsonl`
  (3737/3737) and pair sets are validated against `data/data_info_dair_paper3737.json`.
- Success gate defaults to `te_re` (TE<thr AND RE<thr); this avoids mixed-gate artifacts.

Known gaps / mismatches (as of 2026-02-20):
- HKUST baselines (FGR / Quatro / Teaser++) still do not align with the paper’s time/accuracy.
- ICP/PICP full 3k×noise sweeps are still incomplete (smoke runs exist).

## 3) HEAL Integration + Pose Correction

HEAL is integrated as a git submodule at:
- `HEAL/`

Relevant status / reports live in:
- `docs/operations/heal_pose_alignment_noise_robustness.md`
- `HEAL/docs/pose_alignment_benchmark_master.md` (canonical benchmark master)

Current empirical summary:
- “Stable” pose corrections have not shown meaningful AP gains yet; mid vs late fusion curves are close.

## 4) OPV2V Full Benchmark (HEAL online/fullbench)

Canonical run id (do not mix with partial/smoke runs):
- `opv2v_autopilot_full_20260216_auto3_a1`

Artifacts:
- `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/`

Evidence + analysis docs:
- `docs/operations/opv2v_benchmark_repro.md`
- `docs/operations/opv2v_fullbench_masterplan_execution_status_20260217.md`
- `docs/operations/opv2v_fullbench_comparative_analysis_20260217.md`
- `docs/operations/benchmark_execution_status_20260219.md`

## 5) Descriptor / Feature Extensions

Scope:
- camera descriptors (pixel/HOG/ResNet/DINOv2),
- BEV descriptors,
- hint/seed/weighted matching variants.

Tracking doc:
- `docs/operations/experiment_progress.md`

Current guidance:
- Many hint/seed/weighted variants were negative; avoid re-running without a new hypothesis.

## 6) Benchmark Hygiene (What Is Comparable)

Before comparing runs, read:
- `docs/operations/benchmark_inventory.md`

Rules of thumb:
- Only compare **canonical** runs with consistent splits + caches + noise lists.
- Do not mix per-CAV caches or max_eval_samples smoke runs with full runs.

## 7) “Next” (High-Value TODOs)

- Close HKUST baseline mismatch:
  - align time accounting and correspondence budget against the paper.
- Finish ICP/PICP full sweeps (paper3737, all noises) and regenerate Table III report.
- Unblock GPU-dependent BEV feature dumps (or document a CPU fallback).

