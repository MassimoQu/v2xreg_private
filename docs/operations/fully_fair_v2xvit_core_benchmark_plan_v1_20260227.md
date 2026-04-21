# Fully-Fair Core Benchmark Plan (V2XViT-unified) v1 — DAIR / OPV2V / V2V4Real

更新：2026-02-27

目标：把 **core(no-init/no-prior)** 配准方法（`v2xregpp/freealign/vips/cbm`）在 **DAIR / OPV2V / V2V4Real** 上做到“完全公平”的对比，具体含义是：

1) **同一数据集内公平**：固定同一套 `checkpoint(model_dir) + stage1 cache + noise schedule + comm-range 语义 + runtime 语义`，只替换 pose-correction 方法；
2) **跨数据集也尽量公平**：三数据集使用 **同一类 baseline 网络家族（V2XViT）**，避免因为 backbone/fuser 不一致导致“方法差异”与“网络差异”纠缠。

> 注：跨数据集的 AP 绝对值不做直接横比，结论以“各数据集内的排序/增益”为主；但 backbone 统一可以减少解释成本。

---

## 0) 决策点（你需要先选定）

**D0. comm-range gating 用 noisy 还是 clean？**
- 推荐默认：`noisy`（更贴近线上：通信可达性按 noisy 位姿裁剪；并且所有方法一致，不会 cross-method confound）。
- 若你希望 oracle 严格平线（完全固定 agent set）：选 `clean`（更像“理想通信”）。

**D1. 噪声轴是否统一为 0..10（包含 0）？**
- 推荐：统一 `0..10`，paired sweep（pos_std=rot_std），便于三数据集同规格出图。

下面计划按 **D0=noisy, D1=0..10** 写；如果你选其它，直接替换合同字段即可。

---

## 1) 统一合同（Semantics Freeze）

所有数据集/方法统一固定（必须显式写进 cmd / snapshot）：

- eval driver：`HEAL/opencood/tools/inference_w_noise.py`
- `--fusion_method intermediate`
- `--sweep-mode paired`
- `--noise-target non-ego`
- `--pos-std-list 0,1,2,3,4,5,6,7,8,9,10`
- `--rot-std-list 0,1,2,3,4,5,6,7,8,9,10`
- `--num-workers 0`
- online runtime（统一 core 对比必须）：
  - `--solver-backend online_box`
  - `--runtime-mode register_and_fuse`
  - `--pose-source noisy_input`
  - `--comm-range-gating noisy`（禁止 auto）
- pose solver：
  - `--pose-device cuda`
  - `--pose-timing`
- 单车（single）定义（统一）：**同 comm_range 下只保留 ego 输入、保持 GT label 不变**
  - `--pose-correction none`
  - `--force-ego-input-only`
  - single 只跑噪声点 `0`（噪声对 single-forward 无意义；图里按 flat line 画）

---

## 2) 方法集合（Core only）

- bounds：
  - baseline：`--pose-correction none`
  - oracle：`--pose-correction oracle_gt`
  - single：见上
- core(initfree)（都加 `--pose-compare-current` 防止坏解强行 apply）：
  - `v2xregpp_initfree`
  - `freealign_paper`
  - `vips_initfree`
  - `cbm_initfree`

可选稳定版（不混入 core 主表；单独出 stable 表）：
- `v2xregpp_stable/freealign_paper_stable/vips_stable/cbm_stable`

---

## 3) Fail-fast Gates（跑 full 前必须过）

### G1. stage1 cache 结构 gate
- `tools/validate_stage1_cache.py --stage1 <path>`

### G2. stage1 cache 语义 gate（per-CAV local frame）
- `tools/validate_stage1_semantics.py --stage1 <path> --prefer-head200 --num-samples 50`

### G3. no-op gate（online applied 信号）
从 YAML 的 `timing_stats[*].pose_timing.pose_provider_applied_count` 判断：
- bounds 允许为 0
- core 方法 **不得全 0**（否则视为 no-op，不参与结论）

---

## 4) 数据集落地（统一为 V2XViT baseline）

### 4.1 DAIR（已有 V2XViT）
- 使用现有 v2xvit model_dir（camera/lidar）与对应 stage1 cache
- 需要补：按“统一合同”重跑一版 online_box core（因为历史 DAIR 聚合不是严格同 schema）

### 4.2 OPV2V（把 lidar baseline 也切到 V2XViT）
- camera model：`HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope`
- lidar model（建议换成 v2xvit）：`HEAL/opencood/logs/HeterBaseline_opv2v_lidar_v2xvit_calibfree_2026_01_22_00_20_19`
- stage1：
  - camera：`data/OPV2V/detected/opv2v_camera_v2xvit_stage1_percav/test/stage1_boxes.json`
  - lidar：`data/OPV2V/detected/opv2v_lidar_v2xvit_stage1/test/stage1_boxes.json`

必须修正：
- OPV2V 的 single 不再用 `comm_range_override=0`（会改变 GT set，导致 single 数值虚高）；统一改为 `--force-ego-input-only`。

### 4.3 V2V4Real（需要新增 V2XViT 训练产物）
目前 repo 没有现成 `v2v4real_*v2xvit*` checkpoint，需要补齐：

1) 训练 V2V4Real LiDAR V2XViT baseline（DDP 10x3090）
2) 用该 checkpoint 导出 per-CAV stage1 cache（sharded + merge + 语义 gate）
3) 用同一 checkpoint + stage1 跑 core benchmark

---

## 5) 执行流水线（高利用率 + 容错）

### 5.1 调度策略（无 Slurm 时）
- 默认用脚本内 scheduler（多 GPU + `--max-per-gpu` + `--split-noise`）拉满 CPU/GPU：
  - OPV2V fullbench：`--max-per-gpu 2~3`
  - V2V4Real core：`--max-per-gpu 2` + `--split-noise`

### 5.2 容错/恢复
- 每个 run_dir 写 manifest + results.jsonl；已完成的 YAML 自动跳过
- 任一 job 失败不阻塞其它 job；最终汇总时报告 failures（需要补跑的最小集合）

---

## 6) DoD（完成判据）

每个数据集都要交付：
- `outputs/<dataset>_core_<tag>/manifest.json`
- `preflight.log`（stage1 结构/语义 PASS）
- `results.jsonl` + `summary.md`
- `plots_yaml/`（AP30/AP50/AP70，single 以 flat line 展示，AP 图 y 轴固定 0~1）
- no-op gate：core 方法 applied_count 不得全 0

最终交付：
- 三数据集 core 的对比表（每数据集内排序 + 增益 + timing）
- 清晰说明“跨数据集不可直接比 AP 绝对值”的解释边界

