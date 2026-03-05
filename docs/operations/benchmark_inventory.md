# Benchmark Inventory & Hygiene

Last updated: 2026-03-01

This document consolidates all benchmark artifacts that currently exist in the repo,
classifies them as **canonical (fair/official)** or **non‑canonical (partial/legacy)**,
and points to the correct artifacts for comparison. Use this file as the source of truth
before making any cross‑run comparison.

## Legend (What “Canonical / Fair” Means Here)

A benchmark is considered **canonical** if it:
- uses the **full evaluation split** (no max_eval_samples cap),
- keeps **noise injection**, **comm_range**, and **stage1 cache** consistent,
- includes **bounds** (baseline + oracle) and **single_ego_only** (`--force-ego-input-only`, noise=0) where applicable,
- records enough metadata to reproduce (model dir, stage1 cache, noise lists, etc.).

Everything else is **non‑canonical** (smoke runs, partials, per‑CAV caches, missing metadata, etc.).


## Canonical / Fair Benchmarks (Use These for Comparisons)

### A) HEAL Pose Alignment + Coop Benchmark (DAIR‑V2X, Full Sweep)
- **Status:** complete, canonical **for cooperative methods** (the legacy single baseline in this run is `single_comm0`; do not use it as a fair "single vs coop" bound)
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
  - baseline + oracle included; **legacy** `single_comm0` included (canonical single is now `single_ego_only`, see `docs/operations/benchmark_semantics.md`)
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
- **Status:** legacy / provisional (NOT canonical)
- **Legacy run id (historical):** `opv2v_autopilot_full_20260216_auto3_a1`
- **Why non‑canonical (as of 2026‑02‑24):**
  - `comm_range_gating=auto` under online runtime (semantic drift risk; not “latest unified benchmark condition”)
  - mixed‑env + mid‑run fixes mixed into the same run_id
  - init/no-init/HKUST append scope is incomplete (`run_state.jsonl` has unmatched starts; lidar/drop20 HKUST not present)
  - many `AP030507_*.yaml` are legacy schema without `pose_provider_applied_count` (no-op cannot be gated)
- **Artifacts (source of truth, historical only):**
  - Run dir: `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/`
  - Completion events: `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/run_state.jsonl`
  - Results JSON: `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/results_ap50_from_yaml.json`
  - Plots: `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/plots_yaml/`
  - Config snapshot: `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/config_snapshot.json`
- **Docs (historical context):**
  - `docs/operations/opv2v_append_partial_results_20260222.md`
  - `docs/operations/imagematch_initfree_remote_audit_20260223.md`

### G) OPV2V Unified Fullbench (Target Canonical)
- **Status:** pending (smoke passed; full not launched yet)
- **Smoke run (mechanism validation):**
  - `outputs/full_bench_opv2v_unified_smoke_20260223_fix1/`
- **Plan contract / preflight gates:**
  - `docs/operations/opv2v_unified_fullbench_plan_20260223.md`
  - `docs/operations/benchmark_pending_runs_and_plan_20260224.md`


## How to Compare (Recommended)

1) **Use Section A only** for “official” comparisons across methods.  
2) **Do not mix** per‑CAV stage1 results (Section C) with canonical runs.  
3) **Do not compare** fast/partial sweeps (Section B) against full sweeps.  
4) **OPV2V** should be compared only after AP values are validated.
5) For unified cross-dataset comparisons:
   - Use `docs/operations/benchmark_pending_runs_and_plan_20260224.md` as the “what to run next” contract.
   - Treat `docs/operations/unified_benchmark_contract_and_comparison_20260220.md` as **legacy** for OPV2V (DAIR part still useful as reference).


## TODO (to make the catalog complete)
- (TODO) Run OPV2V unified fullbench under frozen semantics (new run_id; git clean; comm_range_gating fixed).
- (Done) Add lightweight unified manifest/tables for DAIR + OPV2V:
  - `outputs/benchmark_unified_20260220/*.csv`
  - `outputs/benchmark_unified_20260220/coverage_checks.json`
- (Done) Add a unified full-matrix plotting/report script with fixed color/linestyle conventions:
  - `tools/build_fullmatrix_benchmark_report.py`
  - `outputs/benchmark_fullmatrix_20260220/*`
- Continue full-condition append runs for with-init / HKUST downstream AP lines:
  - `docs/operations/fullmatrix_init_noinit_hkust_benchmark_status_20260220.md`
