# Core Benchmark Runbook v1（统一/公平/可引用）

更新：2026-03-05

这份 runbook 是给“跑数 + 复盘 + 引用”用的**唯一入口**（其它文档只做 rationale / 证据链 / 历史记录）。

---

## 0) TL;DR（30 秒）

你在跑的“题目”必须完整写成：

`{dataset, modality, comm_range, comm_range_gating(track), solver_backend, runtime_mode, pose_source, sweep, noise_axis, noise_target, stage1_cache, checkpoint, seed}`

任何一项不一致都等价于**变题**，不能混在一张表/一张图里对比。

---

## 1) 实验矩阵（core 必跑格子）

### 1.1 Lanes（必须区分；不允许混表）

- **Track-D（Diagnostic / 更公平可解释）**：`--comm-range-gating clean`
- **Track-S（System / 更贴近系统真实）**：`--comm-range-gating noisy`

> 注意：clean/noisy gating 不只是裁剪输入，它会改变 agent set + merged GT set；因此它是题目的一部分，不是“实现细节”。

### 1.2 Datasets / comm_range（当前 canonical）

- DAIR-V2X：`comm_range=100`（camera + lidar）
- OPV2V：`comm_range=70`（camera + lidar）
- V2V4Real：`comm_range=70`（当前仓库 canonical 先做 lidar；camera lane 另开）

### 1.3 Sweeps（core 引用口径）

- **core 主结论只引用**：`sweep=noise10`（noise axis 0..10）
- OPV2V 的 `drop20`（dropout=0.2）属于 *appendix lane*（系统鲁棒性），禁止与 core(noise10) 混成一条结论。

---

## 2) 语义冻结（P0 红线）

### 2.1 Online 语义（core 只允许这一套）

- `--solver-backend online_box`
- `--runtime-mode register_and_fuse`
- `--pose-source noisy_input`

禁止：`offline_map` 作为 core 主结论（只可用于 parity/debug）。

### 2.2 Noise axis（单位必须写清）

- paired sweep：`--sweep-mode paired`
- `pos_std_list = rot_std_list = 0,1,2,...,10`
- `--noise-target non-ego`

单位（来自实现定义）：
- `pos_std`：meters
- `rot_std`：degrees（yaw）

### 2.3 Bounds（baseline / single / oracle 必须精确定义）

- **baseline**：`--pose-correction none`（仍是 coop，多车融合）
- **single（唯一合法定义）**：`single_ego_only = baseline + --force-ego-input-only`
  - single 只跑 noise=0（出图画水平线）
  - 严禁用 `comm_range_override=0` 当 single（会改变 agent/GT set，可制造 `single > oracle` 假象）
- **oracle（必须写明是哪种 oracle）**：
  - core 统一用：`oracle_gt`（用 dataset clean pose 覆盖 non-ego pose；理论上应平线）
  - 禁止：图例/表格只写 “oracle”

### 2.4 compare-current（best-state gate pins 必须显式）

任何用到 `--pose-compare-current` 的方法线，必须显式 pin：
- `--pose-compare-distance-threshold`
- `--pose-current-precision-threshold`
- `--pose-min-precision-improvement`
- `--pose-min-matched-improvement`

否则 noise=0 也可能大量 apply（bad-apply），导致“曲线怪/排序漂移/不可复现”。

---

## 3) Methods（core methods；无初值/no-prior）

core methods（必须覆盖）：
- `v2xregpp_initfree`
- `freealign_paper`
- `vips_initfree`
- `cbm_initfree`

可选 appendix（不进入 core 主结论）：
- `*_stable`
- with-init / prior
- HKUST / image_match / lidar_reg 等 audit methods

---

## 4) Preflight（必须做，否则=高概率跑出“垃圾但看不出来”）

### 4.1 stage1 cache 结构/语义校验

必跑：
- `tools/validate_stage1_cache.py --stage1 <path>`
- `tools/validate_stage1_semantics.py --stage1 <path> --prefer-head200 --num-samples 20`

V2V4Real 强约束：
- stage1 必须是 **per-CAV local-frame**（否则配准方向/尺度会错，AP 曲线会被带歪）

### 4.2 checkpoint config gate

- 禁止 `pose_override.enabled=true` 混入 core（会取消 noise sweep 轴）
- `comm_range override` 与 checkpoint config 不一致时，必须显式 `--allow-comm-range-mismatch`（否则视为误跑）

---

## 5) Smoke 规程（必须能防假阳性）

通用：
- `--max-eval-samples 200` 只用于 smoke；summary 必须写明 `max_eval_samples`

V2V4Real 特例（避免 head 子集退化为单车）：
- 当 `comm_range=70 & comm_range_gating=clean` 做 smoke200 时，强制加：
  - `--eval-sample-start 294`
否则很容易出现 `record_len=1` 占比过高 → 所有方法曲线几乎一样（假阳性）。

---

## 6) 统一执行入口（10×3090 本地调度）

### 6.1 一键 pipeline（推荐）

Track-D：

```bash
.micromamba/envs/py39/bin/python -u tools/run_core_benchmark_pipeline.py \
  --tag core_D_$(date +%Y%m%d_%H%M%S) \
  --gpus 0,1,2,3,4,5,6,7,8,9 \
  --comm-range-gating clean \
  --dair-max-per-gpu 2 \
  --opv2v-max-per-gpu 3 \
  --v2v4real-max-per-gpu 2
```

Track-S：把 `--comm-range-gating noisy`。

### 6.2 利用率调参（先调这两个）

- `--max-per-gpu`：每张卡并发子进程数（最有效的吞吐提升手段）
- `--split-noise`：把每个 noise 点拆成独立 job（提升并行度；会产生 YAML shard，需 merge）

---

## 7) DoD（可引用的产物与硬 gate）

每个 run_dir 的 source-of-truth 必须齐全：
- `manifest.json`（DAIR/V2V4Real）或 `config_snapshot.json`（OPV2V）
- `results_ap50_from_yaml.json`（长格式曲线点）
- `plots_yaml/*.png`（AP30/50/70；ylim 必须固定 `[0,1]`；plot-dir 必须 clean）
- `summary.md`（必须写全 track/sweep/axis/pins）

硬 gate（FAIL=不可引用）：
- single 必须是 `single_ego_only`（且只跑 noise=0）
- oracle 必须显式为 `oracle_gt`（core lane）
- comm-range-gating 必须是 `clean|noisy`（禁 auto）
- 同一 noise 点各方法 `samples` 一致（非 single）

