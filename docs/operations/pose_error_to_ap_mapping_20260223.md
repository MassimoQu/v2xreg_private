# Pose Error -> AP50 经验映射 (2026-02-23)

目的：在某些配准方法还没“接到下游协同感知”完整跑 AP 之前，先用已跑出来的 **配准评估**（`rel_error_stats`）来做 **粗预估 / 排序**，并检查配准质量与 AP50 的统计对应关系（尽可能公正、可复现、可溯源）。

本文件只回答一个问题：**“配准评估指标”与“协同感知 AP50”之间，在你现有实验里呈现出什么样的经验关系？**  
（它不替代真实跑 AP，也不保证跨 benchmark 条件可迁移。）

---

## 数据来源（可溯源）

本次分析使用的“统一长表”与“统计摘要”：

- 统一长表：`outputs/benchmark_fullmatrix_mapping_20260223/combined_noise_curve_long.csv`
- 统计摘要：`outputs/benchmark_fullmatrix_mapping_20260223/pose_error_to_ap_summary.json`

它们由以下脚本/输入生成：

1) 生成长表（DAIR + OPV2V 合并）：
```bash
python3 tools/build_fullmatrix_benchmark_report.py \
  --out-dir outputs/benchmark_fullmatrix_mapping_20260223 \
  --skip-plots
```

2) 在长表上做相关性与线性拟合：
```bash
python3 tools/analyze_pose_error_to_ap.py \
  --csv outputs/benchmark_fullmatrix_mapping_20260223/combined_noise_curve_long.csv
```

其中，OPV2V 的输入来自 run-dir 中的 `results_ap50_from_yaml.json` + 对应 `HEAL/opencood/logs/*/AP030507_*.yaml`；DAIR 来自 `outputs/pose_sweep_1to10_full_gpuvoxel20260218_results.jsonl` 里每条的 `yaml_path`。

---

## 指标定义（来自你现有 YAML）

- `ap50`：协同感知检测 AP@0.5
- `success_at_2m`：相对位姿平移误差 `<2m` 的比例（`rel_success_at_m["2"]`）
- `mean_rel_trans_m`：相对平移误差均值（`rel_trans_m["mean"]`）
- `mean_rel_yaw_deg`：相对 yaw 误差均值（`rel_yaw_deg["mean"]`）

经验上（在你现有数据里）：
- `success_at_2m` 比 `mean_rel_trans_m` 更“稳健”（对 heavy-tail/outlier 不那么敏感），也更能解释 AP50。

---

## 统计方法（尽量公正）

对每个 `(dataset, suite, modality)` 分组：

1) 计算 Pearson 相关系数：
- corr(AP50, mean_rel_trans_m)
- corr(AP50, success_at_2m)
- corr(AP50, mean_rel_yaw_deg)

2) 拟合一个非常朴素的线性模型（只用于粗预估）：

> AP50 ≈ b0 + b1 * success_at_2m + b2 * mean_rel_yaw_deg

并报告 RMSE（拟合残差的均方根）。

---

## 结果（从 `pose_error_to_ap_summary.json` 直接抄数）

### OPV2V / LiDAR

- **noise10**
  - corr(AP50, success_at_2m)=**0.9367**
  - coef = **[0.3650, 0.5719, 0.00146]**
  - RMSE = **0.0681**

  粗预估公式：
  - AP50 ≈ 0.3650 + 0.5719 * success_at_2m + 0.00146 * mean_rel_yaw_deg

- **drop20**
  - corr(AP50, success_at_2m)=**0.9486**
  - coef = **[0.3580, 0.5923, 0.00168]**
  - RMSE = **0.0590**

  粗预估公式：
  - AP50 ≈ 0.3580 + 0.5923 * success_at_2m + 0.00168 * mean_rel_yaw_deg

### OPV2V / Camera

- **noise10**
  - corr(AP50, success_at_2m)=**0.9062**
  - coef = **[0.1085, 0.1904, -0.00090]**
  - RMSE = **0.0227**

- **drop20**
  - corr(AP50, success_at_2m)=**0.8980**
  - coef = **[0.1117, 0.1880, -0.00097]**
  - RMSE = **0.0229**

### DAIR-V2X / LiDAR

- **noise10**
  - corr(AP50, success_at_2m)=**0.7684**
  - coef = **[0.2565, 0.1231, -0.000164]**
  - RMSE = **0.0362**

### DAIR-V2X / Camera

- **noise10**
  - corr(AP50, success_at_2m)=**0.8384**
  - coef = **[0.0250, 0.0227, -0.000111]**
  - RMSE = **0.00423**

---

## 怎么用这些结果去“预估 AP”

前提：**必须是同一套 benchmark 条件**（特别是 comm-range gating、噪声注入方式、下游检测模型/输入等都一致）。

做法：
1) 从方法对应的 YAML 里取 `success_at_2m` 与 `mean_rel_yaw_deg`
2) 找到同 `(dataset, suite, modality)` 的系数 `(b0,b1,b2)`
3) 代入得到 AP50 的粗预估值

建议用途：
- 先做“方法排序/筛选”（值得不值得完整跑 AP）
- 或者在大规模跑之前做 sanity check（例如：配准指标很好但 AP 反而极差，优先怀疑 wiring / benchmark confound）

不建议用途：
- 当成最终结论写进 paper / 主结果表

---

## 重要 Caveats（必须读）

1) **comm-range pruning 语义会显著改变 AP（且会破坏映射可迁移性）**  
   你之前一些 OPV2V fullbench 里，pose-correction 在线 backend 会把 `comm_range_use_clean_pose` 置 True（用 clean pose 做 range pruning），而 baseline 默认用 noisy pose 做 pruning。  
   这会把 AP 的变化混进“更多车被纳入融合”的收益，导致“同样的配准指标 -> 不同 AP”的映射不可直接迁移到最新合约（推荐固定 `--comm-range-gating noisy`）。

2) 本模型只用 mean yaw 与 `success_at_2m`，**对 heavy-tail/outlier 的结构不敏感**  
   像 freealign 这类可能出现“median 很好但 mean/p90 很差”的方法，AP 的偏差可能更大。后续如果要更稳健，建议把 `median/p90` 也纳入长表再拟合。

3) **混版本/混环境的历史 run 会污染映射**  
   本文是“利用已有可用结果”先做趋势判断；一旦你开始按最新统一 benchmark 合约重跑，建议重新生成长表并复算系数。

