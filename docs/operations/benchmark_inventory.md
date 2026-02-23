# Benchmark Inventory & Hygiene

Last updated: 2026-02-20

This document consolidates all benchmark artifacts that currently exist in the repo,
classifies them as **canonical (fair/official)** or **non‑canonical (partial/legacy)**,
and points to the correct artifacts for comparison. Use this file as the source of truth
before making any cross‑run comparison.

## Legend (What “Canonical / Fair” Means Here)

A benchmark is considered **canonical** if it:
- uses the **full evaluation split** (no max_eval_samples cap),
- keeps **noise injection**, **comm_range**, and **stage1 cache** consistent,
- includes **bounds** (baseline + oracle) and **single_comm0** where applicable,
- records enough metadata to reproduce (model dir, stage1 cache, noise lists, etc.).

Everything else is **non‑canonical** (smoke runs, partials, per‑CAV caches, missing metadata, etc.).


## Canonical / Fair Benchmarks (Use These for Comparisons)

### A) HEAL Pose Alignment + Coop Benchmark (DAIR‑V2X, Full Sweep)
- **Status:** complete, canonical
- **Doc:** `HEAL/docs/pose_alignment_report_2026-02-05.md`
- **Fairness review:** `HEAL/docs/pose_alignment_fairness_review.md`
- **Master summary:** `HEAL/docs/pose_alignment_benchmark_master.md`
- **Artifacts:**
  - Results: `outputs/pose_sweep_1to10_full_results.jsonl`
  - Results: `outputs/pose_dropout_1to10_full_results.jsonl`
  - Summaries: `outputs/pose_sweep_1to10_full_summary.md`, `outputs/pose_dropout_1to10_full_summary.md`
  - Plots: `outputs/pose_sweep_1to10_full_plots/`, `outputs/pose_dropout_1to10_full_plots/`
- **Key settings:**
  - Full test set, paired sweep (pos 1–10, rot 1–10 for camera / rot=0 for lidar)
  - Noise target: non‑ego
  - comm_range_override=100
  - baseline + oracle + single_comm0 included
  - Same stage1 cache per modality across methods
- **Latest DAIR noise10 refresh (same scope):**
  - `outputs/pose_sweep_1to10_full_gpuvoxel20260218_results.jsonl`
  - Unified AP+pose table: `outputs/benchmark_unified_20260220/dair_noise10_ap_reg.csv`


## Non‑Canonical / Partial Benchmarks (Do Not Mix With Canonical)

### B) Fast / Partial Sweeps (DAIR‑V2X, max_eval_samples=100)
- **Status:** partial, not comparable to canonical
- **Docs:**
  - `HEAL/docs/pose_alignment_report_2026-01-29.md` (noise 0–5, dropout 1–5)
  - `HEAL/docs/pose_alignment_report_2026-02-01.md` (noise 1–10, dropout 0.2)
- **Artifacts:**  
  - `outputs/pose_sweep_1to10_results.jsonl`  
  - `outputs/pose_dropout_1to10_results.jsonl`  
  These lack key metadata (stage1 path / noise list), so they are **non‑canonical**.

### C) Per‑CAV Stage1 Sweeps (Camera‑only)
- **Status:** full sweep but **not comparable** to canonical (different stage1 cache)
- **Artifacts:**  
  - `outputs/pose_sweep_1to10_camera_percav_full_results.jsonl`  
  - `outputs/pose_dropout_1to10_camera_percav_full_results.jsonl`  
  - Plots/logs: `outputs/pose_*_camera_percav_full_*`
- **Reason non‑canonical:** per‑CAV stage1 cache changes the input distribution; only camera modality.

### D) Benchmark Gate / Artifact Smoke Runs
- **Status:** smoke/gate checks, not canonical
- **Artifacts:**
  - `outputs/benchmark_results_20260208_artifacts_smoke.jsonl`
  - `outputs/benchmark_results_20260208_artifacts_ext_smoke.jsonl`
  - `outputs/benchmark_results_20260208_artifacts_final_smoke.jsonl`
  - `outputs/benchmark_results_20260208_artifacts_v11_smoke.jsonl`
  - `outputs/benchmark_results_20260209_real_runtime_gate.jsonl`
  - Gate reports: `outputs/benchmark_gate_report_*.md/.json`
- **Reason non‑canonical:** designed for regression gating, not full‑fidelity evaluation.

### E) Hyper‑parameter Search Snapshots
- **Status:** partial, not canonical
- **Artifacts:** `outputs/hparam_search_results.jsonl`


## OPV2V Canonical Benchmark

### F) OPV2V Full Benchmark (OPV2V, online/fullbench)
- **Status:** complete, canonical
- **Trusted run id:** `opv2v_autopilot_full_20260216_auto3_a1`
- **Artifacts (source of truth):**
  - Run dir: `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/`
  - Completion events: `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/run_state.jsonl`
  - Results JSON: `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/results_ap50_from_yaml.json`
  - Plots: `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/plots_yaml/`
  - Config snapshot: `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/config_snapshot.json`
- **Docs:**
  - Evidence: `docs/operations/opv2v_fullbench_evidence_autopilot_20260216_auto3.md`
  - Masterplan execution status: `docs/operations/opv2v_fullbench_masterplan_execution_status_20260217.md`
  - Comparative analysis: `docs/operations/opv2v_fullbench_comparative_analysis_20260217.md`
- **Notes / caveats:**
  - For completion, **do not** trust `task_summary.json` (can be stale); use `run_state.jsonl` instead.
  - Current `run_state.jsonl` includes post-append camera `v2xregpp_occhint` tasks; core cross-modal scope remains complete.
  - "All‑GPU end‑to‑end" core lanes are now covered by gate artifacts (`outputs/benchmark_gate_report_20260220_fullgpu_gate_rerun2.md`, `outputs/benchmark_gate_report_20260220_fullgpu_featrefine_gate.md`), both with T06 `bad_fallback=[]`.
  - Unified AP+pose table: `outputs/benchmark_unified_20260220/opv2v_dual_suite_ap_reg.csv`


## How to Compare (Recommended)

1) **Use Section A only** for “official” comparisons across methods.  
2) **Do not mix** per‑CAV stage1 results (Section C) with canonical runs.  
3) **Do not compare** fast/partial sweeps (Section B) against full sweeps.  
4) **OPV2V** should be compared only after AP values are validated.
5) For unified cross-dataset comparisons, use:
   - `docs/operations/unified_benchmark_contract_and_comparison_20260220.md`
   - `outputs/benchmark_unified_20260220/coverage_checks.json`
   - `outputs/benchmark_fullmatrix_20260220/combined_noise_curve_long.csv`
   - `outputs/benchmark_fullmatrix_20260220/plots/`


## TODO (to make the catalog complete)
- (Done) Finish OPV2V full benchmark and validate AP correctness.
- (Done) Add lightweight unified manifest/tables for DAIR + OPV2V:
  - `outputs/benchmark_unified_20260220/*.csv`
  - `outputs/benchmark_unified_20260220/coverage_checks.json`
- (Done) Add a unified full-matrix plotting/report script with fixed color/linestyle conventions:
  - `tools/build_fullmatrix_benchmark_report.py`
  - `outputs/benchmark_fullmatrix_20260220/*`
- Continue full-condition append runs for with-init / HKUST downstream AP lines:
  - `docs/operations/fullmatrix_init_noinit_hkust_benchmark_status_20260220.md`
