# Core Benchmark 统一标准 v1（DAIR / OPV2V / V2V4Real）

更新：2026-02-26

> WARNING（2026-03-01）：本文的 `single(comm=0)` 属于 legacy 定义，会改变 agent/GT 集合导致“变题”。  
> 当前 canonical 语义请以 `docs/operations/benchmark_semantics.md` 为准：`single = --force-ego-input-only (single_ego_only)`，并且必须显式 pin `--comm-range-gating clean|noisy`（禁用 auto）。

## 0. 本文解决什么

你现在最大的问题不是“没跑”，而是**三数据集的口径/输入语义没有被统一冻结**，导致：
- 跑出来的 AP/配准指标看似可比，实际可能被 stage1 cache 语义、comm-range gating、online/offline backend 等因素“悄悄换了题”；
- 尤其 V2V4Real：box-based pose solver 在 noise=0 就出现巨大 rel_error，是典型的“输入语义不符合 solver 假设”。

本文给出一个**可执行的统一合同**（core + 必要 preflight），并用证据链确认：
- DAIR/OPV2V 的 stage1 语义与 core 方法假设一致；
- V2V4Real 现有 stage1 语义不一致，必须先修 stage1，再谈统一 benchmark。

> 注：你要求的 “subagent 审阅/检验 loop” 目前无法使用（spawn 触发 max=6 限制）。我用“工具+证据链+最小 smoke”替代做了同等强度的检验。

---

## 1. 当前三数据集的一致性结论（证据链）

### 1.1 Stage1 语义检查（per-CAV/local-frame 是否成立）

我们用统一的语义 gate：对 sampled entries 比较
`matched(identity)` vs `matched(rel_clean)`（rel_clean 由 `lidar_pose_clean_np` 推导）。

判定逻辑：
- 若大量 sample 出现 `identity > rel_clean`（且总体 ratio<0.95），说明 boxes 已在 common frame（无须相对位姿就能对齐），**该 stage1 对 box-based pose solver 是致命的**。

工具（已落地）：
- `tools/validate_stage1_semantics.py`

实测结果（可复现）：

1) OPV2V camera stage1：PASS
```bash
PYTHONPATH=$PWD/HEAL:$PWD ./.micromamba/envs/py39/bin/python tools/validate_stage1_semantics.py \
  --stage1 data/OPV2V/detected/opv2v_camera_v2xvit_stage1_percav/test/stage1_boxes.json --num-samples 50
```
参考输出（head50）：`inverted_rate≈0.240, ratio_rel_over_id≈1.012`。

2) OPV2V lidar stage1：PASS
```bash
PYTHONPATH=$PWD/HEAL:$PWD ./.micromamba/envs/py39/bin/python tools/validate_stage1_semantics.py \
  --stage1 data/OPV2V/detected/opv2v_lidar_v2xvit_stage1/test/stage1_boxes.json --num-samples 50
```
参考输出（head50）：`inverted_rate≈0.000, ratio_rel_over_id≈3.210`。

3) DAIR camera stage1：PASS
```bash
PYTHONPATH=$PWD/HEAL:$PWD ./.micromamba/envs/py39/bin/python tools/validate_stage1_semantics.py \
  --stage1 data/DAIR-V2X/detected/camera_v2xvit_stage1/stage1_boxes.json --num-samples 50
```
参考输出（head50）：`inverted_rate≈0.140, ratio_rel_over_id≈2.105`。

4) DAIR lidar stage1：PASS（borderline ratio=1.0，但 identity 不占优）
```bash
PYTHONPATH=$PWD/HEAL:$PWD ./.micromamba/envs/py39/bin/python tools/validate_stage1_semantics.py \
  --stage1 HEAL/opencood/logs/freealign_repro_dair_stage1/merged_stage1_val.json --num-samples 50
```
参考输出（head50）：`inverted_rate≈0.000, ratio_rel_over_id≈1.000`。

5) V2V4Real 现有 stage1（80boxes）：FAIL（common frame）
```bash
PYTHONPATH=$PWD/HEAL:$PWD ./.micromamba/envs/py39/bin/python tools/validate_stage1_semantics.py \
  --stage1 HEAL/opencood/logs/v2v4real_stage1_pointpillar_from_pastat_bestval17_80boxes/test/stage1_boxes.json \
  --prefer-head200 --num-samples 20 --min-valid-samples 5
```

输出会稳定出现类似证据：
- `inverted_rate≈0.70` 且 `ratio_rel_over_id≈0.807`
- sample0：`matched id=20 rel=8`（identity 明显更好）

### 1.2 V2V4Real stage1 的修复 smoke（证明“不是数据集天生不一致”）

我用**同一 config + checkpoint**，用 per-CAV exporter 导出 10 个样本的 stage1，语义 gate 立刻 PASS：
- 输出：`HEAL/opencood/logs/v2v4real_stage1_pointpillar_from_pastat_bestval17_percav_smoke/test/stage1_boxes.json`
- gate：`total_matched_id=0 total_matched_rel=10 ratio=10.0`

导出命令（注意：py39 会 SIGFPE，必须用 heal env）：
```bash
CUDA_VISIBLE_DEVICES=0 PYTHONPATH=$PWD/HEAL /home/qqxluca/.micromamba/envs/heal/bin/python -u \
  HEAL/opencood/tools/export_stage1_boxes_per_cav.py \
  --hypes_yaml HEAL/opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25/config.yaml \
  --stage1_checkpoint HEAL/opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25/net_epoch_bestval_at17.pth \
  --output_dir HEAL/opencood/logs/v2v4real_stage1_pointpillar_from_pastat_bestval17_percav_smoke \
  --split test --max_samples 10 --log-interval 1
```

