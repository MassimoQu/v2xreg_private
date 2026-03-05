# Core Benchmark 进度与 P0 收口清单（DAIR / OPV2V / V2V4Real）

更新：2026-03-04

本文件只回答两件事：
1) **现在做到什么**（哪些结果可复盘/可引用）  
2) **还差什么**（为了“统一/公平/有证据链”的 core benchmark 最小还缺口）

> Canonical 合同与语义冻结仍以：`docs/operations/unified_core_benchmark_master_spec_results_v1_20260302.md` 为准；本文是它的“执行进度 + P0 收口”视图。

---

## 1) 已完成（可以当作“已钉死”的事实）

### 1.1 语义冻结已经落到可审计的产物里（不是口头约定）
- **single 的唯一合法定义**已经固定为 `baseline + --force-ego-input-only`（single_ego_only），而不是 legacy `comm_range=0`。  
  - 证据：DAIR LiDAR `outputs/dair_core_core_clean_v4_laneD_20260303_run1/lidar/manifest.json`
- **comm-range-gating 必须显式 pin**（禁止 auto）已经写进合同与证据链，并在新 runs 的 manifest 里落地。  
  - 证据：同上 manifest 内 `comm_range_gating: "clean"`
- **compare-current 阈值 pins**已经被写入 manifest（避免 best-state 隐式补默认阈值导致“变题/不可复现”）。  
  - 证据：同上 manifest 内 `compare_current_pins`

### 1.2 “comm-range-gating clean/noisy 会让 CBM/VIPS 大幅波动”的归因已被严格对照实验纠正
结论：在 strict-control（同样本子集、唯一差别=gating）下，**clean vs noisy gating 对 AP 影响极小**；历史观察到的“大差异”主要来自 confound（auto gating 未 pin、以及 V2V4Real head 子集偏置等）。
- 证据链文档：`docs/operations/comm_range_gating_cbm_sensitivity_evidence_20260304.md`
- strict-control runs（可复跑/可查产物）：
  - OPV2V：`outputs/full_bench_opv2v_cbm_gating_clean_smoke200_20260304_a1/` 与 `..._noisy_.../`
  - V2V4Real（修复 head 偏置后）：`outputs/v2v4real_core_v2v4real_gating_clean_smoke200_start294_20260304_a2/` 与 `..._noisy_.../`

### 1.3 三数据集 core 结果“主体”已跑通并产出主图
下面这些 runs 已经产出 `summary.md + plots_yaml/*.png`（且 single/oracle 等语义已对齐到统一规范）：
- DAIR-V2X：`outputs/dair_core_core_clean_v4_laneD_20260303_run1/`（camera + lidar）
- V2V4Real：`outputs/v2v4real_core_core_clean_v4_laneD_20260303_run1/`（LiDAR）
- OPV2V：`outputs/full_bench_opv2v_autopilot_full_core_clean_v4_laneD_20260303_run1_a1/`
  - 已有：`results_ap50_from_yaml.json` 与 `plots_yaml/*.png`
  - 但缺：统一口径 `summary.md`（见 P0-3）

---

## 2) 还差什么（P0：不补齐就会“解释不闭环/容易被误读”）

### P0-1 召回率低/曲线怪/方法“看似失效”的根因缺硬证据链
当前只有侧证（applied 比例、rel_error_stats、AP 曲线），但缺少“失败原因分解”的直接统计，导致：
- 只能说“可能是 bad-apply / no-match / SVD fail”，但无法量化主因占比；
- 也无法解释“为什么某数据集/模态掉得特别多（例如 DAIR camera / OPV2V camera）”。

**必须补齐的可审计产物（最小闭环）：**
- 对每个 method（至少 VIPS/CBM，最好包括 v2xregpp/freealign）在每个 noise 点输出聚合统计：
  - `pose_apply_attempted`
  - `pose_applied`
  - `reject_by_compare_gate`
  - `empty_boxes` / `insufficient_correspondences`
  - `svd_failed`
  - 其它实现可判别的失败原因（按代码实际为准）

### P0-2 V2V4Real 的 camera lane 尚未补齐（公平性缺口）
现状：V2V4Real core 目前只有 LiDAR checkpoint 与结果。  
如果你的“统一公平标准”要求 camera+lidar 都齐全，那么 V2V4Real camera 需要：
- 找到已训好可用 checkpoint（优先 v2xvit 对齐 DAIR/OPV2V），或
- 补训一个最小公平的 camera 模型（训练配置/数据路径/验证方式全部明确）。

### P0-3 OPV2V fullbench 这次 run_dir 缺少统一口径的 summary 索引
现状：OPV2V fullbench 产物齐全（state/results/plots），但缺 `summary.md` 会导致复盘/引用很痛苦，也容易被旧切片误导。
- 需要：从 `results_ap50_from_yaml.json` + `config_snapshot.json` 生成统一结构 `summary.md`（不重跑）

---

## 3) 接下来怎么做（最小行动序列 + DoD）

### Step A：插桩失败原因统计（收 P0-1）
交付：
- 代码插桩（最小侵入）+ 可开关的输出（写进 YAML 或 sidecar JSON）；
- summarize 脚本把 reason stats 汇总成表格（每 noise 点一行）；
- 在 DAIR/OPV2V/V2V4Real 各跑一个 smoke（建议 noise=0 与 noise=10，各 200 samples）验证统计稳定输出。

验收（DoD）：
- 对 VIPS/CBM 至少能解释：是 “apply 少（保守/no-op）” 还是 “apply 多但错（bad-apply）” 还是 “匹配/求解失败为主（no-match/SVD fail）”。

### Step B：补齐 OPV2V summary（收 P0-3）
交付：`outputs/full_bench_opv2v_autopilot_full_core_clean_v4_laneD_20260303_run1_a1/summary.md`

### Step C：补齐 V2V4Real camera lane（收 P0-2）
交付（两选一）：
1) 找到可用 checkpoint 并跑出 camera core；或  
2) 补训并跑出 camera core（训练/验证/评测全链路可复盘）。

---

## 4) 当前全局状态（快速复盘指针）

### 可直接看的“主结果入口”
- DAIR：`outputs/dair_core_core_clean_v4_laneD_20260303_run1/*/summary.md`
- V2V4Real（LiDAR）：`outputs/v2v4real_core_core_clean_v4_laneD_20260303_run1/summary.md`
- OPV2V fullbench：`outputs/full_bench_opv2v_autopilot_full_core_clean_v4_laneD_20260303_run1_a1/results_ap50_from_yaml.json` + `plots_yaml/`

### 关键证据链（避免被误读）
- gating / confound：`docs/operations/comm_range_gating_cbm_sensitivity_evidence_20260304.md`

