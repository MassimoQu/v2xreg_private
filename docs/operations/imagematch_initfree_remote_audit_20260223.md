# ImageMatch InitFree Online Audit (OPV2V Camera, 2026-02-23)

## 0. Question Being Verified

In the OPV2V camera/noise10 append sweep, `imagematch_*` appeared to outperform other online methods by a large margin (and sometimes even exceed `oracle`).

This audit verifies **what `image_match_initfree` is actually doing** in the *online* backend, and whether `init_source=none` vs `init_source=current` changes anything, under **fully unified conditions** (same code, same python/torch, same dataset, same comm-range gating, same sample subset).

## 1. Provenance (Code + Host)

Remote host:

- `ssh -p 10800 qqxluca@2.tcp.vip.cpolar.cn`

Code checkout:

- repo: `~/repos/v2xreg_private`
- branch: `audit/imagematch_initfree_20260223`
- parent commit: `bcac275`
- HEAL submodule commit: `63e4fec` (from `github.com/MassimoQu/coop_calib`)

Key code instrumentation added for this audit:

- `HEAL/opencood/utils/pose_provider_runtime.py` now emits numeric `pose_provider_applied_count`
  so `inference_w_noise.py` can ingest it (only `*_sec`/`*_count` keys are summarized).

## 2. Dataset Wiring (Remote)

OPV2V test data used by this audit lives on the mounted disk:

- `/media/tsinghua3090/8626b953-db6f-4e02-b531-fceb130612da/home/OPV2V`

Repo symlinks created on remote:

- `dataset/OPV2V -> /media/.../home/OPV2V`
- `dataset/OPV2V_Hetero -> /media/.../home/OPV2V/OPV2V_Hetero`

Extra required file (heter modality assignment) created on remote:

- `opencood/logs/heter_modality_assign/opv2v_4modality.json`
  (copied from `HEAL/opencood/modality_assign/opv2v_4modality.json`)

## 3. Checkpoint Wiring (Remote)

Camera model dir used:

- `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/`

Checkpoint copied to remote (not committed to git):

- `HEAL/opencood/logs/_hf/net_epoch_bestval_at21.pth` (108MB)
- symlink: `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/net_epoch_bestval_at21.pth -> ../_hf/net_epoch_bestval_at21.pth`

## 4. Compatibility Fix (Remote)

The repo expects a compiled extension:

- `opencood.utils.box_overlaps`

Remote clone lacked the `.so`, so we copied the cp310 build from local into:

- `HEAL/opencood/utils/box_overlaps.cpython-310-x86_64-linux-gnu.so`

## 5. Unified Smoke Runs (All Conditions Frozen)

Common runtime contract for all runs:

- dataset: OPV2V `test` (len=2170)
- `fusion_method=intermediate`
- `pos_std=1.0`, `rot_std=1.0` (paired)
- `noise_target=non-ego`
- `solver_backend=online_box`
- `runtime_mode=register_and_fuse`
- `pose_source=noisy_input`
- `comm_range_gating=noisy` (explicitly frozen)
- `max_eval_samples=200`

Commands executed (remote, one GPU per run):

Baseline:

```bash
CUDA_VISIBLE_DEVICES=0 PYTHONPATH=$PWD/HEAL python3 HEAL/opencood/tools/inference_w_noise.py \
  --model_dir HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope \
  --fusion_method intermediate \
  --pos-std-list 1.0 --rot-std-list 1.0 --sweep-mode paired --noise-target non-ego \
  --num-workers 0 --log-interval 200 --pose-timing --pose-device cuda \
  --solver-backend online_box --pose-source noisy_input --runtime-mode register_and_fuse \
  --pose-correction none --comm-range-gating noisy --max-eval-samples 200 \
  --note _remote_smoke_20260223_camera_noise10_baseline_n1.0_r4
```

Oracle GT:

```bash
CUDA_VISIBLE_DEVICES=1 PYTHONPATH=$PWD/HEAL python3 -u HEAL/opencood/tools/inference_w_noise.py \
  --model_dir HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope \
  --fusion_method intermediate \
  --pos-std-list 1.0 --rot-std-list 1.0 --sweep-mode paired --noise-target non-ego \
  --num-workers 0 --log-interval 200 --pose-timing --pose-device cuda \
  --solver-backend online_box --pose-source noisy_input --runtime-mode register_and_fuse \
  --pose-correction oracle_gt --comm-range-gating noisy --max-eval-samples 200 \
  --note _remote_smoke_20260223_camera_noise10_oracle_gt_n1.0
```

ImageMatch (no-init):

