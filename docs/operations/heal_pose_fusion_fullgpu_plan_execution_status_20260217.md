# HEAL Pose+Fusion 全 GPU 计划 — 执行现状验收（2026-02-17）

本文件回答的问题：**“全 GPU 在线端到端改造”这条计划线，现在到底执行到哪一步了？哪些 gate 真过了，哪些还没过？**

Plan docs（规范来源）：
- 架构合同（what is true / 语义固定）：`docs/operations/heal_pose_fusion_unified_arch.md`
- 执行手册（order/switch/cutover + T00-T10 gates）：`docs/operations/heal_pose_fusion_execution_playbook.md`
- 无初值 + 异构融合算法设计（目标态）：`docs/operations/heal_noinit_online_heter_fusion_design.md`

关键证据产物（本文件只认这些“硬证据”，不靠口述/感觉）：
- 运行时 gate 三件套（DAIR-val-max20, online_box）：  
  - `outputs/benchmark_manifest_20260209_real_runtime_gate.json`  
  - `outputs/benchmark_gate_report_20260209_real_runtime_gate.md`  
  - `outputs/benchmark_results_20260209_real_runtime_gate.jsonl`
- 更新（2026-02-20）：核心 box 方法（`v2xregpp/freealign/vips/cbm`）全 GPU 化后复跑 gate（用户同意 T03 AP 阈值放宽到 `1e-3`）  
  - manifest：`outputs/benchmark_manifest_20260220_fullgpu_gate.json`
  - gate report：`outputs/benchmark_gate_report_20260220_fullgpu_gate.md`
  - gate report rerun（同输入、重跑测试）：`outputs/benchmark_gate_report_20260220_fullgpu_gate_rerun.md`
  - gate report rerun2（fresh OPV2V smoke-based T06）：`outputs/benchmark_gate_report_20260220_fullgpu_gate_rerun2.md`
  - gate report rerun3（updated test suite + `AP<=1e-3` default）：`outputs/benchmark_gate_report_20260220_fullgpu_gate_rerun3.md`
  - T06 rows：`outputs/gate_fullgpu_t06_rows_20260220.jsonl`（4 行，`bad_fallback=[]`）
  - T06 rows rerun2：`outputs/gate_fullgpu_t06_rows_20260220_recheck.jsonl`（4 行，`bad_fallback=[]`）
- 更新（2026-02-20）：`online_box_feat_refine` 路径落地并完成 gate  
  - manifest：`outputs/benchmark_manifest_20260220_fullgpu_featrefine_gate.json`
  - gate report：`outputs/benchmark_gate_report_20260220_fullgpu_featrefine_gate.md`
  - T06 rows：`outputs/gate_fullgpu_featrefine_t06_rows_20260220_recheck.jsonl`（4 行，`bad_fallback=[]`，`refine_applied_total=4`）
- 严格 oracle parity（offline_map vs online_box, 100 samples）：`outputs/strict_oracle_online_parity_20260209.json`
- 更新（2026-02-18）：oracle parity 复跑（在旧 `1e-4` 口径 FAIL，但 oracle 路径已实现 `cpu_fallback_count==0`）  
  - strict parity JSON：`outputs/strict_oracle_online_parity_20260218_fastpath.json`
- OPV2V fullbench（online_box）历史 CPU fallback 证据（已被 2026-02-20 gate 修复覆盖，保留用于追溯）：  
  - `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/AP030507_v2xregpp_initfree_opv2v_autopilot_full_20260216_auto3_a1_camera_noise10_v2xregpp_best_n1.0.yaml`

---

## 结论

结论分两种（因为 playbook 本身就是“双轨策略”）：

1) **Track R（当前执行口径）**：**PASS**  
   - 口径：AP parity `<=1e-3` + pose parity `<=1e-3`。  
   - 证据：`outputs/benchmark_gate_report_20260220_fullgpu_gate_rerun2.md`（T00-T10 全 PASS）。
2) **Track G（加速/全 GPU 研发 lane）**：**PASS（核心方法 + feat_refine 均达成全 GPU）**  
   - 证据：`outputs/benchmark_gate_report_20260220_fullgpu_gate_rerun2.md`（online_box）与 `outputs/benchmark_gate_report_20260220_fullgpu_featrefine_gate.md`（online_box_feat_refine）均全绿。
3) **阈值收口**：`1e-4 -> 1e-3` 已执行  
   - 含义：旧 `1e-4` 结果仅作历史参考，不再作为当前阻断 gate。

