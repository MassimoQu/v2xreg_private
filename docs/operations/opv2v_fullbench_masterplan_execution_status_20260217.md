# OPV2V Fullbench Masterplan — Execution Status (2026-02-17)

Plan doc:
- `docs/operations/opv2v_fullbench_masterplan.md`

## Update（2026-02-24）：本文件仅保留为历史执行记录（不再作为 canonical 依据）

随着 2026-02-23~02-24 的统一条件审计与修复（comm-range gating 语义冻结、online payload/no-op 排查、HKUST/lidar_reg wiring 修复等），
我们已经确认：

- `opv2v_autopilot_full_20260216_auto3_a1` 使用 `comm_range_gating=auto`，在 online runtime 下存在 baseline vs method gating 语义漂移风险；
- 同 run_id 出现过 mixed-env + mid-run 修复混写；
- init/no-init/HKUST 追加矩阵并未完成（run_state/task_summary 可证）；
- 大量旧 YAML schema 不含 `pose_provider_applied_count`，无法对 no-op 做严格 gate。

因此：本文件不再作为“最终可引用 benchmark”的证据；canonical 版本请以 unified fullbench 合同为准：
- `docs/operations/opv2v_unified_fullbench_plan_20260223.md`
- `docs/operations/benchmark_pending_runs_and_plan_20260224.md`

Trusted run (main result):
- run dir: `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/`
- run id: `opv2v_autopilot_full_20260216_auto3_a1`
- source-of-truth completion: `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/run_state.jsonl`
- results: `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/results_ap50_from_yaml.json`
- plots: `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/plots_yaml/`
- config snapshot (semantics freeze): `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/config_snapshot.json`

Autopilot evidence:
- autopilot log (smoke + full): `outputs/opv2v_autopilot_20260216_auto3/autopilot.log`
- supervisor state: `outputs/opv2v_autopilot_supervisor_20260216_auto3/state.json`
- evidence report: `docs/operations/opv2v_fullbench_evidence_autopilot_20260216_auto3.md`
- comparative analysis: `docs/operations/opv2v_fullbench_comparative_analysis_20260217.md`

Offline reference (not apples-to-apples with OPV2V online):
- review: `docs/operations/pose_benchmark_plots_review_20260214.md`
- offline-vs-online gap: `docs/operations/offline_vs_online_benchmark_gap_20260215.md`

---

## 结论（按 masterplan 的 DoD 口径）

结论: **ALLOW**（用于 OPV2V online pose-noise robustness suite 的主结果）

解释（只说最关键的）：
- masterplan §4.5 的 DoD（完成 + 作图 + 语义固化 + 非退化 sanity）在 `20260216_auto3` 上整体满足。
- 你的“全 GPU 化在线端到端”目标已通过后续 gate 产物补齐（见 `outputs/benchmark_gate_report_20260220_fullgpu_gate_rerun2.md` 与 `outputs/benchmark_gate_report_20260220_fullgpu_featrefine_gate.md`，T06 均 `bad_fallback=[]`）。

---

## P0 阻塞项（影响“能不能用这轮结果做主结论”）

无（在 OPV2V online/fullbench 的语义下）。

> 注：当前 `20260216_auto3` 主 run 是结果基线；全 GPU 验收由后续 gate run 补齐并通过（T06 无 fallback）。

---

## Gate 表（PASS/FAIL + 证据）

G0 Goal / Decision Gate — **PASS**
- masterplan 明确要产出“公平可复现 OPV2V 全量 benchmark + noise sweep 曲线 + camera/lidar 对照”。见 `docs/operations/opv2v_fullbench_masterplan.md:22` 起。

G1 DoD Gate — **PASS**
- DoD 明确为不可变产物 + sanity 条件。见 `docs/operations/opv2v_fullbench_masterplan.md:133` 起（§4.5）。
- 产物存在：`outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/results_ap50_from_yaml.json` + `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/plots_yaml/`。

G2 Semantics Freeze Gate — **PASS**
- `solver_backend=online_box`, `runtime_mode=register_and_fuse`, `pose_source=noisy_input` 固化在 config 快照中：
  - `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/config_snapshot.json`（keys: `solver_backend`, `runtime_mode`, `pose_source`）。

G3 Input Contract Gate (Data/Cache/Checkpoint) — **PASS**
- stage1 cache 校验通过（2170 samples, contiguous keys）：
  - camera: `tools/validate_stage1_cache.py` 输出 `[OK] ... (samples=2170)`（可复跑该命令验证）
  - lidar: 同上
- autopilot 也记录了 stage1 OK：
  - `outputs/opv2v_autopilot_20260216_auto3/autopilot.log:2-3`

G4 Checkpoint / Toolchain Health Gate — **PASS**
- masterplan 要求先 smoke；本次 autopilot 实际执行了 smoke 并通过质量门槛：
  - `outputs/opv2v_autopilot_20260216_auto3/autopilot.log:4-11`

G5 Confound / Cancellation Gate — **PASS**
- “pose-noise robustness suite 禁止 pose_override=zero”：
  - 本次 config 显式 `allow_pose_override=false`：`outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/config_snapshot.json`
