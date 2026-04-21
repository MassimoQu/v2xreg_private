# Roadmap: Core Benchmark Closure and Cloud Standard Alignment

## Overview

This roadmap closes the benchmark backlog by locking one execution contract, running three dataset benchmarks with smoke-first gates, producing evidence-grade summaries, and synchronizing outputs to cloud governance. The final phase picks and publishes the standard strategy that best matches local fairness and cloud decision requirements.

## Scope and Non-goals

**Scope**
- Close benchmark execution and evidence for DAIR-V2X, OPV2V, and V2V4Real.
- Synchronize benchmark artifacts into cloud governance (validate, gate, project sync).
- Select and publish one cloud standard strategy for ongoing runs.

**Non-goals**
- No new dataset onboarding in this milestone.
- No detector architecture retraining as a prerequisite for closure.
- No protocol rewrite of external cloud governance tools.

## Semantics Freeze

The following semantics are frozen for comparability:
- Explicit `comm-range-gating` (no implicit `auto` for canonical online runs).
- Explicit compare-current threshold pins (`pose-compare-distance-threshold`, `pose-current-precision-threshold`, and improvement pins).
- Single-agent bound semantics use ego-only forward path (not comm-range shortcut).
- Smoke-first and stop-loss gates must pass before full-scale benchmark launches.

## Source of Truth

Completion and correctness must be proven by run artifacts, not console logs:
- Dataset run artifacts under `outputs/*` (`manifest.json` or `config_snapshot.json`, result JSON, plots, and `summary.md`).
- OPV2V scheduler state in `run_state.jsonl` for task-level execution truth.
- Cloud governance artifacts in `/home/qqxluca/vggt_series_4_coop/eval_runs/_reports/{validate,gate}` and project sync output.

## Phases

- [ ] **Phase 1: Contract Freeze and Inventory** - Lock semantics, source-of-truth, and run contracts.
- [ ] **Phase 2: DAIR-V2X Canonical Closure** - Complete DAIR smoke/full run and closure artifacts.
- [ ] **Phase 3: OPV2V Canonical Closure** - Complete OPV2V smoke/full run and closure artifacts.
- [ ] **Phase 4: V2V4Real Canonical Closure** - Complete V2V4Real run closure and missing evidence gaps.
- [ ] **Phase 5: Cloud Bundle and Sync Pipeline** - Export runs, validate/gate, sync to Project #2.
- [ ] **Phase 6: Standard Decision and Rollout** - Compare standards, select one, and publish execution rules.

## Phase Details

### Phase 1: Contract Freeze and Inventory
**Goal**: Build one executable contract and complete preflight checks before expensive runs.
**Depends on**: Nothing (first phase)
**Requirements**: STD-01, STD-02, STD-03
**Success Criteria**:
  1. One pinned contract doc is selected and referenced by all runbooks.
  2. All three datasets have validated input contracts (paths, stage1, sample counts).
  3. Smoke/full stop-loss criteria are documented and accepted.
**Plans**: 3 plans

Plans:
- [ ] 01-01: Freeze contract references and redlines in `.planning/research/BENCHMARK_COMMAND_RUNBOOK.md`.
- [ ] 01-02: Inventory latest valid run artifacts and identify stale/non-canonical outputs.
- [ ] 01-03: Run preflight gate audit and produce a go/no-go checklist.

### Phase 2: DAIR-V2X Canonical Closure
**Goal**: Produce a complete DAIR benchmark run with canonical semantics and summary evidence.
**Depends on**: Phase 1
**Requirements**: BEN-01, BEN-04
**Success Criteria**:
  1. DAIR smoke run passes all preflight and artifact gates.
  2. DAIR full run produces manifest, result json, plots, and summary.
  3. DoD report identifies pass/fail and any remaining blockers.
**Plans**: 3 plans

Plans:
- [ ] 02-01: Execute DAIR smoke run with frozen flags and verify source-of-truth artifacts.
- [ ] 02-02: Execute DAIR full run and summarize outputs.
- [ ] 02-03: Write DAIR closure report with risks and rerun criteria.

### Phase 3: OPV2V Canonical Closure
**Goal**: Produce a complete OPV2V benchmark run with unified summary artifacts.
**Depends on**: Phase 1
**Requirements**: BEN-02, BEN-04
**Success Criteria**:
  1. OPV2V smoke run passes preflight and semantics checks.
  2. OPV2V full run has complete run state, merged yaml/json, and summary index.
  3. OPV2V closure report documents residual technical debt and rerun triggers.
**Plans**: 3 plans

Plans:
- [ ] 03-01: Execute OPV2V smoke run and verify task-level state integrity.
- [ ] 03-02: Execute OPV2V full run and generate summary artifacts.
- [ ] 03-03: Produce OPV2V closure report and unresolved issue list.

### Phase 4: V2V4Real Canonical Closure
**Goal**: Complete V2V4Real closure including missing lane/evidence gaps.
**Depends on**: Phase 1
**Requirements**: BEN-03, EVD-02
**Success Criteria**:
  1. V2V4Real run is completed under the same contract semantics as other datasets.
  2. Missing lane/evidence gaps are explicitly resolved or blocked with evidence.
  3. Failure-reason decomposition is produced at anchor noise points.
**Plans**: 3 plans

Plans:
- [ ] 04-01: Execute V2V4Real smoke/full run with contract parity checks.
- [ ] 04-02: Fill camera/lidar lane completeness gap or produce hard blocker evidence.
- [ ] 04-03: Add failure-reason decomposition report for key methods.

### Phase 5: Cloud Bundle and Sync Pipeline
**Goal**: Convert canonical local outputs into cloud-governed artifacts and sync cards.
**Depends on**: Phases 2, 3, 4
**Requirements**: EVD-01, CLD-01, CLD-02, CLD-05
**Success Criteria**:
  1. Bundle exports exist for all three datasets and link back to source runs.
  2. Validate and gate reports are generated for each bundle.
  3. Project #2 sync reports updated items with deterministic filters.
**Plans**: 3 plans

Plans:
- [ ] 05-01: Export DAIR/OPV2V/V2V4Real bundles via transition exporter.
- [ ] 05-02: Run validate+gate scripts and archive reports.
- [ ] 05-03: Sync to Project #2 with minimal-noise mode and record sync result.

### Phase 6: Standard Decision and Rollout
**Goal**: Decide the cloud standard strategy and publish an operational rollout contract.
**Depends on**: Phase 5
**Requirements**: CLD-03, CLD-04, EVD-03
**Success Criteria**:
  1. At least three candidate standards are compared with weighted criteria.
  2. One selected standard strategy is justified against current project needs.
  3. Rollout document includes migration steps, fallback, and rerun triggers.
**Plans**: 3 plans

Plans:
- [ ] 06-01: Build weighted comparison matrix for cloud standard candidates.
- [ ] 06-02: Publish selected strategy and decision memo.
- [ ] 06-03: Create rollout checklist and update closure status dashboard.

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Contract Freeze and Inventory | 0/3 | Not started | - |
| 2. DAIR-V2X Canonical Closure | 0/3 | Not started | - |
| 3. OPV2V Canonical Closure | 0/3 | Not started | - |
| 4. V2V4Real Canonical Closure | 0/3 | Not started | - |
| 5. Cloud Bundle and Sync Pipeline | 0/3 | Not started | - |
| 6. Standard Decision and Rollout | 0/3 | Not started | - |