```bash
CUDA_VISIBLE_DEVICES=2 PYTHONPATH=$PWD/HEAL python3 -u HEAL/opencood/tools/inference_w_noise.py \
  --model_dir HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope \
  --fusion_method intermediate \
  --pos-std-list 1.0 --rot-std-list 1.0 --sweep-mode paired --noise-target non-ego \
  --num-workers 0 --log-interval 200 --pose-timing --pose-device cuda \
  --solver-backend online_box --pose-source noisy_input --runtime-mode register_and_fuse \
  --pose-correction image_match_initfree --pose-compare-current --image-match-init-source none \
  --comm-range-gating noisy --max-eval-samples 200 \
  --note _remote_smoke_20260223_camera_noise10_imagematch_noinit_n1.0
```

ImageMatch (current-init):

```bash
CUDA_VISIBLE_DEVICES=3 PYTHONPATH=$PWD/HEAL python3 -u HEAL/opencood/tools/inference_w_noise.py \
  --model_dir HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope \
  --fusion_method intermediate \
  --pos-std-list 1.0 --rot-std-list 1.0 --sweep-mode paired --noise-target non-ego \
  --num-workers 0 --log-interval 200 --pose-timing --pose-device cuda \
  --solver-backend online_box --pose-source noisy_input --runtime-mode register_and_fuse \
  --pose-correction image_match_initfree --pose-compare-current --image-match-init-source current \
  --comm-range-gating noisy --max-eval-samples 200 \
  --note _remote_smoke_20260223_camera_noise10_imagematch_current_n1.0
```

## 6. Results (Source-of-Truth Artifacts)

All metrics below come from the generated YAML summaries:

- baseline:
  `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/AP030507_none_remote_smoke_20260223_camera_noise10_baseline_n1.0_r4.yaml`
- oracle:
  `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/AP030507_oracle_gt_remote_smoke_20260223_camera_noise10_oracle_gt_n1.0.yaml`
- imagematch (no-init):
  `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/AP030507_image_match_initfree_remote_smoke_20260223_camera_noise10_imagematch_noinit_n1.0.yaml`
- imagematch (current-init):
  `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/AP030507_image_match_initfree_remote_smoke_20260223_camera_noise10_imagematch_current_n1.0.yaml`

Summary (first 200 samples only):

| method | AP50 | mean rel_trans (m) | mean rel_yaw (deg) | pose_provider_applied_count | cpu_fallback_count |
| --- | ---: | ---: | ---: | ---: | ---: |
| baseline (`none`) | 0.1276 | 1.2783 | 0.7633 | 0.0 | 0.0 |
| imagematch (no-init) | 0.1276 | 1.2783 | 0.7633 | 0.0 | 1.0 |
| imagematch (current-init) | 0.1276 | 1.2783 | 0.7633 | 0.0 | 1.0 |
| oracle_gt | 0.1608 | ~0 | ~0 | 0.405 | 0.0 |

Key observations:

1) **`imagematch` == `baseline`** on AP and pose error under unified conditions.
2) `cpu_fallback_count=1.0` for imagematch shows the corrector path is entered, but
   `pose_provider_applied_count=0.0` shows **no pose update was applied**.
3) `init_source=none` vs `init_source=current` is **effectively identical** here.

## 7. Mechanism-Level Explanation (Why It Becomes a No-op Online)

The online backend (`PoseProviderRuntime`) builds a minimal `base_data_dict` that contains:

- `params.lidar_pose`, `params.pose_confidence` (and optional `params.lidar_pose_clean`)

It does **not** pass:

- `camera_data` (images)
- camera intrinsics (`params.camera*/intrinsic`)
- camera extrinsics / coords (`params.camera*/cords` or `extrinsic`)

But `Stage1ImageMatchPoseCorrector` requires `camera_data + intrinsic + extrinsic/cords` to estimate
camera-camera relative pose and map it back to lidar frames.

Therefore in the current online path it cannot form valid camera pairs and returns `updated_any=False`,
leading to `pose_provider_applied_count=0.0` and unchanged pose error stats.

Code pointers (for follow-up patching):

- online payload construction: `HEAL/opencood/utils/pose_provider_runtime.py`
- image-match corrector input contract: `HEAL/opencood/extrinsics/pose_correction/stage1_image_match.py`

## 8. Implication for the Earlier “断档领先”

Given imagematch does not apply pose updates in the unified online setup, any large AP gap observed in
older mixed benchmarks is **not evidence of true imagematch superiority**; it is most likely caused by
benchmark confounds (e.g., mixing different python envs / code snapshots between baseline and append runs).

Next action (recommended): rerun the full OPV2V camera/noise10 baseline+oracle under the same env/commit
as the append methods and rebuild the unified report/plots from YAML.

