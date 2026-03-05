# 配准评估 ↔ 协同感知 AP：对应关系与 AP 预估（可溯源，2026-02-24）

你要的事情其实分两步：

1) 用“已经跑过的实验”把 **registration metrics**（success@2m / rel_trans / rel_yaw）和 **coop-perception AP**（AP50）之间的对应关系建起来；  
2) 用这个对应关系去**预估**某个方法（或某一组参数）在相同条件下大概会得到什么 AP（并说明误差/失效场景）。

本文件给出可复核的证据链（输入 CSV、脚本、产物路径），并尽量用“控制混杂因素”的口径描述这个关系。

---

## 0) Source-of-Truth（可复核输入/输出）

输入（长表，逐 noise 点）：
- `outputs/benchmark_fullmatrix_20260220/combined_noise_curve_long.csv`
  - 每行：`dataset/suite/modality/method/strategy/noise/ap50/mean_rel_trans_m/mean_rel_yaw_deg/success_at_2m/source`

报告生成脚本（可重复运行）：
- `tools/build_pose_error_to_ap_mapping_report.py`

本次生成的产物（含预测点表 + 图）：
- `outputs/pose_error_to_ap_mapping_report_20260224/mapping_summary.json`
- `outputs/pose_error_to_ap_mapping_report_20260224/pred_points.csv`
- `outputs/pose_error_to_ap_mapping_report_20260224/plots/scatter_*.png`

生成命令（复跑）：

```bash
.micromamba/envs/v2x/bin/python tools/build_pose_error_to_ap_mapping_report.py \
  --csv outputs/benchmark_fullmatrix_20260220/combined_noise_curve_long.csv \
  --out-dir outputs/pose_error_to_ap_mapping_report_20260224 \
  --methods baseline,oracle,v2xregpp,freealign,vips,cbm
```

---

## 1) 对应关系怎么建（尽可能“公正”）

### 1.1 先说清楚：我们在做什么、没在做什么

- 这里给的是 **经验映射**（descriptive mapping），不是“严格因果证明”。
- 为了避免被噪声轴（n=1..10）主导，我们至少要求：
  - 数据来自同一套 benchmark 口径（同 dataset/suite/modality 的同口径统计字段）；
  - 映射形式简单可解释，优先用最常用的注册指标：
    - `success@2m`（相对位姿误差 <=2m 的比例）
    - `mean_rel_yaw_deg`
    - （`mean_rel_trans_m` 也在 summary 里做相关性对照）

### 1.2 用的模型（可解释，便于预估）

对每个 group（`dataset/suite/modality`）单独拟合：

`AP50 ≈ b0 + b1 * success_at_2m + b2 * mean_rel_yaw_deg`

系数/拟合误差写在：
- `outputs/pose_error_to_ap_mapping_report_20260224/mapping_summary.json`

---

## 2) 结果：配准指标与 AP 的对应强度（相关性 + 拟合误差）

下面所有数字都来自 `mapping_summary.json`（每组 n=100 点，对应 10 个 noise × 10 条方法线）。

### 2.1 DAIR-V2X / noise10

- camera：
  - Pearson(AP50, success@2m) = **0.838**
  - Pearson(AP50, rel_trans_mean) = **-0.729**
  - Pearson(AP50, rel_yaw_mean) = **-0.619**
  - 拟合：`coef=[0.02496, 0.02271, -0.000111]`，RMSE=**0.00423**
  - 解释：camera 的 AP 基本盘子小，但“配准越好 AP 越高”的趋势是存在的，只是增益空间有限。

- lidar：
  - Pearson(AP50, success@2m) = **0.768**
  - Pearson(AP50, rel_trans_mean) = **-0.365**
  - Pearson(AP50, rel_yaw_mean) = **-0.497**
  - 拟合：`coef=[0.25651, 0.12311, -0.000164]`，RMSE=**0.03623**

### 2.2 OPV2V / noise10 与 drop20（核心方法集合）

（注意：OPV2V 的绝对数值受 benchmark 合同影响更大；如果你要求 *strictly unified*，建议用新的 unified run_id 复跑。但“对应关系是否强”这件事，在现有 core 集上已经很明确。）

- camera/noise10：
  - Pearson(AP50, success@2m) = **0.979**
  - 拟合：`coef=[0.06808, 0.21693, -0.000122]`，RMSE=**0.01423**

- lidar/noise10：
  - Pearson(AP50, success@2m) = **0.948**
  - 拟合：`coef=[0.36430, 0.58371, 0.001603]`，RMSE=**0.06040**

对应散点图：
- `outputs/pose_error_to_ap_mapping_report_20260224/plots/scatter_OPV2V_noise10_camera.png`
- `outputs/pose_error_to_ap_mapping_report_20260224/plots/scatter_OPV2V_noise10_lidar.png`

---

