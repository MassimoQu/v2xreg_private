# OPV2V: Cooperative Detection Without Extrinsics (Pose Injection via Stage-1 Boxes)

This note records a concrete "no extrinsics input" experiment in this repo on OPV2V.

## Goal

Make cooperative perception work when the model is *not given any usable poses/extrinsics* at inference.

Practical definition used here:
- Override all agents' `lidar_pose` to zeros (so `pairwise_t_matrix` becomes identity).
- Recover relative poses online using a calibration-free estimator from per-agent stage-1 detections.
- Let the detector/fusion model consume the recovered transforms normally.

## Data / Artifacts

Stage-1 cache (per-agent boxes in local LiDAR frames) already exists on this machine:
- Source: `/home/qqxluca/_tmp_freealign_repo/_baidu/logs_extracted/coalign_precalc/opv2v/{train,val,test}/stage1_boxes.json`
- Linked into this repo:
  - `HEAL/opencood/logs/freealign_repro_opv2v_stage1/train/stage1_boxes.json`
  - `HEAL/opencood/logs/freealign_repro_opv2v_stage1/val/stage1_boxes.json`
  - `HEAL/opencood/logs/freealign_repro_opv2v_stage1/test/stage1_boxes.json`

## Implementation (Repo Changes)

Key additions:
- `HEAL/opencood/utils/pose_utils.py`: `override_lidar_poses()` (sets all/selected agents' `lidar_pose` to ego or zeros).
- `HEAL/opencood/data_utils/datasets/intermediate_fusion_dataset.py`: supports `pose_override` + `comm_range_use_clean_pose` and applies the override before `pairwise_t_matrix`.
- `HEAL/opencood/data_utils/datasets/intermediate_heter_fusion_dataset.py`: same as above for heter pipeline.
- `HEAL/opencood/tools/inference_w_noise.py`: pose solver runs outside dataset and injects override map.

## Experiment Setup

Detector under test:
- Model: PointPillar (multiscale) + **MaxFusion** (intermediate fusion).
- Checkpoint: `HEAL/opencood/logs/freealign_repro_opv2v_baseline/net_epoch_bestval_at27.pth`
- "Clean extrinsics" reference metric (from existing run):
  - `HEAL/opencood/logs/freealign_repro_opv2v_baseline/eval_0.0_0.0_0.0_0.0_intermediate.yaml`
  - AP50 ≈ 0.9593, AP70 ≈ 0.9210

No-extrinsics configs (created as lightweight run dirs with `config.yaml` + symlinked checkpoint):
- No extrinsics, no correction:
  - `HEAL/opencood/logs/freealign_repro_opv2v_baseline_noextr_none/config.yaml`
- No extrinsics + FreeAlign (paper impl):
  - `HEAL/opencood/logs/freealign_repro_opv2v_baseline_noextr_freealign/config.yaml`
- No extrinsics + V2XReg++ (initfree):
  - `HEAL/opencood/logs/freealign_repro_opv2v_baseline_noextr_v2xregpp/config.yaml`

Common knobs used:
- `pose_override.enabled: true`, `pose_override.mode: zero`, `pose_override.apply_to: all`
- `comm_range_use_clean_pose: true` (avoid agent inclusion artifacts from the override)
- `noise_setting.add_noise: false`

## Results (OPV2V Test, full 2170 frames)

All results come from the run dirs' `eval_intermediate_epoch27.yaml`.

1) No extrinsics, no correction
- `HEAL/opencood/logs/freealign_repro_opv2v_baseline_noextr_none/eval_intermediate_epoch27.yaml`
- AP50 = 0.2744, AP70 = 0.1953

2) No extrinsics + FreeAlign (GNN-Lite)
- `HEAL/opencood/logs/freealign_repro_opv2v_baseline_noextr_freealign/eval_intermediate_epoch27.yaml`
- AP50 = 0.8779, AP70 = 0.8115
- Pose correction overhead (from stdout):
  - `freealign_pre_sec`: mean ~0.133s/sample (p95 ~0.455s)

3) No extrinsics + V2XReg++ (initfree)
- `HEAL/opencood/logs/freealign_repro_opv2v_baseline_noextr_v2xregpp/eval_intermediate_epoch27.yaml`
- AP50 = 0.9025, AP70 = 0.8443
- Pose correction overhead:
  - `v2xregpp_pre_sec`: mean ~0.118s/sample (p95 ~0.333s)

## Takeaways

- The earlier "feature-map phase correlation" prototype is not reliable enough on OPV2V.
- Object-level calibration-free pose estimation (FreeAlign / V2XReg++) *does* make cooperative perception work with **no usable extrinsics input**.
- V2XReg++ is slightly better than FreeAlign here on OPV2V test (AP50/AP70).
- The reported overhead is only for pose correction; it does **not** include the cost of running a stage-1 detector to obtain boxes online (we used cached outputs).
