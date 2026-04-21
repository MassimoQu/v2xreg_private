# Run Inventory (2026-03-04)

## Scope

Dataset scope is fixed to:
- DAIR-V2X
- OPV2V
- V2V4Real

Primary references:
- `docs/operations/core_benchmark_progress_p0_closure_20260304.md`
- `docs/operations/cloud_reintegration_pack_20260301.md`

## Canonical Candidates

### DAIR-V2X

- Candidate: `outputs/dair_core_core_clean_v4_laneD_20260303_run1/`
- Evidence:
  - listed as main result entry in `docs/operations/core_benchmark_progress_p0_closure_20260304.md`
  - has camera/lidar subdirectories and summary references in progress doc

### OPV2V

- Candidate: `outputs/full_bench_opv2v_autopilot_full_core_clean_v4_laneD_20260303_run1_a1/`
- Evidence:
  - listed as main result entry in `docs/operations/core_benchmark_progress_p0_closure_20260304.md`
  - currently has `results_ap50_from_yaml.json` and plots, but summary completion is flagged as gap P0-3

### V2V4Real

- Candidate: `outputs/v2v4real_core_core_clean_v4_laneD_20260303_run1/`
- Evidence:
  - listed as main result entry in `docs/operations/core_benchmark_progress_p0_closure_20260304.md`
  - lidar lane available; camera lane still flagged as P0-2 gap

## Cloud-Synced Transition Bundle Candidates

From `docs/operations/cloud_reintegration_pack_20260301.md` and update section:

- `20260303_234522_v2xtransfullbencho009cad5bb2_dev100_M0_N2_D0_0` (OPV2V)
- `20260303_234522_v2xtranscamera01c9cb60b1_dev100_M0_N2_D0_0` (DAIR camera)
- `20260303_234522_v2xtranslidar024da2675e_dev100_M0_N2_D0_0` (DAIR lidar)
- `20260303_234522_v2xtransv2v4realco03a5089ccf_dev100_M0_N2_D0_0` (V2V4Real comm200)
- `20260303_234522_v2xtransv2v4realco042473d27e_dev100_M0_N2_D0_0` (V2V4Real comm70)

## Stale / Non-Canonical (Do Not Use for Final Claims)

- Legacy OPV2V run family centered on `full_bench_opv2v_autopilot_full_20260216_*`.
  - Reason: newer unified semantics and contract freeze replaced this baseline.
- Any run with implicit comm-range gating or missing compare-current pin manifest fields.
  - Reason: comparability risk and confound exposure.

## Active Blockers

1. OPV2V canonical candidate still needs a unified summary artifact (`summary.md`).
2. V2V4Real camera lane not yet closed under the same fairness contract.
3. Cloud transition bundles are managed, but full geometry depth/scale metrics are placeholders and can block route-decision gates.

## Next Action

Proceed with Phase 1 preflight and then execute smoke-first closure for each dataset.
