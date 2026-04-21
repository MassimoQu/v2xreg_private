# OPV2V Fullbench Evidence Report (2026-03-06)

## 0) Executive Conclusions

- Run dir: `/home/qqxluca/projects/v2xreg_private/outputs/full_bench_opv2v_autopilot_smoke_p3_opv2v_trackd_smoke_20260306_a1`
- Run id: `opv2v_autopilot_smoke_p3_opv2v_trackd_smoke_20260306_a1`
- Source of truth: `/home/qqxluca/projects/v2xreg_private/outputs/full_bench_opv2v_autopilot_smoke_p3_opv2v_trackd_smoke_20260306_a1/run_state.jsonl` (NOT log grepping)

## 1) Run State (What Actually Finished)

- unique_tasks_started: 42
- unique_tasks_ended: 42
- final_end_codes: {0: 42}
- final_done_tasks: 42
- tasks_ever_failed (historical): 0

### task_summary.json (May Be Stale/Misleading)

- path: `/home/qqxluca/projects/v2xreg_private/outputs/full_bench_opv2v_autopilot_smoke_p3_opv2v_trackd_smoke_20260306_a1/task_summary.json`
```json
{
  "done_from_reuse": 0,
  "done_from_state_in_scope": 0,
  "done_from_state_total": 0,
  "done_total_in_scope": 0,
  "in_progress": 0,
  "pending": 42,
  "scope_tasks": 42,
  "total_tasks": 42
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

- AP50 span lidar/noise10/baseline/bounds: n=2 min=0.378986 max=0.503650 span=0.124664
- AP50 span lidar/noise10/oracle/bounds: n=2 min=0.997620 max=0.997631 span=0.000011
- AP50 span camera/noise10/v2xregpp/best: n=2 min=0.263191 max=0.292134 span=0.028943

