# Dataset Differences: Comm-Range / Gating Sensitivity（DAIR / OPV2V / V2V4Real）

更新：2026-02-28

补充（机制 + 实证对照 / CBM 敏感性）：`docs/operations/comm_range_gating_cbm_sensitivity_evidence_20260304.md`

## 0) 这份文档解决什么问题

同一套 unified core benchmark 合同（noise=0..10、online_box、paired sweep、non-ego 注噪）下：

- **为什么 OPV2V/DAIR 的曲线形态在 `comm-range-gating=noisy` 下可能更“抖”**，而 V2V4Real（尤其 comm=200）往往更平？  
  > 注：若你用的是当前 `oracle_gt`（online_box 下禁噪），oracle_gt 本身应当平线；这里讨论的是 baseline/方法线（以及“保留注噪的 oracle”）为何会因 agent-set 抖动而形态不同。
- **为什么“用 noisy 外参做通信范围裁剪（comm-range gating）”在不同数据集上影响差别很大？**

这份文档只聚焦于一个关键差异：**样本中 ego↔non-ego 的距离分布相对 comm_range 的位置**，以及它导致的 **gating 稳定性**差异。

> 说明：跨数据集 AP 绝对值不建议硬对齐；这里讨论的是“曲线形态/稳定性”的原因链条。

---

## 1) 统一术语（与你的 benchmark 合同一致）

### 1.1 comm-range gating（通信范围裁剪）

- `comm_range_gating=clean`：用 clean pose 计算距离裁剪邻居 → **邻居集合固定**
- `comm_range_gating=noisy`：用 noisy pose 计算距离裁剪邻居 → **邻居集合可能随噪声变化**

当你在 `comm_range_gating=noisy` 下做 noise sweep 时，baseline/方法线的邻居集合可能随噪声变化，导致曲线形态更“抖”。  
对于 oracle：需要区分实现——若用的是当前 `oracle_gt`（online_box 下禁噪），oracle_gt 应当平线；若用“保留注噪的 oracle”（例如 `v2vloc_oracle_*`），则可能因为邻居集合变动而出现轻微漂移。

### 1.2 我们用什么“证据工具”量化 gating 的敏感度

工具：`tools/analyze_comm_range_gating_effect.py`

它用 stage1 cache 里的 `lidar_pose_clean_np` 做一个近似：

- 对每个样本，取 ego（index=0）与所有 non-ego 的 clean 平面距离 `d`
- 统计距离分位数、`d<=R` 的比例、以及 `|d-R|<=5m` 的“靠边界”比例
- 用 Monte-Carlo 估计：当只给 non-ego 加平移噪声 `N(0, σ^2)` 时，
  **原本 in-range 的 link（d<=R）变成 out-of-range（>R）的概率**

> 这是解释工具，不是 end-to-end AP 的替代；但它非常适合解释“为什么某数据集在 noisy gating 下 oracle 更容易抖”。

---

## 2) 数据集对比（同一工具、同一噪声轴）

下面所有数值均来自同一命令：

```bash
./.micromamba/envs/py39/bin/python -u tools/analyze_comm_range_gating_effect.py \
  --stage1 <stage1_boxes.json> --comm-range <R> \
  --sigmas 0,1,2,3,4,5,6,7,8,9,10 --mc-draws 500 --seed 42
```

### 2.0 一句话总览（便于你快速判断“gating 会不会抖”）

| dataset | comm_range R (m) | records_used | mean_pairs_per_record | inrange_rate | near_boundary_rate(±5m) | dropout@σ=10m |
|---|---:|---:|---:|---:|---:|---:|
| OPV2V | 70 | 2170 | 1.758 | 0.903 | 0.024 | 2.07% |
| DAIR-V2X | 100 | 1789 | 1.000 | 0.915 | 0.047 | 3.34% |
| V2V4Real | 200 | 3986 | 1.000 | 1.000 | 0.000 | 0.00% |
| V2V4Real | 70 | 3986 | 1.000 | 0.926 | 0.000 | 1.45% |

> `mean_pairs_per_record` 近似为“每个样本 ego 的 non-ego 数”；`dropout@σ=10m` 是 in-range link 变 out-of-range 的 MC 概率估计（noise-target=non-ego）。

### 2.1 OPV2V（comm_range=70）

- stage1：`data/OPV2V/detected/opv2v_camera_v2xvit_stage1_percav/test/stage1_boxes.json`
- records_used=2170
- agent 数分布（len(lidar_pose_clean_np)）：{2:994, 3:874, 4:135, 5:167}
- mean_pairs_per_record≈1.758（平均 non-ego 数≈1.758）
- inrange_rate≈0.903
- near_boundary_rate_pm5m≈0.024（有约 2.4% 的 ego↔non-ego 距离在 [R-5, R+5] 附近）
- in-range link dropout（σ=10m）≈2.07%

