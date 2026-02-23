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

