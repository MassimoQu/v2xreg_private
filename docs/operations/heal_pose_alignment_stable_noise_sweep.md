# HEAL: Pose-Alignment "Stable" Noise Sweep (V2V4Real, comm_range=200)

This note records how we reproduce the "stable / noise-insensitive" extrinsic robustness sweep in **HEAL** by keeping cooperative perception fixed and only swapping the pose/alignment module.

## What "stable" means in this repo

For pose-correction methods that output an estimated relative transform `T_est` (ego -> cav), we define a *stable* update rule that behaves like a temporal filter:

1. Compute current relative transform from the (possibly noisy) poses: `T_cur`.
2. Convert the correction into a delta transform: `ΔT = T_est · inv(T_cur)`.
3. Convert `ΔT` to SE(2) parameters `(dx, dy, yaw)` and keep a per-CAV *delta state*.
4. Update that delta state with:
   - EMA smoothing (`ema_alpha`)
   - step gating (`max_step_xy_m`, `max_step_yaw_deg`)
5. Apply the filtered delta back onto the current relative transform:
   - `T_corrected = ΔT_filtered · T_cur`

This is the same strategy used for `v2xregpp_stable`, and we reuse it for `freealign_*_stable` and `v2vloc_*_stable`.

Key implication: **stable mode requires sequential sample order**, so `num_workers=0` is enforced for `*_stable` during sweeps.

## Code pointers (stable implementation)

- V2XReg++ stable delta filter + per-sample caching:
  - `HEAL/opencood/extrinsics/pose_correction/stage1_v2xregpp.py:602`
- FreeAlign (paper/repo) stable delta filter + per-sample caching:
  - `HEAL/opencood/extrinsics/pose_correction/stage1_freealign.py:1`
- V2VLoc-style (PGC/oracle pose JSON) stable delta filter:
  - `HEAL/opencood/extrinsics/pose_correction/stage1_pgc_pose.py:1`
- CLI entry + hypes injection (single switch for methods):
  - `HEAL/opencood/tools/inference_w_noise.py:300`

## Experiment setup (V2V4Real)

- Cooperative perception model (fixed across methods):
  - `HEAL/opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25`
- Stage-1 cache used by pose correctors:
  - `HEAL/opencood/logs/v2v4real_stage1_pointpillar_from_pastat_bestval17_80boxes/test/stage1_boxes.json`
- Dataset:
  - `dataset/v2v4real/test`
  - multi-ego expansion enabled (`base_len=1993`, `expanded_len=3986`)
- Sweep:
  - `--sweep-mode paired`
  - `--noise-target non-ego`
  - `pos_std = rot_std ∈ {0,1,2,3,4}` (meters / degrees)
- Comm range:
  - `--comm-range-override 200`

## Methods compared (same cooperative perception)

- `none`: no pose correction.
- `v2xregpp_stable`:
  - with lidar-occupancy hint and `--v2xregpp-force-occ-pose` to make correction independent of injected pose noise.
- `freealign_paper_stable`:
  - FreeAlign (paper-style) estimator + stable delta filter.
- `v2vloc_oracle_stable`:
  - "oracle" pose override from `lidar_pose_clean_np` in the stage1 cache + stable delta filter (upper bound).
  - Note: this is not a trained V2VLoc-PGC model; it is used to isolate the benefit of *perfect* localization on the same cooperative perception pipeline.

## Slurm sweep commands (job ids)

Submitted (comm200, sigma=0..4 paired):

```bash
MODEL_DIR="opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25"
STAGE1="opencood/logs/v2v4real_stage1_pointpillar_from_pastat_bestval17_80boxes/test/stage1_boxes.json"

sbatch -p normal --gres=gpu:1 --cpus-per-task=4 --mem=64G \
  -J v2v4_v2xregpp_stable_occ200 \
  -o "HEAL/${MODEL_DIR}/slurm_v2v4_v2xregpp_stable_occlidar_comm200_paper_%j.out" \
  -e "HEAL/${MODEL_DIR}/slurm_v2v4_v2xregpp_stable_occlidar_comm200_paper_%j.err" \
  HEAL/opencood/tools/sbatch_pose_sweep.sh \
    --model-dir "${MODEL_DIR}" \
    --pose-correction v2xregpp_stable \
    --stage1-result "${STAGE1}" \
    --note _comm200_paper \
    -- --v2xregpp-use-occ-hint --v2xregpp-use-occ-pose --v2xregpp-occ-from-lidar --v2xregpp-force-occ-pose

sbatch -p normal --gres=gpu:1 --cpus-per-task=4 --mem=64G \
  -J v2v4_freealign_paper_stable200 \
  -o "HEAL/${MODEL_DIR}/slurm_v2v4_freealign_paper_stable_comm200_paper_%j.out" \
  -e "HEAL/${MODEL_DIR}/slurm_v2v4_freealign_paper_stable_comm200_paper_%j.err" \
  HEAL/opencood/tools/sbatch_pose_sweep.sh \
    --model-dir "${MODEL_DIR}" \
    --pose-correction freealign_paper_stable \
    --stage1-result "${STAGE1}" \
    --note _comm200_paper

sbatch -p normal --gres=gpu:1 --cpus-per-task=4 --mem=64G \
  -J v2v4_v2vloc_oracle_stable200 \
  -o "HEAL/${MODEL_DIR}/slurm_v2v4_v2vloc_oracle_stable_comm200_paper_%j.out" \
  -e "HEAL/${MODEL_DIR}/slurm_v2v4_v2vloc_oracle_stable_comm200_paper_%j.err" \
  HEAL/opencood/tools/sbatch_pose_sweep.sh \
    --model-dir "${MODEL_DIR}" \
    --pose-correction v2vloc_oracle_stable \
    --stage1-result "${STAGE1}" \
    --note _comm200_paper
```

