# Benchmark Execution Status (2026-02-19)

Last updated: 2026-02-20 13:46

## 1) DAIR full sweep (gpuvoxel20260218) — Completed

- Runner: `outputs/run_noise_sweep_1to10.py` (already exited)
- Logs: `outputs/pose_sweep_1to10_full_gpuvoxel20260218_logs/`
- Result JSONL: `outputs/pose_sweep_1to10_full_gpuvoxel20260218_results.jsonl` (20/20 jobs)
- Plots:
  - `outputs/pose_sweep_1to10_full_gpuvoxel20260218_plots/pose_sweep_1to10_full_camera_best_ap50.png`
  - `outputs/pose_sweep_1to10_full_gpuvoxel20260218_plots/pose_sweep_1to10_full_camera_stable_ap50.png`
  - `outputs/pose_sweep_1to10_full_gpuvoxel20260218_plots/pose_sweep_1to10_full_lidar_best_ap50.png`
  - `outputs/pose_sweep_1to10_full_gpuvoxel20260218_plots/pose_sweep_1to10_full_lidar_stable_ap50.png`

Evidence note:
- Every log ends with `exit_code=0`, and max noise reaches `10.0`.

## 2) OPV2V camera occhint append onto auto3 — Completed

Goal:
- Add `v2xregpp_occhint` curves into existing run id
  `opv2v_autopilot_full_20260216_auto3_a1`, then re-summarize and re-plot.

Launcher/script:
- `outputs/launch_occhint_append_auto3_after_dair_20260219.sh`

Execution completion:
- launcher trace shows completion:
  - start: `2026-02-19 04:59:02`
  - done: `2026-02-19 07:19:31`
- scheduler process has exited (no active `run_opv2v_fullbench_fast.py` for this run id).

Stage1 checks already passed:
- raw occ stage1:
  `data/OPV2V/detected/opv2v_camera_v2xvit_stage1_percav_occ_full/test/stage1_boxes.json`
- merged stage1:
  `data/OPV2V/detected/opv2v_camera_v2xvit_stage1_percav_occ_merged/test/stage1_boxes.json`

Scheduler state (final):
- `run_state.jsonl` has `v2xregpp_occhint` events:
  - start: 40
  - end(code=0): 40
  - end(code!=0): 0
- scope covered:
  - camera/noise10/best n=1..10
  - camera/noise10/stable n=1..10
  - camera/drop20/best n=1..10
  - camera/drop20/stable n=1..10

Target output location after completion:
- `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/plots_yaml/noise10_camera_ap50.png`
- `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/plots_yaml/drop20_camera_ap50.png`
- `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/results_ap50_from_yaml.json`

Quick outcome:
- `v2xregpp_occhint` is consistently above `v2xregpp` on camera AP50 for both suites.
- mean AP50 gain (occhint - v2xregpp, best lines):
  - noise10: `+0.00297`
  - drop20: `+0.00285`
