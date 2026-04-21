# OPV2V Append (Init/No-init/HKUST) Partial Results (2026-02-22)

This note snapshots the *current* (partial) results for the OPV2V append sweep that adds:

- `vips_prior`, `cbm_prior`
- `imagematch_noinit`, `imagematch_current`
- `lidarreg_ransac`, `hkust_teaser`, `hkust_fgr`, `hkust_quatro`

## IMPORTANT UPDATE (2026-02-23): imagematch “断档领先”已证实为不可用结论（no-op + mixed-version）

这份 2026-02-22 的“partial results”仅能作为**历史记录**，不能作为最终 benchmark 的排序依据，原因是：

1) **imagematch 在统一条件审计下为 no-op**
- 在远端统一条件审计（同 commit / 同 env / 同 comm-range gating / 同样本子集）下：
  `image_match_initfree` **不会 apply pose update**（`pose_provider_applied_count=0`），AP50 与 baseline 完全一致。
  见：`docs/operations/imagematch_initfree_remote_audit_20260223.md`。
- 在本地统一 smoke（同样冻结 `comm_range_gating=noisy`）下也复现：
  - baseline：
    `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/AP030507_none_opv2v_unified_smoke_20260223_fix1_camera_noise10_baseline_n1.0.yaml`
  - imagematch_noinit：
    `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/AP030507_image_match_initfree_opv2v_unified_smoke_20260223_fix1_camera_noise10_imagematch_noinit_best_n1.0.yaml`
  - 结论：两者 AP30/50/70 逐项相同，且 `timing_stats[0].pose_timing.pose_provider_applied_count=0.0`。

2) **同一 run_id（`opv2v_autopilot_full_20260216_auto3_a1`）存在 mixed-env + mid-run 修复混写**
- core 与 append 使用了不同 python env（见下文“Important reproducibility note”）。
- append 长跑过程中 HEAL 子模块发生关键修复（imagematch online payload、lidar_reg per-CAV raw points、T 方向修复等）。
  因此同一 run_id 下不同任务可能对应不同代码语义，最终 numbers **不具备“同口径可比性”**。

3) **LiDAR 的 lidarreg/hkust 也存在“早期任务退化”风险（需要重跑验证）**
- 在 append run 的早期已完成任务里，可以观察到 `lidarreg_ransac` 与 `hkust_teaser` 产出**完全一致的曲线/误差**，
  且 `match_sec` 极小（暗示 registration 没有真正跑起来，或 payload 缺失导致快速 no-op）：
  - `HEAL/opencood/logs/freealign_repro_opv2v_baseline/AP030507_lidar_reg_initfree_opv2v_autopilot_full_20260216_auto3_a1_lidar_noise10_lidarreg_ransac_best_n1.0.yaml`
  - `HEAL/opencood/logs/freealign_repro_opv2v_baseline/AP030507_lidar_reg_initfree_opv2v_autopilot_full_20260216_auto3_a1_lidar_noise10_hkust_teaser_best_n1.0.yaml`
  - 两者在该点上 `ap50=0.595188...`、`rel_trans_m.mean=1.223692...`、`match_sec≈7e-4`。
  - 进一步说明（机制层面）：当 runtime batch 未携带 per-CAV raw points（`lidar_np_by_cav`）时，
    online `lidar_reg` corrector 无法组装 `base_data_dict[*].lidar_np`，会直接返回不 apply（silent no-op）。
    另外在部分脚本（默认 `visualize=False`）里，历史版本的 dataloader 曾把 `lidar_np_by_cav` 导出绑定到 `visualize`，
    这也会导致同样的 no-op；该点已在 2026-02-24 解耦修复（以最新 commit 为准）。

因此：**本文件中“imagematch AP 很高”的表格只保留为历史现象，不应作为最终对比结论。**

Run directory (source of truth):

- `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/`

Progress state file:

- `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/run_state.jsonl`

## Benchmark Contract (What Was Launched)

Scheduler:

- `tools/run_opv2v_fullbench_fast.py`

Config snapshot:

- `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/config_snapshot.json`

Key runtime knobs:

- `solver_backend=online_box`
- `runtime_mode=register_and_fuse`
- `pose_source=noisy_input`
- `sweeps=noise10,drop20` (dropout=0.2 on `drop20`)
- `pos_std_list = rot_std_list = [1..10]` (paired)

