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
- 严格 oracle parity（offline_map vs online_box, 100 samples）：`outputs/strict_oracle_online_parity_20260209.json`
- 更新（2026-02-18）：oracle parity 复跑（仍 FAIL，但 oracle 路径已实现 `cpu_fallback_count==0`）  
  - strict parity JSON：`outputs/strict_oracle_online_parity_20260218_fastpath.json`
- OPV2V fullbench（online_box）实际 CPU fallback 证据（例 1 条 YAML）：  
  - `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/AP030507_v2xregpp_initfree_opv2v_autopilot_full_20260216_auto3_a1_camera_noise10_v2xregpp_best_n1.0.yaml`

---

## 结论

结论分两种（因为 playbook 本身就是“双轨策略”）：

1) **Track R（可发布 benchmark reference lane）**：**BLOCK**  
   - 原因：严格 oracle parity 仍未满足 hard gate（AP delta 超阈值），因此 **不能把 online_box / 全 GPU 路径晋升为 reference**。
2) **Track G（加速/全 GPU 研发 lane）**：**ALLOW（继续推进）**  
   - 原因：runtime 合同测试 + proxy gate（T00-T10 的 real_runtime_gate）已 PASS，说明基础设施可用；但仍需补齐 promotion gate。

---

## P0 阻塞项（阻止“宣称全 GPU 已完成 / 晋升为 Track R”）

1) **严格 oracle offline_map vs online_box parity 未过 hard gate**  
   - 证据（旧）：`outputs/strict_oracle_online_parity_20260209.json` 里 `ap_pass=false`，且 `max_ap_abs_delta=2.934e-4 > 1e-4`。
   - 证据（新，2026-02-18）：`outputs/strict_oracle_online_parity_20260218_fastpath.json` 里 `ap_pass=false`，`max_ap_abs_delta=5.420e-4 > 1e-4`，但 `online_pose_timing.cpu_fallback_count=0.0`（oracle online 路径无 CPU fallback）。
2) **主线 OPV2V online/fullbench 仍出现 CPU fallback（不是 strict all-GPU hot path）**  
   - 证据：  
     - `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/AP030507_v2xregpp_initfree_opv2v_autopilot_full_20260216_auto3_a1_camera_noise10_v2xregpp_best_n1.0.yaml`  
     - `timing_stats[0].pose_timing.cpu_fallback_count == 1.0`
3) **`online_box_feat_refine` 仍未形成“可验收”的 refine 行为**（当前实现上等价走 `online_box`）  
   - 证据：`HEAL/opencood/utils/pose_provider_runtime.py` 对 `solver_backend in {"online_box","online_box_feat_refine"}` 走同一路径（没有独立 refine gate/计时字段）；仓库内无独立 refine 模块文件。

---

## Gate 表（按 execution_playbook 的核心验收口径）

T00-T10（proxy gate，证明 runtime 基础设施可跑、可测、可审计）— **PASS**
- 证据：`outputs/benchmark_gate_report_20260209_real_runtime_gate.md`：`overall_status: PASS`，且 T00..T10 全 PASS。
- 含义：工具链/契约/证据三件套是通的（但这不是“严格晋升条件”）。

严格 oracle parity（promotion hard gate）— **FAIL**
- 证据：  
  - `outputs/strict_oracle_online_parity_20260209.json`：`ap_pass=false`。  
  - `outputs/strict_oracle_online_parity_20260218_fastpath.json`：`ap_pass=false`（oracle online 路径 `cpu_fallback_count==0` 但 AP gate 仍未过）。
- 含义：**不能晋升 Track G -> Track R**（否则 benchmark 语义漂移风险不可控）。

GPU residency（“热路径无 CPU fallback”）— **PARTIAL**
- PASS 证据（小样本）：`outputs/gate_real_t06_rows.jsonl`：`cpu_fallback_count: 0.0`（job_id=`real_online_gpu20`）。  
- FAIL 证据（主线 fullbench）：见上方 OPV2V YAML，`cpu_fallback_count: 1.0`。  
- 含义：GPU 化路径存在且能跑到 0 fallback，但 **尚未变成主线默认/可复现**。

无初值 + 特征 refine（目标态 L2）— **NOT DONE（按计划定义）**
- 证据：`docs/operations/heal_noinit_online_heter_fusion_design.md` 明确将 `online_feature_refiner.py` 标注为 open milestone；代码侧未见独立 refine 实现产物。

---

## 证据链（事实 -> 推论 -> 风险）

1) `benchmark_gate_report_20260209_real_runtime_gate.md` PASS  
-> runtime 合同、测试、manifest/gate/results 证据闭环已具备  
-> 风险：该 gate 是 proxy（DAIR-val-max20），不能替代 strict promotion gate

2) `strict_oracle_online_parity_20260209.json` AP hard gate FAIL  
-> online_box 的语义仍与 offline_map 存在可测 AP 漂移  
-> 风险：若直接在论文/主 benchmark 中替换 reference，会把“加速改造造成的漂移”误当成算法增益/退化

3) OPV2V fullbench YAML 出现 `cpu_fallback_count==1`  
-> 主线 benchmark 仍非 strict all-GPU hot path  
-> 风险：你要的“全 GPU 在线端到端 benchmark”目前只能算 **partial**（需要把 fallback=0 变成可验收条款）

---

## 止损执行单（最小 next actions）

1) 把 promotion gate 变成“每次跑分自动生成”的硬产物：  
   - 每次 candidate（全 GPU）跑完，必须输出一份 strict parity JSON（像 `outputs/strict_oracle_online_parity_20260209.json` 这种）。
2) 将 `cpu_fallback_count==0` 升级为 OPV2V online/fullbench 的验收项（否则不要叫“全 GPU”）。  
3) 若要推进 `online_box_feat_refine`：先补齐“refine 生效证据”（独立 timing 字段 + 可控开关 + ablation 通过），再谈收益。

---

## 复跑验收条件（晋升 Track G -> Track R 的最低要求）

必须同时满足：
- strict oracle parity：`max_ap_abs_delta <= 1e-4` 且 `pose_delta <= 1e-3`
- GPU residency：在 OPV2V fullbench 代表性任务上 `cpu_fallback_count == 0`
- fairness：非 oracle 路径无 GT 泄漏（T04 类规则）
- provenance：manifest + gate_report + results 三件套齐全且可追溯到同一协议（同 split/同 ckpt/同后处理/同 eval 范围）