## 3) 用它“预估 AP”到底靠谱不：看每条方法线的平均误差

`mapping_summary.json` 里已经给出每个 group 的 `per_method_mean_error`：

你可以用它回答两类问题：

1) **同一个方法在不同 noise 上**：配准指标变化 → AP 变化是否跟得上（通常 lidar 更一致）；  
2) **不同方法在同 noise 上**：谁的 registration 更好，谁的 AP 一般也更高（在 OPV2V 上尤为明显）。

例子（OPV2V camera/noise10）：
- `vips(best)`：模型倾向 **高估**（mean_pred > mean_ap），说明存在“配准看起来还行，但 AP 掉得更狠”的额外因素（例如下游融合对误差更敏感/或某些错误类型被 success@2m 掩盖）。

这就是我会强调“尽可能公正”的点：  
**registration metrics 能解释 AP 的主要趋势，但不是 100% 充分统计量**；你在比较方法时要把偏差/失配方法标出来，而不是把拟合当真值。

---

## 4) 你要用这套映射做什么（建议的使用方式）

### 4.1 预估新方法/新参数的 AP（还没跑下游融合）

前提：你已经有同口径的注册评估结果（至少 success@2m + mean_rel_yaw_deg），并且确定该方法在运行时**不是 no-op**（例如 `pose_provider_applied_count>0`）。

做法：
1) 选对 group（dataset/suite/modality）
2) 用该 group 的系数代入：
   - `AP50_pred = b0 + b1*success@2m + b2*mean_rel_yaw_deg`
3) 以该 group 的 RMSE 作为“预估误差尺度”

### 4.2 识别“配准很好但 AP 没提升”的异常

如果 `success@2m` 明显上升，但 AP50 没升甚至下降：
- 要优先排查是否存在 **策略/门限** 改变了下游行为（例如 gating/过滤 confound）
- 或注册误差类型变化（例如 yaw 大但 trans 小，被 success@2m 掩盖）
- 或方法其实部分样本 no-op / apply 很稀疏（看 `pose_provider_applied_count`）

---

## 5) 关于你提到的“camera 也是 dataloader 没改好？”（结论）

你在 OPV2V smoke 里看到的 camera `imagematch_*` 等价 baseline，**不是 dataloader 没导出图像**：
- 从 `outputs/full_bench_opv2v_unified_smoke_20260223_fix1/results_ap50_from_yaml.json` 可见 `pose_match_sec` 是秒级，说明 matcher 过程确实跑了；
- 但 `pose_provider_applied_count=0`，说明在当前安全门限/质量条件下没有 apply 更新（因此 AP 等于 baseline）。

真正需要 dataloader 修的，是 LiDAR `lidar_reg/hkust` 这类 raw 注册对 `lidar_np_by_cav` 的依赖（已修复并在文档里标注）：
- `docs/operations/lidarreg_noop_root_cause_and_rerun_20260224.md`

---

## 6) 为什么“配准指标 ↔ AP”会出现飘动（drift）：你需要在文档里明确的解释链

这里的“飘动”指的是：你观察到同样的配准指标（例如 `success@2m` 或 `mean_rel_trans_m`）在不同条件下，对应的 AP50
增益并不恒定；甚至出现 “配准看起来更好，但 AP 没涨/反而掉” 这种不直觉的点。

为了可溯源，这里把原因分成两类：**假飘动（confound/无效点导致）** 和 **真飘动（指标信息不足 + 下游非线性导致）**。

### 6.1 假飘动：实际上不是“指标不相关”，而是 benchmark 条件不一致/方法没生效

1) **语义冻结没做好：同一条曲线其实跑在不同合同下**
- 典型例子：OPV2V online runtime 下 `comm_range` pruning 可能在 pose-correction 开启时隐式切换语义；
  如果 baseline 用 noisy pose 做 gating，而某个方法线用了 clean pose gating，则 AP 的变化混进了“纳入更多车参与融合”的收益。
- 解决方式：强制使用并记录 `--comm-range-gating {noisy|clean}`，并写入 `config_snapshot.json`。
  相关合同/证据链：`docs/operations/unified_benchmark_contract_and_comparison_20260220.md`、
  `docs/operations/opv2v_unified_fullbench_plan_20260223.md`。

2) **方法线 silent no-op：配准逻辑没 apply / 早退，但仍然产出 AP**
- 典型信号：`pose_provider_applied_count=0`，此时该方法线等价 baseline（AP 当然对不上“配准指标改善”的预期）。
- camera/imagematch 的 no-op 审计：`docs/operations/imagematch_initfree_remote_audit_20260223.md`
- lidar_reg/hkust 的 no-op 根因与修复：`docs/operations/lidarreg_noop_root_cause_and_rerun_20260224.md`

