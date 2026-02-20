# HEAL Pose+Fusion Docs Index (Single Entry)

Update Log (append new entries at top):
- 2026-02-09 (v1.3): Synced playbook v1.4 / unified-arch Round20 (deterministic parity run, strict oracle delta now `~2.93e-4`, still not promotable).
- 2026-02-09 (v1.2): Synced playbook v1.3 / unified-arch Round19. Added strict oracle parity evidence path (`outputs/strict_oracle_online_parity_20260209.json`) and current not-pass status for Track-R promotion.
- 2026-02-09 (v1.1): Synced with execution playbook v1.2 and no-init design v1.0 (`online_box_solver` landed as opt-in GPU stage1 path; non-fixture gate artifacts published with run_id=20260209_real_runtime_gate).
- 2026-02-08 (v1.0): Synced with playbook v1.1; T01 now includes pose-provider runtime cache regression tests for stateful online execution consistency.
- 2026-02-08 (v0.9): Synced with playbook v1.0; T01 hard-gate now includes both pose-provider runtime tests and `inference_w_noise` runtime-config tests.
- 2026-02-08 (v0.8): Synced with playbook v0.9; artifact automation now supports full T00-T10 gate coverage.
- 2026-02-08 (v0.7): Added implementation pointer to artifact automation script `tools/pose_fusion_benchmark_artifacts.py` for manifest/gate-report/results generation.
- 2026-02-08 (v0.6): Synced with playbook v0.7; added pointer that T05 whitelist/T06 GPU-residency判定已转为可执行规则。
- 2026-02-08 (v0.5): Synced with playbook v0.6; key gate command templates (T01-T04) are now documented for direct execution.
- 2026-02-08 (v0.4): Added traceability pointer: benchmark claims must be backed by manifest/gate-report/results artifacts from execution playbook.
- 2026-02-08 (v0.3): Marked `heal_pose_fusion_execution_playbook.md` as the canonical source for benchmark-vs-GPU balancing policy and executable gates (T00-T10).
- 2026-02-08 (v0.2): Added active-doc policy (only 3 active docs) and a rule for introducing new docs to control documentation sprawl.
- 2026-02-08 (v0.1): Created as single navigation entry after splitting execution playbook from architecture contract.

## Why this index exists
The project already has many operation docs. This index keeps pose+fusion related docs to a minimal, role-clear set so day-to-day work does not jump across too many files.

## Core docs (read in this order)
1) Architecture contract / current validated baseline
- `docs/operations/heal_pose_fusion_unified_arch.md`
- Read when: you want "what is true in current code" and "what interface/semantics are fixed".

2) Execution order / switching / cutover (implementation playbook)
- `docs/operations/heal_pose_fusion_execution_playbook.md`
- Read when: you want "what to do next", "how to switch modes safely", and "how to rollback".

3) Algorithm co-design (no-init + heter-fusion)
- `docs/operations/heal_noinit_online_heter_fusion_design.md`
- Read when: you want "what algorithmic extension to add after runtime foundation is stable".


## Active set policy（控文档数量）
- Pose+Fusion 主题默认只维护 3 份活跃文档（本页列出的 Core docs）。
- 新增第 4 份文档前，必须先判断是否能作为现有文档的附录/小节。
- 只有在“受众不同 + 更新频率不同 + 生命周期不同”三者同时满足时，才允许新开文档。

## Ownership boundary (avoid overlap)
- `unified_arch`: architecture contract + current validated behavior + acceptance definitions.
- `execution_playbook`: staged delivery plan, benchmark-vs-GPU balancing policy, and executable go/no-go gates.
- `noinit_design`: future algorithm design and ablation decisions.

Rule: if content is procedural (order/switch/rollback), it belongs to `execution_playbook`; if content is contract-level truth, it belongs to `unified_arch`.

## Update policy
- Every non-trivial update to any of the three docs must append one line to its own Update Log.
- If boundary changes, update this index first, then update affected docs.

## Operational entry (artifact 三件套)
- 脚本入口：`tools/pose_fusion_benchmark_artifacts.py`
- 用途：自动生成 `benchmark_manifest`、`benchmark_gate_report`、`benchmark_results`，作为 benchmark 证据链最小闭环。

## Quick decision map
- "我要看现在到底实现到哪了" -> `heal_pose_fusion_unified_arch.md`
- "我要按什么顺序做，怎么切换不翻车" -> `heal_pose_fusion_execution_playbook.md`
- "我要做无初值+异构融合的算法扩展" -> `heal_noinit_online_heter_fusion_design.md`
- "我要先确认哪些测试必须过" -> `heal_pose_fusion_execution_playbook.md`（T00-T10）
- "我要审计这次结论有没有证据链" -> `heal_pose_fusion_execution_playbook.md`（Required Artifacts）