直觉：OPV2V 的 `R=70` 在距离分布的“尾部附近”，且多车导致 pair 数更多 → noisy gating 下更容易出现“少量 link 翻转”。

### 2.2 DAIR（comm_range=100）

注意：很多旧 detected cache（例如 `veh_rsu_dual` / `paper3737_pp_dual`）的 `lidar_pose_clean_np` 被写成全 0（已经在 ego frame 里），**无法用于 gating 分析**。因此这里使用从 DAIR lidar V2XViT checkpoint 导出的 **per-CAV stage1 cache**（包含真实 pose）。

- stage1：`data/DAIR-V2X/detected/lidar_v2xvit_stage1_percav/test/stage1_boxes.json`
- records_used=1789
- agent 数：恒为 2（vehicle + infrastructure）
- mean_pairs_per_record=1.0
- inrange_rate≈0.915
- near_boundary_rate_pm5m≈0.047（约 4.7% 距离靠近 R=100 的边界）
- in-range link dropout（σ=10m）≈3.34%

直觉：DAIR 的 vehicle↔infra 距离有相当一部分靠近 `R=100` 的边界，因此 noisy gating 下更容易因为噪声把 link 推到 out-of-range → oracle 也更可能轻微抖动。

### 2.3 V2V4Real（comm_range=200 vs 70）

stage1：`HEAL/opencood/logs/v2v4real_stage1_pointpillar_from_pastat_bestval17_percav/test/stage1_boxes.json`

该 cache 的 agent 数恒为 2（mean_pairs_per_record=1.0）。

> 备注：本仓库的 V2V4Real 训练 hypes（PASTAT）默认 `comm_range=70`（例如 `HEAL/opencood/hypes_yaml/v2v4real/LiDAROnly/lidar_pastat_noise1.yaml:17`）。这里把 `R=200` 也列出来，是为了回答“若按 paper 常见设定，noisy gating 会不会抖”这个解释性问题，不代表本仓库的默认 benchmark setting。

#### (A) comm_range=200（paper 常用）

- inrange_rate=1.0（所有样本 link 都在 200m 内）
- near_boundary_rate_pm5m=0.0
- dropout（σ=10m）≈0.00%

直觉：`R=200` 对这个数据集太宽，距离分布远离边界 → noisy gating 几乎不改变邻居集合，因此 oracle 通常非常平。

#### (B) comm_range=70（为了与 OPV2V 更接近的对照）

- inrange_rate≈0.926
- near_boundary_rate_pm5m=0.0（在 70±5m 区间几乎没有样本）
- dropout（σ=10m）≈1.45%

直觉：即便用 70m，V2V4Real 的 in-range 距离仍普遍明显小于 70（离边界有“空档”），因此 noisy gating 仍比较稳定。

---

## 3) 结论：为什么“同做 noisy gating”但表现差这么多

证据链（从“几何”到“曲线形态”）：

1) noisy gating 是否会影响 oracle，取决于 **ego↔non-ego 距离是否靠近 comm_range 边界**  
   - near_boundary_rate 越高 → 越容易发生 link 翻转
2) link 翻转概率（dropout）可被 Monte-Carlo 估计（上面的 σ=10m 数值）  
   - OPV2V@70：≈2.07%  
   - DAIR@100：≈3.33%  
   - V2V4Real@200：≈0%
3) 因此：你看到的“noisy gating 下曲线更抖、而 V2V4Real@200 很平”是**预期现象**，不是必然 bug。  
   若你看到 `oracle_gt` 本身明显不平，优先按“混语义/未走禁噪分支/非 oracle_gt”排查。

---

## 4) 对 unified benchmark 的直接建议（可操作）

1) **如果你的目标是系统级真实（包含通信裁剪也受噪声影响）**：统一用 `--comm-range-gating noisy`  
   - 接受 oracle 可能轻微抖动；用本工具先量化敏感度作为解释证据。

2) **如果你的目标是诊断/隔离“对齐误差对融合的影响”**：统一用 `--comm-range-gating clean`  
   - 这样邻居集合固定，oracle 更接近平线；曲线更“像纯对齐问题”。

3) **跨数据集不要强行统一 comm_range**  
   - `R` 不只是一个超参，它与数据集的距离分布强耦合；强行统一会引入新的 confound（例如 V2V4Real@200 和 @70 的 gating 稳定性本来就差很多）。
