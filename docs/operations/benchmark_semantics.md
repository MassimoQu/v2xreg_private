# Benchmark Semantics Contract（Single / Comm-Range Gating / Oracle / Online vs Offline）

更新：2026-03-01

这份文档只做一件事：把 benchmark 的“题目”定义写死，避免被旧文档切片（尤其 single_comm0 / auto gating / offline_map）带歪。

适用范围：DAIR / OPV2V / V2V4Real（以及未来新增数据集）。

---

## 1) Single：唯一可比的定义是 `single_ego_only`（禁止把 comm=0 当 single）

### 1.1 禁止：`single_comm0`（legacy）

旧定义：`single = --comm-range-override 0`（comm_range=0）  
问题：会触发 dataset pruning，改变 **agent set** 和 **merged GT set**，导致“变题”，数值可能虚高，甚至出现 `single > oracle`。

证据（OPV2V, noise=0, max_eval_samples=200，其他语义冻结一致）：
- legacy `single_comm0`：AP50=0.9146  
  - YAML：`HEAL/opencood/logs/freealign_repro_opv2v_baseline/AP030507_none_legacy_single_comm0_20260301.yaml:1`
- canonical `single_ego_only`：AP50=0.8873  
  - YAML：`HEAL/opencood/logs/freealign_repro_opv2v_baseline/AP030507_none_canonical_single_ego_only_20260301.yaml:1`
- 运行日志与复现脚本：`outputs/single_contract_opv2v_20260301/`

证据（DAIR LiDAR, noise=0, max_eval_samples=200，同一 checkpoint；只改变 single 定义）：
- legacy `single_comm0`：AP50=0.4081  
  - YAML：`HEAL/opencood/logs/freealign_repro_dair_baseline/AP030507_none_dair_lidar_legacy_single_comm0_numpyvoxel_max200_20260301.yaml:1`
- canonical `single_ego_only`：AP50=0.3126  
  - YAML：`HEAL/opencood/logs/freealign_repro_dair_baseline/AP030507_none_dair_lidar_single_ego_only_max200_20260301.yaml:1`

证据（comm_range=0 会改变 merged GT set；同一批样本 head200 的 GT count 统计）：
- OPV2V（comm70 vs comm0）：mean GT `17.745 -> 17.045`  
  - `outputs/single_contract_opv2v_20260301/gt_counts_comm_range_70_vs_0_first200.json:1`
- DAIR（comm100 vs comm0）：mean GT `13.935 -> 7.655`（变化更大）  
  - `outputs/single_contract_gt_counts_20260301/dair_gt_counts_comm_range_100_vs_0_first200.json:1`
- V2V4Real（comm200 vs comm0）：mean GT `4.590 -> 2.675`  
  - `outputs/single_contract_gt_counts_20260301/v2v4real_gt_counts_comm_range_200_vs_0_first200.json:1`

> 注：这里用 `comm_range=200` 只是为了直观演示“comm=0 会改变 merged GT set”。本仓库 V2V4Real(PASTAT) 的 canonical core setting 是 `comm_range=70`（见 `docs/operations/fair_core_benchmark_setting_v1_20260301.md` 的 V2V4Real 条目）。`cr70` 与 `cr200` 属于不同题目，禁止混表/混命名。

### 1.2 规定：`single_ego_only`（canonical）

目标：**保持同一 comm_range、同一 merged GT labels（任务难度不变）**，但 forward 只吃 ego 输入（不通信）。

实现（OpenCOOD intermediate/early fusion 通用）：
- `HEAL/opencood/tools/inference_w_noise.py --force-ego-input-only`

单次评测约束：
- single 只需要跑噪声点 `0`（画图时作为一条水平线即可；不要用 comm=0 造“单车曲线”）。

---

## 2) Comm-Range Gating：必须显式冻结（禁止 `auto`）

定义：通信范围裁剪时，用哪个 pose 计算 ego↔cav 的距离。

- `--comm-range-gating clean`：用 `lidar_pose_clean` 裁剪 → **agent set 固定**（更“诊断公平”）
- `--comm-range-gating noisy`：用 `lidar_pose` 裁剪 → **agent set 可能随噪声变化**（更“系统真实”）
- `--comm-range-gating auto`：禁止用于 benchmark（会被 solver_backend/runtime_mode/pose_correction 等隐式影响，导致 confound）

代码锚点（pruning 发生在 dataset `__getitem__`）：
- `HEAL/opencood/data_utils/datasets/intermediate_fusion_dataset.py:381`
- `HEAL/opencood/data_utils/datasets/intermediate_heter_fusion_dataset.py:454`

证据（不同数据集 noisy gating 的敏感度差异）：
- `docs/operations/dataset_comm_range_and_gating_analysis_20260228.md:1`

---

## 3) Oracle：必须写清是哪一种 oracle（不要混叫）

### 3.1 `oracle_gt`（GT clean pose 覆盖）

- 命令：`--pose-correction oracle_gt`
- 含义：用 dataset 自带 `lidar_pose_clean` 覆盖非 ego 的 `lidar_pose`（上界）。

### 3.2 `v2vloc_oracle_*`（V2VLoc-style oracle）

- 命令：`--pose-correction v2vloc_oracle_initfree|stable`
- 含义：从 stage1 cache 的 `lidar_pose_clean_np` 读取 clean pose 覆盖（不是 `oracle_gt`；依赖 stage1 字段存在且正确）。

