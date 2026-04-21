# OPV2V Fullbench Evidence Report (2026-02-23)

## 0) Executive Conclusions

- Run dir: `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1`
- Run id: `opv2v_autopilot_full_20260216_auto3_a1`
- Source of truth: `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/run_state.jsonl` (NOT log grepping)

## 1) Run State (What Actually Finished)

- unique_tasks_started: 668
- unique_tasks_ended: 638
- final_end_codes: {0: 638}
- final_done_tasks: 638
- tasks_ever_failed (historical): 0

### task_summary.json (May Be Stale/Misleading)

- path: `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/task_summary.json`
```json
{
  "done_from_reuse": 0,
  "done_from_state_in_scope": 178,
  "done_from_state_total": 622,
  "done_total_in_scope": 178,
  "in_progress": 30,
  "pending": 192,
  "scope_tasks": 400,
  "total_tasks": 400
}
```

## 2) Historical Failures (Why It Failed Before)

- No failures recorded in run_state.jsonl.
## 3) Stage1 Cache Integrity (Hard Requirement for Pose-Correction)

- camera stage1: `data/OPV2V/detected/opv2v_camera_v2xvit_stage1_percav/test/stage1_boxes.json` samples=2170 len_mismatch=0
- lidar stage1: `data/OPV2V/detected/opv2v_lidar_v2xvit_stage1/test/stage1_boxes.json` samples=2170 len_mismatch=0

## 4) Pose Override (Can Cancel Noise Sweeps)

- camera model config: `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/config.yaml` pose_override_found=False enabled=None mode=None
- lidar model config: `HEAL/opencood/logs/freealign_repro_opv2v_baseline/config.yaml` pose_override_found=False enabled=None mode=None

## 5) YAML-Derived Sanity Stats (AP Span + pose_solver.applied)

- AP50 span lidar/noise10/baseline/bounds: n=10 min=0.403879 max=0.604202 span=0.200323
- AP50 span lidar/noise10/oracle/bounds: n=10 min=0.959351 max=0.959417 span=0.000067
- AP50 span camera/noise10/v2xregpp/best: n=10 min=0.093046 max=0.177483 span=0.084437