- 且 baseline 曲线确实随噪声下降（非平线）：
  - LiDAR noise10 baseline AP50: 0.6042 (n=1) -> 0.4159 (n=10)
  - Camera noise10 baseline AP50: 0.2078 (n=1) -> 0.0824 (n=10)
  - 数据源：`outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/results_ap50_from_yaml.json`

G6 Effectiveness Gate (The Thing Actually Applies) — **PASS**
- 方法间出现显著分化（不是“所有方法重合/无效”）：
  - LiDAR noise10：`v2xregpp-best` 显著高于 baseline（数值见 `docs/operations/opv2v_fullbench_comparative_analysis_20260217.md:34` 起）。
- “pose_solver.applied” 这一旧口径在 online_box 下并不会写入 `results_ap50_from_yaml.json`；我们改用 `rel_error_stats` + `pose_timing` 作为“确实跑了矫正”的证据：
  - per-task YAML: `HEAL/opencood/logs/freealign_repro_opv2v_baseline/AP030507_*opv2v_autopilot_full_20260216_auto3_a1*.yaml`

G7 Source-of-Truth Gate (Completion + Metrics) — **PASS**
- 完成以 `run_state.jsonl` 为准（而不是 log grep / task_summary）：
  - `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/run_state.jsonl`
  - 统计见 `docs/operations/opv2v_fullbench_evidence_autopilot_20260216_auto3.md`（core scope ended=404；2026-02-20 camera occhint append 后 same run_id ended=444, code0=444）。
- `task_summary.json` 仍可能陈旧（pending=404），已在证据报告中显式标注：
  - `docs/operations/opv2v_fullbench_evidence_autopilot_20260216_auto3.md` §1。

G8 Resume / Re-run Safety Gate — **PASS (with note)**
- 本次 `log_mode=append`，避免了 masterplan §6 描述的 “open(log,'w') 覆盖旧结果”：
  - `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/config_snapshot.json`（key: `log_mode`）。
- NOTE: `task_summary.json` stale 仍可能误导，但不会影响 run_state 的事实记录。

G9 Smoke-First Gate — **PASS**
- smoke run 完成并通过质量门槛后才进入 full：
  - `outputs/opv2v_autopilot_20260216_auto3/autopilot.log:4-12`

G10 Cost / Stop-Loss Gate — **PARTIAL**
- 有明确 stop 机制（supervisor max_attempts=3）：
  - `outputs/opv2v_autopilot_supervisor_20260216_auto3/state.json`（keys: `max_attempts`, `attempt`）
- 但 masterplan 没有把“预算/最长耗时/触发止损阈值”写成强约束；建议补齐成可机读的 SLA。

---

## 证据链（关键事实 -> 推论 -> 风险）

1) `run_state.jsonl` core scope ended=404 且全部 code=0（append 后总 ended=444 仍全部 code=0）  
-> 本轮 scope 的任务确实完成（不是“看起来跑了”）  
-> 风险: `task_summary.json` 可能 stale，必须禁止用它做完成判定

2) stage1 cache 校验 OK（2170 samples + contiguous）  
-> 避免了旧 run camera stage1=50 samples/结构错导致方法退化为 no-op  
-> 风险: 若未来更换 cache/重建 cache，必须重新做该校验（不可跳过）

3) baseline 随噪声下降、oracle 近似水平上界  
-> 语义属于 pose-noise robustness（没有被 no-extr 取消）  
-> 风险: 如果误启用 pose_override=zero，会再次回到“平线但并非画图错”的假象

4) 仅 oracle 使用 GT 覆盖（其 cmd 明确 `--pose-correction oracle_gt`）  
-> 非 oracle 方法没有用 clean pose 直接替换外参（不属于 GT 泄漏）  
-> 风险: camera 内部坐标变换处会读取 `lidar_pose_clean` 作为回退（用于构建 camera-lidar 关系），论文里需要解释这是“车内标定/坐标系还原”，不是“跨车外参 oracle”

---

## 止损执行单（最小下一步）

1) 保持 “全 GPU” 验收条款：在汇总里继续硬性输出并检查 `cpu_fallback_count==0`（当前已满足，后续新增方法继续沿用）。  
2) 修正/移除 `task_summary.json` 误导口径（或在工具层面禁止它作为完成判定）。  
3) 对 camera-online 的异常弱增益做 targeted ablation（见 `docs/operations/opv2v_fullbench_comparative_analysis_20260217.md` 的 camera 章节）。  

---

## 复跑验收条件（如果要做下一轮 online/fullbench）

必须同时满足：
- completion: `run_state.jsonl` ended=scope_tasks 且 code=0 全通过
- sanity: baseline 随噪声下降；oracle 上界近似水平；single 用 **canonical** `single_ego_only=--force-ego-input-only (noise=0)`（禁止再用 legacy `comm_range=0(single_comm0)`；见 `docs/operations/benchmark_semantics.md`）
- integrity: stage1 cache 2170 samples 且 contiguous；所有 task 使用同一 cache（同模态内）
- semantics: config_snapshot.json 固化 `solver_backend/runtime_mode/pose_source`
- full-GPU: `cpu_fallback_count==0`（当前已由 `20260220_fullgpu*` gate 产物满足）
