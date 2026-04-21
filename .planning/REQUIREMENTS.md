# Requirements: Core Benchmark Closure and Cloud Standard Alignment

**Defined:** 2026-03-04
**Core Value:** Produce one trusted, decision-grade benchmark baseline across three datasets and sync it to cloud governance.

## v1 Requirements

### Contract and Semantics

- [ ] **STD-01**: A single benchmark contract document is pinned and referenced by every run (commands, semantics, redlines, DoD).
- [ ] **STD-02**: All dataset runs use explicit compare-current thresholds and explicit comm-range gating (no implicit defaults).
- [ ] **STD-03**: Single baseline semantics are fixed to ego-only forward pass and not comm-range shortcuts.

### Dataset Benchmark Delivery

- [ ] **BEN-01**: DAIR-V2X canonical run is completed with manifest, plots, and summary artifacts.
- [ ] **BEN-02**: OPV2V canonical run is completed with run state, merged outputs, and summary artifacts.
- [ ] **BEN-03**: V2V4Real canonical run is completed with comparable lane coverage and summary artifacts.
- [ ] **BEN-04**: Every dataset has at least one smoke run before full run, with explicit rerun criteria.

### Evidence Quality

- [ ] **EVD-01**: Source-of-truth artifacts are defined and checked per run (not log-grep based completion).
- [ ] **EVD-02**: Failure reason decomposition exists for major methods at key noise points.
- [ ] **EVD-03**: Each dataset has a closure report with pass/fail against DoD and residual risk notes.

### Cloud Synchronization and Standard Selection

- [ ] **CLD-01**: Each canonical run is exported to cloud bundle format with traceable source linkage.
- [ ] **CLD-02**: Validate and gate reports are generated and archived for each exported run.
- [ ] **CLD-03**: Cloud standard candidates are compared with a weighted decision matrix.
- [ ] **CLD-04**: A single standard strategy is selected and published with rollout steps.
- [ ] **CLD-05**: Project #2 sync is executed and produces updated run/task cards.

## v2 Requirements

### Geometry Completeness Upgrade

- **EXT-01**: Replace transition depth/scale placeholders with object-level metrics for gate-passing eligibility.
- **EXT-02**: Integrate robustness reporting that satisfies full route-decision gate conditions.

## Out of Scope

| Feature | Reason |
|---------|--------|
| New detector training research track | Not required to close benchmark contract and cloud governance sync |
| New dataset onboarding | Dilutes closure focus for current backlog |
| Rebuilding cloud governance stack | Existing coopVGGT governance scripts already exist |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| STD-01 | Phase 1 | Pending |
| STD-02 | Phase 1 | Pending |
| STD-03 | Phase 1 | Pending |
| BEN-01 | Phase 2 | Pending |
| BEN-04 | Phase 2 | Pending |
| BEN-02 | Phase 3 | Pending |
| BEN-04 | Phase 3 | Pending |
| BEN-03 | Phase 4 | Pending |
| EVD-02 | Phase 4 | Pending |
| EVD-01 | Phase 5 | Pending |
| CLD-01 | Phase 5 | Pending |
| CLD-02 | Phase 5 | Pending |
| CLD-05 | Phase 5 | Pending |
| CLD-03 | Phase 6 | Pending |
| CLD-04 | Phase 6 | Pending |
| EVD-03 | Phase 6 | Pending |

**Coverage:**
- v1 requirements: 15 total
- Mapped to phases: 15
- Unmapped: 0

---
*Requirements defined: 2026-03-04*
*Last updated: 2026-03-04 after initial structuring*