## Local sweep (no Slurm)

If Slurm is unavailable, you can run the exact same sweep locally by calling the same script via `bash` and pinning one GPU per process:

```bash
TS=$(date +%Y%m%d_%H%M%S)
MODEL_DIR="opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25"
STAGE1="opencood/logs/v2v4real_stage1_pointpillar_from_pastat_bestval17_80boxes/test/stage1_boxes.json"
RUN_DIR="HEAL/${MODEL_DIR}/local_runs"
mkdir -p "${RUN_DIR}"

# v2xregpp++ stable (occ-from-lidar + force_occ_pose)
nohup env CUDA_VISIBLE_DEVICES=0 PYTHONUNBUFFERED=1 \
  bash HEAL/opencood/tools/sbatch_pose_sweep.sh \
    --model-dir "${MODEL_DIR}" \
    --pose-correction v2xregpp_stable \
    --stage1-result "${STAGE1}" \
    --note _comm200_paper \
    --log-interval 200 \
    -- --v2xregpp-use-occ-hint --v2xregpp-use-occ-pose --v2xregpp-occ-from-lidar --v2xregpp-force-occ-pose \
  > "${RUN_DIR}/${TS}_v2xregpp_stable_comm200_paper.out" 2>&1 &

# freealign stable
nohup env CUDA_VISIBLE_DEVICES=1 PYTHONUNBUFFERED=1 \
  bash HEAL/opencood/tools/sbatch_pose_sweep.sh \
    --model-dir "${MODEL_DIR}" \
    --pose-correction freealign_paper_stable \
    --stage1-result "${STAGE1}" \
    --note _comm200_paper \
    --log-interval 200 \
  > "${RUN_DIR}/${TS}_freealign_paper_stable_comm200_paper.out" 2>&1 &

# v2vloc oracle stable
nohup env CUDA_VISIBLE_DEVICES=2 PYTHONUNBUFFERED=1 \
  bash HEAL/opencood/tools/sbatch_pose_sweep.sh \
    --model-dir "${MODEL_DIR}" \
    --pose-correction v2vloc_oracle_stable \
    --stage1-result "${STAGE1}" \
    --note _comm200_paper \
    --log-interval 200 \
  > "${RUN_DIR}/${TS}_v2vloc_oracle_stable_comm200_paper.out" 2>&1 &
```

Monitor:

```bash
tail -f "${RUN_DIR}/${TS}_v2xregpp_stable_comm200_paper.out"
```

Expected outputs (written into the model dir):

- `HEAL/opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25/AP030507_none_comm200_paper.yaml`
- `HEAL/opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25/AP030507_v2xregpp_stable_comm200_paper.yaml`
- `HEAL/opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25/AP030507_freealign_paper_stable_comm200_paper.yaml`
- `HEAL/opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25/AP030507_v2vloc_oracle_stable_comm200_paper.yaml`

## Plotting

Once the YAMLs exist:

```bash
$HOME/.micromamba/envs/heal/bin/python HEAL/opencood/tools/plot_noise_sweep.py \
  --yaml \
    HEAL/opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25/AP030507_none_comm200_paper.yaml \
    HEAL/opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25/AP030507_v2xregpp_stable_comm200_paper.yaml \
    HEAL/opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25/AP030507_freealign_paper_stable_comm200_paper.yaml \
    HEAL/opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25/AP030507_v2vloc_oracle_stable_comm200_paper.yaml \
  --label none v2xregpp_stable freealign_paper_stable v2vloc_oracle_stable \
  --metric ap50 --x pos_std --slice all --xlim 0,4 \
  --out docs/operations/v2v4real_extrinsic_sweep_comm200_paper_ap50_stable.png \
  --title "V2V4Real (PASTAT, comm=200): AP@0.5 vs pose noise (stable)"
```

## Notes / known issues

- FreeAlign on V2V4Real stage1 caches may produce incorrect relative transforms even at noise=0. If you see low-but-flat AP, it likely indicates a coordinate-frame mismatch between the cached stage1 boxes and the pose convention used by the matcher.