---

## P0 阻塞项（当前执行口径）

无。

---

## Gate 表（按 execution_playbook 的核心验收口径）

T00-T10（proxy gate，证明 runtime 基础设施可跑、可测、可审计）— **PASS**
- 证据：`outputs/benchmark_gate_report_20260209_real_runtime_gate.md`：`overall_status: PASS`，且 T00..T10 全 PASS。
- 含义：工具链/契约/证据三件套是通的（但这不是“严格晋升条件”）。

严格 oracle parity（按当前 `1e-3` 口径）— **PASS**
- 证据：  
  - `outputs/strict_oracle_online_parity_20260209.json`：`max_ap_abs_delta=2.934e-4 < 1e-3`。  
  - `outputs/strict_oracle_online_parity_20260218_fastpath.json`：`max_ap_abs_delta=5.420e-4 < 1e-3`，且 `cpu_fallback_count==0`。
- 含义：在当前阈值配置下，不再阻断晋升。

GPU residency（“热路径无 CPU fallback”）— **PASS（核心方法）**
- 证据：`outputs/gate_fullgpu_t06_rows_20260220.jsonl`：4 行（`v2xregpp/freealign/vips/cbm`）`cpu_fallback_count` 均为 0。  
- 含义：在当前主线核心方法集合下，hot path 已可复现为无强制 CPU fallback。

无初值 + 特征 refine（目标态 L2）— **DONE（runtime 落地 + gate 通过）**
- 证据：`HEAL/opencood/extrinsics/pose_correction/online_feature_refiner.py` 已落地，`HEAL/opencood/utils/pose_provider_runtime.py` 已接入 `online_box_feat_refine` 并输出 `refine_sec/refine_attempted_count/refine_applied_count`；`outputs/benchmark_gate_report_20260220_fullgpu_featrefine_gate.md` T06 PASS。

---

## 证据链（事实 -> 推论 -> 风险）

1) `benchmark_gate_report_20260209_real_runtime_gate.md` PASS  
-> runtime 合同、测试、manifest/gate/results 证据闭环已具备  
-> 风险：该 gate 是 proxy（DAIR-val-max20），不能替代 strict promotion gate

2) `strict_oracle_online_parity_20260209.json` / `...20260218_fastpath.json` 的 AP delta 均小于 `1e-3`  
-> 当前阈值下，online_box 与 offline_map 可视为可接受语义近似  
-> 风险：若未来切回 `1e-4`，该项会重新变成阻断

3) `outputs/gate_fullgpu_t06_rows_20260220_recheck.jsonl` 与 `outputs/gate_fullgpu_featrefine_t06_rows_20260220_recheck.jsonl` 均为 `cpu_fallback_count==0`  
-> online_box 与 online_box_feat_refine 两条主线都已可复现无强制 CPU fallback  
-> 风险：新增方法/新分支仍可能引入 fallback，需要继续按 T06 审计

---

## 止损执行单（最小 next actions）

1) 把 promotion gate 变成“每次跑分自动生成”的硬产物：  
   - 每次 candidate（全 GPU）跑完，必须输出一份 strict parity JSON（像 `outputs/strict_oracle_online_parity_20260209.json` 这种）。
2) 将 `cpu_fallback_count==0` 继续保留为 OPV2V online/fullbench 的硬验收项（新增方法必须先过 T06）。  
3) 下一步重点从“实现完成”切到“收益验证”：在 DAIR/OPV2V fullbench 上做 refine ablation（AP/pose/吞吐三维）。

---

## 复跑验收条件（晋升 Track G -> Track R 的最低要求）

必须同时满足（当前执行口径）：
- strict oracle parity：`max_ap_abs_delta <= 1e-3` 且 `pose_delta <= 1e-3`
- GPU residency：在 OPV2V fullbench 代表性任务上 `cpu_fallback_count == 0`
- fairness：非 oracle 路径无 GT 泄漏（T04 类规则）
- provenance：manifest + gate_report + results 三件套齐全且可追溯到同一协议（同 split/同 ckpt/同后处理/同 eval 范围）

用户当前执行口径（2026-02-20）：
- T03/T02 AP 阈值统一为 `1e-3`；
- 对应证据：`outputs/benchmark_gate_report_20260220_fullgpu_gate_rerun2.md` 与 `outputs/benchmark_gate_report_20260220_fullgpu_featrefine_gate.md`（均 T00-T10 全 PASS）。
