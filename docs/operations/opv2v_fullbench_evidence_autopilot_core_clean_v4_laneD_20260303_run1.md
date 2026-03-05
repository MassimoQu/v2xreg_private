# OPV2V Fullbench Evidence Report (2026-03-04)

## 0) Executive Conclusions

- Run dir: `/home/qqxluca/projects/v2xreg_private/outputs/full_bench_opv2v_autopilot_full_core_clean_v4_laneD_20260303_run1_a1`
- Run id: `opv2v_autopilot_full_core_clean_v4_laneD_20260303_run1_a1`
- Source of truth: `/home/qqxluca/projects/v2xreg_private/outputs/full_bench_opv2v_autopilot_full_core_clean_v4_laneD_20260303_run1_a1/run_state.jsonl` (NOT log grepping)

## 1) Run State (What Actually Finished)

- unique_tasks_started: 444
- unique_tasks_ended: 444
- final_end_codes: {0: 444}
- final_done_tasks: 444
- tasks_ever_failed (historical): 0

### task_summary.json (May Be Stale/Misleading)

- path: `/home/qqxluca/projects/v2xreg_private/outputs/full_bench_opv2v_autopilot_full_core_clean_v4_laneD_20260303_run1_a1/task_summary.json`
```json
{
  "done_from_reuse": 0,
  "done_from_state_in_scope": 0,
  "done_from_state_total": 0,
  "done_total_in_scope": 0,
  "in_progress": 0,
  "pending": 444,
  "scope_tasks": 444,
  "total_tasks": 444
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

- AP50 span lidar/noise10/baseline/bounds: n=11 min=0.405243 max=0.959381 span=0.554138
- AP50 span lidar/noise10/oracle/bounds: n=11 min=0.959319 max=0.959388 span=0.000070
- AP50 span camera/noise10/v2xregpp/best: n=11 min=0.091457 max=0.273605 span=0.182148