3) **mixed-version / mixed-env：同一 run_id 里 mid-run 修复混写**
- 同一 run_id 下，不同任务对应不同 HEAL commit/不同 python env，会直接破坏“同口径可比性”。
- 证据/案例：`docs/operations/opv2v_append_partial_results_20260222.md`

结论：你看到的“飘动”里相当一部分，其实是 **合同漂移** 或 **无效点污染**，不是“配准指标本身无用”。

### 6.2 真飘动：即使合同完全一致，配准指标也不是 AP 的充分统计量

1) **指标信息损失（aggregation）**
- `mean_rel_trans_m` / `mean_rel_yaw_deg` 是均值；`success@2m` 是阈值命中率。
- 下游 AP 对少量“关键帧/失败帧”（例如车多、远距多、目标密集）更敏感；因此两个方法即使均值/成功率接近，
  只要误差分布的 tail 不同（例如 p90/p95 更差），AP 也可能差很多。

2) **误差类型权重不一致**
- AP@0.5 对横向误差、yaw 误差、远距误差往往更敏感；而 `success@2m` 会把多维误差压缩成一个布尔阈值，
  可能出现 “success@2m 提升，但 yaw 结构更差 -> AP 不涨/下降”。

3) **下游是强非线性系统（阈值/量化/排序）**
- IoU=0.5 的阈值、NMS、置信度排序、BEV/voxel 的栅格量化都会引入“阶梯/饱和”效应：
  在临界区间 AP 会跳变；接近上限时又会饱和不涨。

4) **数据集/模态的动态范围不同**
- OPV2V 多车多视角，配准直接决定融合是否有效，AP 动态范围大，所以相关性往往更强；
- DAIR 的 camera AP 盘子更小、瓶颈可能在检测本体/域差，导致同样幅度的配准改善，AP 增益空间有限。
  这也是为什么同样用 `success@2m`，OPV2V 的相关性更高，而 DAIR 更“松”。

### 6.3 如何把“真飘动”压下去（后续改进建议，仍保持可复核）

如果你希望映射更稳健（更接近“可迁移的预估器”），建议逐步把长表扩展为：
- 增加分位数/尾部：`p50/p90/p95 rel_trans`、`p90/p95 yaw`（而不是只看 mean）
- 增加分桶：按目标距离/目标数量加权的 success@x（而不是全局平均）
- 增加有效性信号：`pose_provider_applied_count`、apply rate（避免 silent no-op 混入）

这些改动要以 **同口径 long.csv** 为 source-of-truth（让每一列都能从 YAML/日志溯源）。

---

## 7) 推荐的“可复核使用方式”：用映射做筛选/预估，但不替代真实 AP

当某条方法线暂时还没接到下游协同感知（没跑 AP），但你已经有同口径的注册评估结果时：

1) **先过有效性 gate**（否则任何预估都没意义）
- 必须确认方法线不是 no-op：`pose_provider_applied_count > 0`（或至少 > very small threshold）。
- 如果为 0：直接标注为 “baseline 等价”，不要进入拟合/预估。

2) **选对 group**（必须同 dataset/suite/modality）
- 例如：`OPV2V/noise10/lidar` 的系数不能用到 `DAIR/noise10/camera` 上。

3) **给出“预估值 + 误差尺度”**
- 用该 group 的拟合系数输出 `AP50_pred`；
- 用该 group 的 RMSE 作为“误差条”的尺度（例如 ±RMSE 作为粗置信区间）。

4) **把它当作筛选/止损工具**
- 用于决定“哪些方法值得花完整 fullbench 成本去跑”；
- 或作为 sanity check：配准指标很好但 AP 预估极差/异常时，优先排查 wiring/合同漂移。

---

## 8) 下一步：在“最新 unified fullbench 条件”为基准重算映射（避免历史污染）

当前映射来自 `outputs/benchmark_fullmatrix_20260220/combined_noise_curve_long.csv`，
它汇总了你当时认为“可用”的 core methods；但你要做最终 paper-level 的 fullmatrix，
仍然建议在 **全新 unified run_id（git clean + comm-range gating 冻结）** 上重算一遍：

1) 先用 unified run 生成新的 long.csv（同口径）：
- `tools/summarize_opv2v_fullbench_from_yaml.py`
- `tools/build_fullmatrix_benchmark_report.py`

2) 再复跑映射报告：
```bash
.micromamba/envs/v2x/bin/python tools/build_pose_error_to_ap_mapping_report.py \
  --csv <new_combined_noise_curve_long.csv> \
  --out-dir outputs/pose_error_to_ap_mapping_report_<new_date> \
  --methods baseline,oracle,v2xregpp,freealign,vips,cbm
```

验收标准：
- 映射输出必须能定位到每个点的 `source`（YAML 路径）；
- 过滤规则明确（尤其 no-op/混合同点不进入统计）；
- 关键相关性与散点形态应与本报告一致（否则说明合同/实现又漂移了，需要回到 gate 排查）。
