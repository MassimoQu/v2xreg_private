# OPV2V Append (Init/No-init/HKUST) Partial Results (2026-02-22)

This note snapshots the *current* (partial) results for the OPV2V append sweep that adds:

- `vips_prior`, `cbm_prior`
- `imagematch_noinit`, `imagematch_current`
- `lidarreg_ransac`, `hkust_teaser`, `hkust_fgr`, `hkust_quatro`

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

Additionally, the current **online pose-provider runtime** builds a minimal `base_data_dict`
containing only `lidar_pose` (+ optional `lidar_pose_clean`) and **does not include `camera_data`**:

- `HEAL/opencood/utils/pose_provider_runtime.py:731` (base_data_dict construction)

But the image-match corrector requires `camera_data` + intrinsics to run:

- `HEAL/opencood/extrinsics/pose_correction/stage1_image_match.py:124` (`_extract_camera_info` reads `camera_data` + intrinsics)

Action item (to make this benchmark self-validating):
- log `pose_provider_applied` / “pairs matched” counters into YAML,
  and hard-gate runs where a method never applies any pose update.

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
