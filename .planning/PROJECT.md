# Core Benchmark Closure and Cloud Standard Alignment

## What This Is

This initiative turns the current benchmark backlog into an execution contract that can be audited and synchronized to cloud governance. The scope is the three active datasets in this repo (DAIR-V2X, OPV2V, V2V4Real), with a single rule: every result must be reproducible, explainable, and cloud-sync ready.

## Core Value

Produce one trusted, decision-grade benchmark baseline across three datasets and make it visible in cloud project governance without ambiguity.

## Requirements

### Validated

- ✓ OPV2V fullbench has run artifacts with source-of-truth state files (`run_state.jsonl`) in `outputs/full_bench_*`.
- ✓ DAIR and V2V4Real have core benchmark scripts and prior run outputs in `outputs/dair_core_*` and `outputs/v2v4real_core_*`.
- ✓ Transition cloud export path exists via `tools/export_transition_bundles_to_eval_v2_1.py`.

### Active

- [ ] Run three dataset benchmarks under one frozen contract (semantics + compare pins + SoT artifacts).
- [ ] Fill remaining P0 evidence gaps (failure reason decomposition, missing summaries, lane completeness).
- [ ] Export benchmark results to cloud bundles and keep validate/gate reports linked to source runs.
- [ ] Decide and publish the standard strategy to use in cloud governance.

### Out of Scope

- Rewriting benchmark pipelines from scratch - use existing scripts and contracts.
- Expanding to new datasets beyond DAIR-V2X, OPV2V, V2V4Real in this milestone.
- Chasing leaderboard gains without first passing contract and evidence gates.

## Context

Current repo status (as of 2026-03-04) already includes multiple benchmark outputs and progress docs, but closure is fragmented. Existing references indicate contract drift risk, partial summaries, and cloud-sync gaps. This project formalizes one execution path from local run to cloud decision artifact.

Primary source references:
- `docs/operations/unified_core_benchmark_master_spec_results_v1_20260302.md`
- `docs/operations/core_benchmark_progress_p0_closure_20260304.md`
- `docs/operations/cloud_reintegration_pack_20260301.md`
- `docs/operations/fully_fair_v2xvit_core_benchmark_plan_vs_eval_v2_1_20260228.md`

## Constraints

- **Compute**: full benchmark sweeps are expensive; smoke-first and stop-loss gates are mandatory.
- **Contract**: semantic drift (comm-range, runtime mode, single baseline semantics) invalidates comparability.
- **Data**: each dataset path, stage1 cache, and expected sample count must be verified before full runs.
- **Governance**: cloud sync requires bundle compliance and token permissions for project update scripts.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Keep dataset scope fixed to DAIR-V2X, OPV2V, V2V4Real | Avoid backlog sprawl and enforce closure | ✓ Good |
| Use smoke-first then full-run gates for each dataset | Prevent expensive invalid runs | ✓ Good |
| Treat cloud sync as first-class deliverable, not post-hoc | Work is considered incomplete without cloud traceability | ✓ Good |
| Evaluate cloud standard options explicitly before final selection | Avoid silent protocol mismatch across teams | - Pending |

---
*Last updated: 2026-03-04 after GSD initialization*
