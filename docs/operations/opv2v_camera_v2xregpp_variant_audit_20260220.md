# OPV2V Camera V2X-Reg++ Variant Audit (2026-02-20)

Last updated: 2026-02-20

## 1) Question and scope

This audit answers three concrete questions:

1. Did we run only OCC, or multiple feature-enhanced V2X-Reg++ variants?
2. In OPV2V camera online benchmark, which variant is currently best?
3. Why can registration metrics improve more than downstream AP50?

Scope is fixed to:
- online benchmark semantics (`solver_backend=online_box`, `runtime_mode=register_and_fuse`)
- OPV2V camera sweeps (`noise10`, `drop20`)
- trusted run id: `opv2v_autopilot_full_20260216_auto3_a1`

## 2) Evidence sources (source of truth)

- Variant history and smoke records:
  - `docs/operations/experiment_progress.md`
  - `docs/operations/opv2v_camera_v2xregpp_occhint_20260219.md`
- Fullbench completion and outputs:
  - `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/run_state.jsonl`
  - `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/results_ap50_from_yaml.json`
- Per-task rel-error evidence (YAML):
  - `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/AP030507_*opv2v_autopilot_full_20260216_auto3_a1_camera_*v2xregpp*.yaml`

## 3) Findings

### 3.1 We did NOT run only OCC

Historical records show multiple feature routes were tried:

- descriptor-seed + hint route (negative):
  - `Detection + BEV desc + occ hint + descriptor seed` underperformed and was not promoted.
- camera online OCC family smoke:
  - `v2xregpp` vs `v2xregpp+occ-hint` vs `v2xregpp+occ-pose` all have explicit YAML evidence.

Smoke AP50 (n=1, 100 samples):

| Method | AP50 | rel_trans mean (m) | rel_yaw mean (deg) |
| --- | ---: | ---: | ---: |
| baseline | 0.1867 | 1.38 | 0.67 |
| v2xregpp | 0.1716 | 7.51 | 4.32 |
| v2xregpp + occ-hint | 0.1814 | 4.73 | 1.14 |
| v2xregpp + occ-pose | 0.1534 | 30.48 | 38.08 |

Conclusion at smoke level: occ-hint > plain v2xregpp, while occ-pose is clearly worse in current setting.

### 3.2 Fullbench append run is complete, and occ-hint is currently the best tested V2X-Reg++ camera variant

Run completion facts:
- `run_state.jsonl` has full `start/end` closure with no fail events for `v2xregpp_occhint` append tasks (40 starts, 40 ends).
- Updated plots/results are under:
  - `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/plots_yaml/`
  - `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/results_ap50_from_yaml.json`

AP50 mean over n=1..10 (camera):

| Sweep | baseline | v2xregpp-best | v2xregpp-occhint-best | oracle |
| --- | ---: | ---: | ---: | ---: |
| noise10 | 0.106112 | 0.111027 | **0.113999** | 0.302016 |
| drop20 | 0.106065 | 0.111582 | **0.114428** | 0.302016 |

Delta (`occhint-best - v2xregpp-best`):
- noise10: `+0.002972`
- drop20: `+0.002846`

So under the current online camera setup, **occ-hint is the best tested V2X-Reg++ enhancement variant**.

### 3.3 Why registration gain can be larger than AP gain

For `best` lines in fullbench:

- noise10 (`v2xregpp -> occhint`):
  - rel_trans mean: `10.939 -> 9.464` (improve `-1.475 m`)
  - rel_yaw mean: `11.624 -> 9.698` (improve `-1.926 deg`)
  - AP50 mean: `0.111027 -> 0.113999` (only `+0.002972`)
- drop20 (`v2xregpp -> occhint`):
  - rel_trans mean: `11.036 -> 9.538` (improve `-1.498 m`)
  - rel_yaw mean: `11.653 -> 9.697` (improve `-1.955 deg`)
  - AP50 mean: `0.111582 -> 0.114428` (only `+0.002846`)

Interpretation chain:
1. The correction does improve relative pose on average.
2. But both corrected lines are still far from oracle AP50 (`~0.114` vs `0.302`), so pose is only part of the bottleneck.
3. In this camera stack, remaining error budget is dominated by perception/fusion sensitivity, so AP gain is compressed even when registration metrics move more.

## 4) Status of "full GPU + all benchmark" plan

Consolidated from status docs:

- OPV2V fullbench masterplan: **ALLOW** for online benchmark publication lane.
- Full-GPU promotion lane: **PARTIAL/BLOCK for reference promotion**:
  - strict oracle parity gate is still FAIL,
  - CPU fallback still appears in mainline fullbench hot path,
  - therefore cannot claim strict all-GPU reference lane completed.
- DAIR noise sweep (`gpuvoxel20260218`): **Completed** (20/20 jobs, all `exit_code=0`).
- OPV2V camera occhint append: **Completed** and integrated into existing run id plots/results.

Bottom line:
- "all benchmark" is substantially complete for the currently scoped OPV2V + DAIR runs.
- "strict full-GPU reference lane" is not complete yet due to parity/fallback gates.