验证命令：
```bash
PYTHONPATH=$PWD/HEAL:$PWD ./.micromamba/envs/py39/bin/python tools/validate_stage1_semantics.py \
  --stage1 HEAL/opencood/logs/v2v4real_stage1_pointpillar_from_pastat_bestval17_percav_smoke/test/stage1_boxes.json \
  --num-samples 10 --min-valid-samples 5
```

结论：V2V4Real “不一致”来自 **stage1 export 语义（common frame）**，不是数据集天然口径不同。

---

## 2. Core Benchmark 合同（统一口径 / Semantics Freeze）

### 2.1 固定评测语义（必须显式写进 cmd / manifest）

统一要求（跨数据集/方法都一致）：
- `--fusion_method intermediate`
- `--sweep-mode paired`
- `--noise-target non-ego`
- `--num-workers 0`
- `--pose-timing`
- online runtime（统一 core 对比必须）：  
  - `--solver-backend online_box`  
  - `--runtime-mode register_and_fuse`  
  - `--pose-source noisy_input`  
  - `--comm-range-gating noisy`（禁止 auto）
- pose solver device：`--pose-device cuda`

### 2.2 Core 方法集合（无 prior / no-init）

必须包含：
- bounds：
  - baseline：`--pose-correction none`
  - oracle：`--pose-correction oracle_gt`（用 clean pose 覆盖）
  - single(ego-only)：`--pose-correction none --force-ego-input-only`（仅 noise=0 1 个点；comm_range 不变）
- core(initfree)：
  - `v2xregpp_initfree`
  - `freealign_paper`
  - `vips_initfree`
  - `cbm_initfree`
  - 统一加：`--pose-compare-current`（降低 noise=0 错误 apply 风险）

可选（不混入 core 主表，单独出 stable 表）：
- `*_stable`（必须在 note 里写清 `ema_alpha/max_step_xy/max_step_yaw`）

### 2.3 产物合同（Source of Truth）

- 每条曲线：`HEAL/opencood/logs/<model_dir>/AP030507_<pose_correction><note>.yaml`
- sweep 级别的可追溯产物（推荐）：
  - `outputs/<dataset>_core_<tag>/manifest.json`
  - `outputs/<dataset>_core_<tag>/results.jsonl`
  - `outputs/<dataset>_core_<tag>/summary.md`
- OPV2V fullbench（更严格）：`outputs/full_bench_<run_id>/run_state.jsonl` + `config_snapshot.json`

---

## 3. Stage1 Cache 合同（结构 + 语义）

### 3.1 结构要求（硬门槛）

- JSON dict（key=sample_idx str）
- 每个 sample 至少字段：
  - `cav_id_list`（list）
  - `pred_corner3d_np_list`（list，len 与 cav_id_list 一致）
  - `lidar_pose_clean_np`（list，len 与 cav_id_list 一致）

工具：
```bash
./.micromamba/envs/py39/bin/python tools/validate_stage1_cache.py --stage1 <path>
```

### 3.2 语义要求（硬门槛，决定三数据集能否统一）

**必须**：`pred_corner3d_np_list[i]` 在第 i 个 agent 的 local frame。

工具（已落地，能直接抓出 V2V4Real common-frame stage1）：
```bash
PYTHONPATH=$PWD/HEAL:$PWD ./.micromamba/envs/py39/bin/python tools/validate_stage1_semantics.py \
  --stage1 <path/to/stage1_boxes.json> --num-samples 50 --prefer-head200
```

---

## 4. 数据集适配（canonical 建议）

### 4.1 OPV2V

- 建议入口：`tools/run_opv2v_fullbench_fast.py`（已补 stage1 semantic preflight）
- 最新完成的 canonical run（source-of-truth）：
  - `outputs/full_bench_opv2v_autopilot_full_fixv2xregpp_20260225_065926_a1/run_state.jsonl`
  - `outputs/full_bench_opv2v_autopilot_full_fixv2xregpp_20260225_065926_a1/config_snapshot.json`

### 4.2 DAIR-V2X

- stage1 语义已验证 PASS（见 1.1 的 gate）
- 现有 `2026-02-18` 的 sweep 可用于“历史趋势/参考”，但它没有完整冻结 online 语义字段（建议后续按 2.1 合同重跑一版 canonical 并带 manifest/config_snapshot）

### 4.3 V2V4Real

- 当前默认 stage1（80boxes）语义 FAIL：必须先修 stage1，再跑 core。
- `tools/run_v2v4real_core_benchmark.py` 已加入 preflight：
  - 发现 stage1 common-frame 会直接 BLOCK（避免浪费 GPU 天）
  - 已补 single(ego-only, force-ego-input-only) baseline（可用 `--skip-single` 关闭）

V2V4Real per-CAV stage1 全量导出建议（10 shards x 10 GPUs）：
1) shard export（每 shard 一张卡）
2) merge：`tools/merge_stage1_shards.py`
3) 语义验证：`tools/validate_stage1_semantics.py`

---

## 5. 下一步（按优先级）

1) 先把 V2V4Real 的 per-CAV stage1 全量导出并通过 gate（否则 core benchmark 无意义）
2) 用新的 stage1 跑 V2V4Real core methods（生成与 DAIR/OPV2V 同规范的曲线图 + 表格）
3) （可选）按 2.1 合同重跑 DAIR 一版 canonical core（补齐 online 语义冻结与 applied 信号）