Important reproducibility note:

- This append launcher uses `python_bin=.micromamba/envs/v2x/bin/python` (see `config_snapshot.json`).
  The earlier “core” run in the same `run_id` used `py39` (see `config_snapshot.before_occhint_20260219_045908.json`).
  If strict “same-env” parity is required, we should rerun the non-TEASER methods under the original env.
- Concretely:
  - Core run (baseline/oracle/v2xregpp/freealign/vips/cbm) snapshot:
    `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/config_snapshot.before_occhint_20260219_045908.json`
    - `python_bin = .../.micromamba/envs/py39/bin/python`
  - Append run (this file's methods) snapshot:
    `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/config_snapshot.json`
    - `python_bin = .../.micromamba/envs/v2x/bin/python`
  - **Implication**: any cross-method comparison that mixes core vs append lines is *provisionally* informative,
    but not yet “same-condition fair” until baseline/oracle (+ ideally the core methods) are re-run under the same env.

Method → CLI mapping is defined in:

- `tools/run_opv2v_fullbench_fast.py`

where each method runs two strategies:

- `best`: `*_initfree` + `--pose-compare-current`
- `stable`: `*_stable`

Extra args used by the append methods:

- `vips_prior`: `--vips-use-prior`
- `cbm_prior`: `--cbm-use-prior`
- `imagematch_noinit`: `--image-match-init-source none`
- `imagematch_current`: `--image-match-init-source current`
- `lidarreg_ransac`: `--lidar-reg-global-method ransac`
- `hkust_teaser`: `--lidar-reg-global-method teaser_gnctls`
- `hkust_fgr`: `--lidar-reg-global-method teaser_fgr`
- `hkust_quatro`: `--lidar-reg-global-method teaser_quatro`

## What Has Finished So Far (As of 2026-02-22)

Append scope contains 400 tasks total:

- `4 (camera-only) methods × 2 sweeps × 10 noises × 2 (best/stable) = 160`
- `4 (lidar-only)  methods × 2 sweeps × 10 noises × 2 (best/stable) = 160`
- `2 (vips_prior/cbm_prior on lidar) methods × 2 sweeps × 10 noises × 2 = 80`

Currently finished subset:

- **camera/noise10**: all noise levels `1..10` finished for
  `vips_prior`, `cbm_prior`, `imagematch_noinit`, `imagematch_current` (both `best` and `stable`).
- **camera/drop20**: only noise levels `1..3` finished for the same 4 methods.
- **lidar/**: no append tasks finished yet (not started yet in the current scheduler ordering).

All finished append tasks so far are `code=0` (no failures).

## Downstream Detection (AP@0.5) — Camera / noise10

Values below are extracted from the last line of the corresponding log files in:

- `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/logs/`

Representative comparisons (AP@0.5), camera/noise10:

| noise std | oracle | baseline | imagematch_noinit (best) | v2xregpp_occhint (best) | vips_prior (best) | cbm_prior (best) |
|---:|---:|---:|---:|---:|---:|---:|
| 1.0 | 0.300 | 0.210 | 0.340 | 0.190 | 0.140 | 0.110 |
| 2.0 | 0.300 | 0.140 | 0.220 | 0.140 | 0.110 | 0.090 |
| 3.0 | 0.300 | 0.110 | 0.170 | 0.120 | 0.090 | 0.080 |
| 4.0 | 0.300 | 0.100 | 0.150 | 0.110 | 0.090 | 0.080 |
| 5.0 | 0.300 | 0.090 | 0.150 | 0.100 | 0.080 | 0.080 |
| 6.0 | 0.300 | 0.090 | 0.140 | 0.100 | 0.080 | 0.070 |
| 7.0 | 0.300 | 0.080 | 0.140 | 0.100 | 0.080 | 0.070 |
| 8.0 | 0.300 | 0.080 | 0.140 | 0.100 | 0.080 | 0.070 |
| 9.0 | 0.300 | 0.080 | 0.130 | 0.090 | 0.080 | 0.070 |
| 10.0 | 0.300 | 0.080 | 0.140 | 0.090 | 0.080 | 0.070 |

Means over noise `1..10` (camera/noise10, AP@0.5):

- oracle: 0.3000
- baseline: 0.1060
- imagematch_noinit (best): 0.1720
- v2xregpp_occhint (best): 0.1140
- vips_prior (best): 0.0910
- cbm_prior (best): 0.0790

Notes:

- For the 4 append camera methods, **`best` and `stable` AP@0.5 are identical** on the finished camera/noise10 subset.
- `imagematch_noinit` (ORB default, CPU) exceeds `oracle_gt` on AP@0.5 at noise=1.0 in this run; treat this as *provisional* until we sanity-check “oracle” pose wiring and coordinate conventions.

Update (2026-02-23, remote verification):

- Under a fully unified setup on the remote OPV2V machine (same code commit/env, same dataset wiring, same comm-range gating, same sample subset),
  `image_match_initfree` **does not apply any pose update** (`pose_provider_applied_count=0`) and its AP50 matches baseline exactly.
- `init_source=none` vs `init_source=current` is also identical in that unified run.
- See: `docs/operations/imagematch_initfree_remote_audit_20260223.md`.

## Sanity Check: Comm-Range Gating Is NOT The Explanation (Verified)

Because `inference_w_noise.py` can flip `comm_range_use_clean_pose` automatically when pose correction is enabled,
one tempting explanation for `imagematch_*` being high is “agent inclusion differs (clean-vs-noisy comm-range pruning)”.

We verified this is *not* the driver on OPV2V camera:

- Using the exact stage1 cache used by this run:
  - `data/OPV2V/detected/opv2v_camera_v2xvit_stage1_percav/test/stage1_boxes.json`
- Applying the same noise injection routine (`add_noise_data_dict`, seed=303, target=non-ego),
  and counting CAVs within `comm_range=70` under:
  - clean gating: distance from `lidar_pose_clean`
  - noisy gating: distance from `lidar_pose`

Results over all 2170 samples:

- `pos_std=rot_std=1.0`: only **11 / 2170** samples change inclusion
- `pos_std=rot_std=10.0`: only **86 / 2170** samples change inclusion

So “comm-range gating semantic drift” is far too small to explain AP jumps of ~0.1.

Repro command used:

```bash
PYTHONPATH=HEAL ./.micromamba/envs/v2x/bin/python - <<'PY'
import json, math
from collections import OrderedDict, Counter
import numpy as np
from opencood.utils.pose_utils import add_noise_data_dict

stage1_path="data/OPV2V/detected/opv2v_camera_v2xvit_stage1_percav/test/stage1_boxes.json"
stage1=json.load(open(stage1_path))
keys=sorted(stage1.keys(), key=lambda x:int(x))
comm_range=70.0

def run(pos_std):
    np.random.seed(303)
    if hasattr(add_noise_data_dict,"_dropout_state"):
        delattr(add_noise_data_dict,"_dropout_state")
    noise_setting=OrderedDict(add_noise=True, args=dict(pos_std=pos_std, rot_std=pos_std, pos_mean=0.0, rot_mean=0.0, target="non-ego"))
    deltas=[]
    for k in keys:
        entry=stage1[k]
        cav_ids=entry["cav_id_list"]
        poses=np.asarray(entry["lidar_pose_np"],dtype=np.float32)
        base=OrderedDict((cid, dict(ego=i==0, params=dict(lidar_pose=poses[i].copy()))) for i,cid in enumerate(cav_ids))
        base=add_noise_data_dict(base, noise_setting)
        ego_id=cav_ids[0]
        ego_clean=base[ego_id]["params"]["lidar_pose_clean"]
        ego_noisy=base[ego_id]["params"]["lidar_pose"]
        c=n=0
        for cav in base.values():
            p_clean=cav["params"]["lidar_pose_clean"]
            p_noisy=cav["params"]["lidar_pose"]
            dc=math.hypot(p_clean[0]-ego_clean[0], p_clean[1]-ego_clean[1])
            dn=math.hypot(p_noisy[0]-ego_noisy[0], p_noisy[1]-ego_noisy[1])
            c+=dc<=comm_range
            n+=dn<=comm_range
        deltas.append(c-n)
    ctr=Counter(deltas)
    nonzero=sum(v for kk,v in ctr.items() if kk!=0)
    print(pos_std, "nonzero", nonzero, "/", len(deltas), "hist", dict(sorted(ctr.items())))

run(1.0)
run(10.0)
PY
```

## Likely Cause: Mixed Envs + Image-Match Online Runtime Inputs (Hypothesis)

Given:
- `imagematch_*` improves AP far more than it improves `rel_error_stats`,
- `best == stable` and `noinit == current` (suggesting the method knobs are ineffective),
- and the append jobs are executed under a different python env than the core run,

we should treat `imagematch_*` as *suspect until proven effective*.

Additionally, the **online pose-provider runtime** historically built a minimal `base_data_dict`
containing only `lidar_pose` (+ optional `lidar_pose_clean`) and **did not include `camera_data`** (已在后续修复)：

- `HEAL/opencood/utils/pose_provider_runtime.py:731` (base_data_dict construction)

But the image-match corrector requires `camera_data` + intrinsics to run:

- `HEAL/opencood/extrinsics/pose_correction/stage1_image_match.py:124` (`_extract_camera_info` reads `camera_data` + intrinsics)

Action item (to make this benchmark self-validating):
- log `pose_provider_applied` / “pairs matched” counters into YAML,
  and hard-gate runs where a method never applies any pose update.

Update (2026-02-23, confirmed):
- imagematch 的 online payload wiring 已修复；但在统一条件下默认安全门限仍常见 `pose_provider_applied_count=0`，
  因而 imagematch 的“真实效果”应按 **no-op（等价 baseline）**对待，除非你明确选择更强 matcher/放松门限并重新跑 benchmark。
- 同理，LiDAR 的 online lidar_reg/hkust 在 payload 未就绪时可能退化为 no-op；应以统一条件新 run_id 的结果为准。

## Pose Accuracy (Rel Errors) — Camera / noise10

Pose accuracy metrics are logged by `inference_w_noise.py` into per-task YAML files under the camera model directory:

- `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/AP030507_*.yaml`

Each YAML contains `rel_error_stats[0]` with:

- `rel_trans_m.mean` (meters)
- `rel_yaw_deg.mean` (degrees)
- `rel_success_at_m[2]` (fraction of non-ego pairs with <2m relative translation error)

Mean over noise std `1..10` (camera/noise10, OPV2V):

| method | strategy | mean AP@0.5 | mean rel_trans_m | mean rel_yaw_deg | success@2m |
| --- | --- | ---: | ---: | ---: | ---: |
| baseline | bounds | 0.1061 | 6.869 | 4.402 | 0.184 |
| imagematch_noinit | best | 0.1719 | 6.730 | 4.440 | 0.191 |
| imagematch_current | best | 0.1719 | 6.730 | 4.440 | 0.191 |
| v2xregpp | best | 0.1110 | 10.939 | 11.624 | 0.211 |
| freealign | best | 0.0987 | 9.682 | 16.031 | 0.177 |
| vips | best | 0.0701 | 17.782 | 27.726 | 0.112 |
| cbm | best | 0.0525 | 34.927 | 57.798 | 0.004 |
| oracle | bounds | 0.3020 | 0.000 | 0.000 | 1.000 |

Interpretation (provisional):

- On this run, **`imagematch_*` has pose errors very close to baseline**, i.e., it does **not** show a strong pose-accuracy advantage.
- Some box-based methods show higher `success@2m` (e.g. `v2xregpp`), but also heavier tails (large outliers) which inflate the mean errors.
- Because `imagematch_*` improves AP@0.5 much more than it improves pose errors, the AP jump likely involves additional factors (e.g., comm-range gating differences) and should be sanity-checked before concluding image-match “beats” others.

## Downstream Detection (AP@0.5) — Camera / drop20 (Partial)

Only `noise=1..3` are finished so far (camera/drop20):

| noise std | vips_prior (best) | cbm_prior (best) | imagematch_noinit (best) | imagematch_current (best) |
|---:|---:|---:|---:|---:|
| 1.0 | 0.140 | 0.100 | 0.340 | 0.340 |
| 2.0 | 0.110 | 0.090 | 0.220 | 0.220 |
| 3.0 | 0.090 | 0.080 | 0.180 | 0.180 |

Remaining `drop20` noise levels (4..10) are still running for these methods; lidar append has not started yet.
