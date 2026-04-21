# OPV2V Fullbench Evidence Report (2026-02-17)

## 0) Executive Conclusions

- Run dir: `/home/qqxluca/projects/v2xreg_private/outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1`
- Run id: `opv2v_autopilot_full_20260216_auto3_a1`
- Source of truth: `/home/qqxluca/projects/v2xreg_private/outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/run_state.jsonl` (NOT log grepping)

### Update (2026-02-20)

- This file's original `404` counts describe the core fullbench scope before camera `v2xregpp_occhint` append.
- Current run_state (same run_id) after append is:
  - unique_tasks_started: 444
  - unique_tasks_ended: 444
  - final_end_codes: {0: 444}
- The append adds camera-only occhint tasks; cross-modal core scope remains complete.

## 1) Run State (What Actually Finished)

- unique_tasks_started: 404
- unique_tasks_ended: 404
- final_end_codes: {0: 404}
- final_done_tasks: 404
- tasks_ever_failed (historical): 0

### task_summary.json (May Be Stale/Misleading)

- path: `/home/qqxluca/projects/v2xreg_private/outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/task_summary.json`
```json
{
  "done_from_reuse": 0,
  "done_from_state_in_scope": 0,
  "done_from_state_total": 0,
  "done_total_in_scope": 0,
  "in_progress": 0,
  "pending": 404,
  "scope_tasks": 404,
  "total_tasks": 404
}
```

## 2) Historical Failures (Why It Failed Before)

- No failures recorded in run_state.jsonl.
## 3) Stage1 Cache Integrity (Hard Requirement for Pose-Correction)

- camera stage1: `/home/qqxluca/projects/v2xreg_private/data/OPV2V/detected/opv2v_camera_v2xvit_stage1_percav/test/stage1_boxes.json` samples=2170 len_mismatch=0
- lidar stage1: `/home/qqxluca/projects/v2xreg_private/data/OPV2V/detected/opv2v_lidar_v2xvit_stage1/test/stage1_boxes.json` samples=2170 len_mismatch=0

## 4) Pose Override (Can Cancel Noise Sweeps)

- camera model config: `/home/qqxluca/projects/v2xreg_private/HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/config.yaml` pose_override_found=False enabled=None mode=None
- lidar model config: `/home/qqxluca/projects/v2xreg_private/HEAL/opencood/logs/freealign_repro_opv2v_baseline/config.yaml` pose_override_found=False enabled=None mode=None

## 5) YAML-Derived Sanity Stats (AP Span + pose_solver.applied)

- AP50 span lidar/noise10/baseline/bounds: n=10 min=0.403879 max=0.604202 span=0.200323
- AP50 span lidar/noise10/oracle/bounds: n=10 min=0.959351 max=0.959417 span=0.000067
- AP50 span camera/noise10/v2xregpp/best: n=10 min=0.093046 max=0.177483 span=0.084437