规则（强制）：**曲线/表格的 method 名必须等于 `--pose-correction` 字符串**（例如 `oracle_gt`, `v2vloc_oracle_initfree`），不要再用模糊的 “oracle”。

### 3.3 “oracle 应该平线吗？”

首先要分清 **oracle 的实现**，否则会出现“你以为是 bug，其实是定义不一样”：

- `oracle_gt`（当前代码）在 `online_box/offline_map` 下会 **显式关闭 pose noise 注入**（`add_noise=False`），因此它按定义就是“clean-everything upper bound”，**曲线应当严格平线**。  
  代码锚点：`HEAL/opencood/tools/inference_w_noise.py:1098`（offline_map）与 `HEAL/opencood/tools/inference_w_noise.py:1114`（online_box + method=gt）。
- `v2vloc_oracle_*` **不会**走上述“禁噪”分支（仍会注噪），它只是把 pose 覆盖为 clean（来自 stage1 字段）。在 `comm-range-gating=noisy` 时，agent set 仍可能随噪声抖动，因此 AP 允许轻微漂移（属于系统效应，不一定是 bug）。

在你明确了 oracle 的实现后，再讨论 gating：
- 若 `comm-range-gating=clean`（agent set 固定）→ oracle 更接近平线；
- 若 `comm-range-gating=noisy`（agent set 随噪声可能变化）→ **只有“保留注噪的 oracle”** 才可能出现轻微漂移；`oracle_gt` 仍应平线。

---

## 4) Online vs Offline：`online_box` 与 `offline_map` 不能混着做方法对比

### 4.1 语义差异（必须先承认这不是同一个 benchmark）

⚠️ 默认值陷阱：`HEAL/opencood/tools/inference_w_noise.py` 默认 `--solver-backend offline_map` 且 `--comm-range-gating auto`；跑 core benchmark 必须显式指定 `online_box + comm-range-gating=clean|noisy`。

- `online_box`：pose solver 在 runtime（`pose_provider`）中执行；dataset pruning 已发生；修正发生在 forward 前。
  - 关键点：comm-range pruning 的 clean/noisy 选择会影响“是否有非 ego 可用”，从而影响 applied 率与曲线形态。
- `offline_map`：先离线跑 solver 生成 override map，再在 dataset `__getitem__` 里注入。
  - 当前实现会在评测阶段把 dataset 的 `noise_setting.add_noise` 强制置为 false（对 pose-correction/offline_map 分支），导致 **noise/gating 轴语义与 online_box 不同**；因此 offline_map 只能用于 parity/调试，禁止与 online_box 混表/混结论。

代码锚点（offline_map 路径关闭 noise）：
- `HEAL/opencood/tools/inference_w_noise.py:1093`

### 4.2 实验事实（OPV2V parity，pos/rot=10/10，max_eval_samples=200）

source-of-truth YAML：
- A online_box + gating=clean：`HEAL/opencood/logs/freealign_repro_opv2v_baseline/AP030507_v2xregpp_initfree_parity_A_online_box_gating_clean_pos10_rot10_cr70_max200_20260301.yaml:1`
- B online_box + gating=noisy：`HEAL/opencood/logs/freealign_repro_opv2v_baseline/AP030507_v2xregpp_initfree_parity_B_online_box_gating_noisy_pos10_rot10_cr70_max200_20260301.yaml:1`
- C offline_map + gating=clean：`HEAL/opencood/logs/freealign_repro_opv2v_baseline/AP030507_v2xregpp_initfree_parity_C_offline_map_gating_clean_pos10_rot10_cr70_max200_20260301.yaml:1`
- D offline_map + gating=noisy：`HEAL/opencood/logs/freealign_repro_opv2v_baseline/AP030507_v2xregpp_initfree_parity_D_offline_map_gating_noisy_pos10_rot10_cr70_max200_20260301.yaml:1`

现象摘要：
- offline_map 下切 gating 基本不变（C==D）→ 因为它不是在“带噪姿态 + noisy gating”的同一语义里评测。
- online_box 的 applied 率显著更低（mean `pose_provider_applied_count` ≈ 0.41），而 offline solver applied≈0.93（186/200）。
  - 解释：online 路径先 pruning，很多样本只剩 ego → 没有可修正对象；offline solver 用的是全 agent set（retrieve_base_data）→ applied 更高。

运行日志：`outputs/parity_opv2v_online_offline_20260301/`

---

## 5) 推荐：一套“最公平且可解释”的 core benchmark 设置

为了同时满足“公平可比”与“系统真实”，建议明确两条 lane（不要混在一张 core 表里）：

1) **Track-D（Diagnostic / 更公平）**：`online_box` + `comm-range-gating=clean`  
   - 目的：固定 agent set，只衡量“对齐误差 → AP”。
2) **Track-S（System / 更真实）**：`online_box` + `comm-range-gating=noisy`  
   - 目的：包含真实系统的邻居裁剪抖动；若使用“保留注噪的 oracle”（如 `v2vloc_oracle_*`）则 AP 可能轻微漂移（`oracle_gt` 按当前实现仍应平线）。

两条 lane 的共同冻结项（必须一致）：
- `--fusion_method intermediate`
- `--sweep-mode paired`
- `--noise-target non-ego`
- noise axis：`pos_std_list=rot_std_list=0..10`
- `--solver-backend online_box --runtime-mode register_and_fuse --pose-source noisy_input`
- `single=--force-ego-input-only`（只跑 noise=0）
- oracle：必须写清 `oracle_gt` 或 `v2vloc_oracle_*`，并在表格里按真实 pose_correction 名展示
