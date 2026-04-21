# Benchmark 全跑完 + 全 GPU 改造：规划文档整理（Single Entry, 2026-02-17）

你关心的其实是两条“交付线”，它们不能混口径：

1) **Benchmark 全部跑完（可用/可复现/公平）**：产出可用于写论文/对比的方法曲线与表格。  
2) **全 GPU 在线端到端改造**：把 runtime 变成 GPU-resident 的在线配准+融合系统，并用严格 parity gate 保证语义不漂移。

下面把 repo 里已经存在的 MD 规划/执行/证据文档按“用途 + 当前状态”整理成一个入口。

---

## A) OPV2V online/fullbench（“benchmark 全跑完”主线）

### A1. 规划（Plan / DoD）
- **Masterplan（主计划 / DoD / 止损 gate）**  
  - `docs/operations/opv2v_fullbench_masterplan.md`

### A2. 执行入口（How to run）
- **复现文档（环境 + stage1 cache + fullbench + autopilot/supervisor）**  
  - `docs/operations/opv2v_benchmark_repro.md`

### A3. 执行过程复盘（为什么之前会“跑完但垃圾/平线/重合”）
- **规范缺口复盘（规划里漏掉的硬门槛）**  
  - `docs/operations/opv2v_spec_gap_review_20260215.md`
- **审计（把平线/重合的第一性原因讲清楚）**  
  - `docs/operations/opv2v_fullbench_audit_20260214.md`
- **离线 vs 在线差距定义与止损路线**（避免混语义）  
  - `docs/operations/offline_vs_online_benchmark_gap_20260215.md`

### A4. 证据闭环（Evidence / Source-of-truth）
- **本次可信主结果（已跑完）**  
  - run dir: `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/`
  - completion（唯一可信口径）: `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/run_state.jsonl`
  - results: `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/results_ap50_from_yaml.json`
  - plots: `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/plots_yaml/`
  - semantics snapshot: `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/config_snapshot.json`
- **证据报告（stage1 校验 / pose_override 检查 / sanity span）**  
  - `docs/operations/opv2v_fullbench_evidence_autopilot_20260216_auto3.md`
- **对 masterplan 的执行验收表（gate-by-gate）**  
  - `docs/operations/opv2v_fullbench_masterplan_execution_status_20260217.md`

### A5. 结果解释（给论文写作/研究机会用）
- **old vs new + offline reference 的对照分析**  
  - `docs/operations/opv2v_fullbench_comparative_analysis_20260217.md`

### A6. 当前状态（一句话）
- **OPV2V online/fullbench**：已按 masterplan DoD 跑完并产出可用曲线（主结果 run：`opv2v_autopilot_full_20260216_auto3_a1`）。  
  - 注意：这条线解决的是“benchmark 全跑完/公平可复现”；不等价于“全 GPU 在线端到端已完成”（见 B）。

---

## B) HEAL Pose+Fusion 全 GPU 在线改造（“全 GPU”主线）

这条线的核心原则在文档里已经写死：**加速 Track G 不能直接污染 benchmark Track R**；必须通过 parity gate 才能晋升。

### B1. 文档入口（先读哪个）
- **Pose+Fusion docs 索引（单入口，控文档数量）**  
  - `docs/operations/heal_pose_fusion_docs_index.md`

### B2. 规划（Architecture / Playbook / Algorithm）
- **架构合同（现在代码真实实现到了哪 + 固定语义是什么）**  
  - `docs/operations/heal_pose_fusion_unified_arch.md`
- **执行手册（按依赖顺序怎么改、怎么切换、怎么回滚、T00-T10 gates）**  
  - `docs/operations/heal_pose_fusion_execution_playbook.md`
- **无初值在线配准 + 异构融合算法设计（系统目标态 + L0/L1/L2/L3 分层）**  
  - `docs/operations/heal_noinit_online_heter_fusion_design.md`

### B3. 关键证据（目前为什么还不能宣称“全 GPU 已完成”）
- **严格 oracle parity（offline_map vs online_box）未过 hard gate**  
  - evidence: `outputs/strict_oracle_online_parity_20260209.json`  
  - 结论：`ap_pass=false`，AP 最大差异约 `2.93e-4 > 1e-4`（pose parity 通过但 AP gate 未过）。
- **在线 solver 热路径仍出现 CPU fallback**（所以不是 strict all-GPU）  
  - 例如（LiDAR, v2xregpp initfree）：  
    - `HEAL/opencood/logs/freealign_repro_opv2v_baseline/AP030507_v2xregpp_initfree_opv2v_autopilot_full_20260216_auto3_a1_lidar_noise10_v2xregpp_best_n1.0.yaml`  
    - `timing_stats[0].pose_timing.cpu_fallback_count == 1.0`

### B4. 当前状态（一句话）
- **全 GPU 在线端到端**：处于“实现了一部分在线 runtime/工具链，但尚未通过 parity 与 GPU-residency 验收”的阶段；因此它应该继续作为 Track G（加速线），不能直接替换最终 benchmark 口径。

---

## C) Offline 参考基线（用于 sanity / 论文“对照口径”）

这部分是你说“更合理”的两组离线 png 对照来源（**不要和 OPV2V online 混口径**）。

- 产物：  
  - `outputs/pose_sweep_1to10_camera_percav_full_plots/`
  - `outputs/pose_dropout_1to10_full_plots/`
- 解读复盘：`docs/operations/pose_benchmark_plots_review_20260214.md`
- 总清单（canonical vs non-canonical）：`docs/operations/benchmark_inventory.md`

---

## D) 你现在如果只想“少看文档，快速定位”

- 我只想跑出 OPV2V 最终曲线（可复现 + 有证据链）  
  -> `docs/operations/opv2v_benchmark_repro.md`（然后对照 `docs/operations/opv2v_fullbench_masterplan.md` 的 DoD）

- 我只想确认这次 OPV2V 是否真的跑完、结果能不能用  
  -> `docs/operations/opv2v_fullbench_masterplan_execution_status_20260217.md`

- 我只想推进“全 GPU 在线端到端”，并且保证不把 benchmark 搞脏  
  -> `docs/operations/heal_pose_fusion_execution_playbook.md`（Track R/G + T00-T10 gates）

