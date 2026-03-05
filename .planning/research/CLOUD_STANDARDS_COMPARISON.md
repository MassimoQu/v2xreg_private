# Cloud Standards Comparison (Draft)

**Date:** 2026-03-04
**Objective:** pick the cloud-facing standard strategy that best supports three-dataset benchmark closure plus governance traceability.

## Candidate Standards

1. **UNIFIED_CORE_MASTER_SPEC_V1**
   - Source: `docs/operations/unified_core_benchmark_master_spec_results_v1_20260302.md`
   - Strength: strongest local benchmark comparability and semantic freeze.
   - Gap: not a full cloud governance protocol by itself.

2. **FULLY_FAIR_V2XVIT_PLAN_V1**
   - Source: `docs/operations/fully_fair_v2xvit_core_benchmark_plan_v1_20260227.md`
   - Strength: strong fairness framing for method-level comparison.
   - Gap: limited direct compatibility with cloud gate pipeline.

3. **COOPVGGT_EVAL_V2_1**
   - Source: `/home/qqxluca/vggt_series_4_coop/configs/eval_protocol_v2_1.yaml`
   - Strength: complete cloud governance chain (validate -> gate -> leaderboard -> project sync).
   - Gap: depth/scale requirements can block current transition exports.

## Weighted Criteria

| Criterion | Weight | UNIFIED_CORE_MASTER_SPEC_V1 | FULLY_FAIR_V2XVIT_PLAN_V1 | COOPVGGT_EVAL_V2_1 |
|-----------|--------|------------------------------|-----------------------------|--------------------|
| Local comparability and semantic freeze | 0.30 | 5 | 4 | 3 |
| Cloud governance compatibility | 0.30 | 2 | 2 | 5 |
| Operational readiness with existing scripts | 0.20 | 4 | 3 | 4 |
| Decision traceability in project board | 0.10 | 2 | 2 | 5 |
| Upgrade path to route-decision quality | 0.10 | 3 | 3 | 4 |
| **Weighted total** | **1.00** | **3.5** | **3.0** | **4.3** |

Scoring scale: 1 (weak) to 5 (strong).

## Recommendation

Use a **two-layer strategy**:

- **Execution contract (local):** UNIFIED_CORE_MASTER_SPEC_V1
- **Cloud governance contract (cloud):** COOPVGGT_EVAL_V2_1

This keeps local fairness strict while making every result visible in the same cloud decision pipeline.

## Decision Gate

A final standard decision is considered complete when all are true:

- [ ] All three dataset canonical runs have cloud bundles and gate reports.
- [ ] At least one cycle of Project #2 sync is verified.
- [ ] A rollout note is published with fallback policy (transition bundle mode vs full metric mode).

## Open Risks

- Depth/scale placeholders in transition bundles can keep gates blocked even when local benchmark quality is high.
- If run metadata is incomplete, cloud comparability can still be questioned despite formal sync.
