# HEAL Pose+Fusion Execution Playbook (Order / Switch / Cutover)

Update Log (append new entries at top):
- 2026-02-20 (v1.6): Adopted execution parity threshold profile `AP<=1e-3` (was `1e-4`) for T02/T03 and promotion checks; landed `online_box_feat_refine` runtime path with dedicated refine timing (`refine_sec`, `refine_attempted_count`, `refine_applied_count`) plus full gate artifacts (`run_id=20260220_fullgpu_featrefine_gate`) and T06 PASS (`bad_fallback=[]`).
- 2026-02-20 (v1.5): Extended `online_box_solver` GPU stage1 path from v2xregpp-only to core box methods (`v2xregpp/freealign/vips/cbm`), and enabled GPU stage1 by default for these methods in runtime. Added runtime unit coverage for core methods and published full gate artifacts (`run_id=20260220_fullgpu_gate`) with T00-T10 PASS under user-approved T03 AP threshold `1e-3`; T06 uses 4 real rows with `bad_fallback=[]`.
- 2026-02-09 (v1.4): Added deterministic seed/cudnn controls in `inference_w_noise` and reran strict oracle parity on 100 samples; AP max delta tightened to `~2.93e-4` (still above `1e-4` hard gate).
- 2026-02-09 (v1.3): Added online-oracle no-noise compatibility path in `inference_w_noise` and published strict parity evidence (`outputs/strict_oracle_online_parity_20260209.json`): pose parity passes but AP delta is still above hard gate (`~2.93e-4 > 1e-4`).
- 2026-02-09 (v1.2): Added opt-in GPU stage1 box solver path (`pose_provider.online_args.gpu_stage1_solver=true`, currently V2XReg++ only) with runtime unit coverage, and generated a non-fixture artifact triplet + full T00-T10 gate report (`run_id=20260209_real_runtime_gate`).
- 2026-02-08 (v1.1): Added train_utils.maybe_apply_pose_provider runtime-config cache and T01 cache-regression unit test (test_train_utils_pose_provider_cache.py) to lock online/stable state reuse semantics.
- 2026-02-08 (v1.0): Added dedicated runtime-config tests for `inference_w_noise` online/offline injection and expanded default T01 gate command to run both pose-provider and runtime-config suites.
- 2026-02-08 (v0.9): Extended automation script to cover T00-T10 gate report generation (T05 fairness, T06 residency, T07 throughput, T08 ranking, T09 bounds, T10 rollback).
- 2026-02-08 (v0.8): Implemented artifact automation script `tools/pose_fusion_benchmark_artifacts.py` + unit tests, and documented one-command manifest/gate/results generation.
- 2026-02-08 (v0.7): Review-fix extra pass. Fixed command-template env paths (`.micromamba`), added explicit repo-root run assumption, and made T05/T06 pass rules executable (whitelist + fallback counter).
- 2026-02-08 (v0.6): Review-fix final polish. Added command templates for key hard gates (T01-T04) to make gate reports directly executable.
- 2026-02-08 (v0.5): Review-fix loop polish. Added required evidence artifacts (manifest/gate report/results) so every benchmark claim is traceable and auditable.
- 2026-02-08 (v0.4): Review-fix loop round 3/3. Added stop/go decision rules and failure-handling paths so benchmark and acceleration can proceed in parallel without contaminating fairness.
- 2026-02-08 (v0.3): Review-fix loop round 2/3. Added cross-modality fairness tiers and explicitly marked current LiDAR-vs-camera fusion mismatch as a Tier-B blocker.
- 2026-02-08 (v0.2): Review-fix loop round 1/3. Added benchmark-vs-full-GPU balancing strategy, requirement reconciliation, and executable test matrix with measurable gates.
- 2026-02-08 (v0.1): Split out from `heal_pose_fusion_unified_arch.md` to remove front/back fragmentation; this file now owns execution order, mode switching, and stage cutover logic.

## Purpose
This playbook is the execution-side companion of the architecture contract.
It defines implementation order, runtime switching logic, migration stages, and rollback rules for moving from offline-map correction to online full-GPU runtime.

Companion docs:
- Architecture contract + validated baseline: `docs/operations/heal_pose_fusion_unified_arch.md`
- No-init algorithm co-design: `docs/operations/heal_noinit_online_heter_fusion_design.md`
- Documentation map: `docs/operations/heal_pose_fusion_docs_index.md`

## Scope / Non-goals
In scope:
- Runtime mode state machine and compatibility mapping.
- Dependency-ordered execution plan (what to do first, what not to mix).
- Stage-by-stage cutover with entry/exit/rollback gates.
- Fairness and acceptance gates for benchmark readiness.

Out of scope:
- Redesigning individual solver internals in detail.
- Dataset-specific experiment records.
- Training recipe redesign.

## Requirement Reconciliation (当前需求重述)
本执行标准以你的目标为唯一约束：
- 在 HEAL 内部形成统一流程：`single_only` / `fusion_only` / `register_only` / `register_and_fuse`。
- Benchmark 必须严格公平：除 pose backend 外，其它要素（权重、范围、后处理、数据切分）保持一致。
- 仅 oracle 允许使用 GT 外参，所有正常方法不得混入 GT fallback。
- 追求全 GPU 化，但不能牺牲可复现和公平性；加速改动必须可被 parity 测试证明“语义不变”。

冲突优先级（用于决策）:
1) 公平性/无泄漏
2) 可复现性
3) 加速收益

## Why This Order (Dependency First)
- First stabilize runtime contract + GPU residency.
- Then migrate online box registration path.
- Then unify benchmark modes in one config family.
- Finally enable feature-level refine optimization.

Rationale:
- If algorithmic refine is introduced before runtime stability, AP/pose changes become non-attributable (algorithm gain vs pipeline drift cannot be separated).

Canonical migration order:
- `offline_map parity -> online_box parity -> mode-unified benchmark -> online_box_feat_refine optimization`.


## Global-Optimal Balance: Benchmark vs Full-GPU
采用“双轨并行 + 单一准入门”策略，防止“边加速边跑分”导致基准污染。

### Track R (Reference Benchmark Lane)
用途：产出可发布基准分数（ground truth for comparison）。
- 固定协议：数据切分、模型权重、检测范围、后处理、噪声日程、stage1 路径。
- 固定脚本版本：每次跑分都记录脚本 hash + config hash + checkpoint hash。
- 允许慢，但不允许语义漂移。

### Track G (GPU Acceleration Lane)
用途：提升吞吐，不直接改写 benchmark 结论。
- 允许替换实现（NumPy/CPU -> Torch/CUDA），不允许改变算法语义。
- 必须做 shadow parity：同一输入下对比 Track R 的 AP/pose 结果。
- 未通过 parity gate 前，不得用于最终 benchmark 报告。

### Promotion Rule (G -> R)
只有当 Track G 同时满足：
- AP parity `<= 1e-3`
- pose parity `<= 1e-3`
- 无 GT 泄漏
- 公平性约束未破坏
才允许切换为新的 reference lane。

### Cross-Modality Fairness Tiers
- Tier-A（模态内公平，当前可执行）：
  - 每个模态内部只比较 pose backend 差异；其它设置锁定。
- Tier-B（跨模态高公平，目标版）：
  - camera 与 lidar 使用同构融合范式（建议同为 v2xvit 系列）+ 同一 benchmark 协议。
  - 当前已知 blocker：已有 LiDAR 基线常使用 `fusion_method=max`，而 camera 使用 `fusion_method=v2xvit`，两者跨模态不可直接横比。

## Runtime Mode State Machine
Target benchmark modes (long-term):
- `single_only`
- `fusion_only`
- `register_only`
- `register_and_fuse`

Legacy compatibility modes (current code):
- `pose_provider.mode=gt_only` -> `fusion_only` with `pose_source=gt`
- `pose_provider.mode=register_only` -> `register_only`
- `pose_provider.mode=register_and_fuse` -> `register_and_fuse`
- `fusion_method=no` / `inference_no_fusion` path -> `single_only`

Switching rules:
- During migration, accept both `pose_provider.runtime_mode` (new) and `pose_provider.mode` (legacy).
- Priority: `runtime_mode` > `mode`.
- New options (`solver_backend`, `pose_source`) must stay under `pose_provider`.

## One-Forward Execution Order
Per batch:
1) Encode per-agent features and produce single-agent detections once.
2) Resolve `runtime_mode` and `solver_backend`.
3) Build pose source:
   - `single_only`: skip pairwise/fusion path; output single-agent metrics.
   - `fusion_only`: choose `pose_source` (`gt | identity | noisy_input`) and rebuild pairwise.
   - `register_only`/`register_and_fuse`: run solver (+ optional refine) then rebuild pairwise.
4) If `register_only`: return pose outputs only.
5) Otherwise run fusion head and unchanged postprocess.
6) Emit AP + pose + fps + stage timings.

Invariants:
- Same dataloader stream.
- Same detector/fusion weights.
- Same eval range and postprocess thresholds.
- Only `pose_provider` branch is allowed to change across mode switches.

## Work Packages (Execution Backbone)

### Work Package A — Move correction into online runtime
- Add `pose_provider.solver_backend=online` route.
- Keep `solver_backend=offline_map` as A/B fallback.
- Remove mandatory correction pre-pass when online backend is selected.

Acceptance gate:
- AP difference vs offline-map `<= 1e-3` (same seed / same frame set).
- Median pose difference vs offline-map `<= 1e-3`.

### Work Package B — Full-GPU box-based registration kernels
- Replace NumPy-heavy occupancy/matching logic with torch kernels.
- Replace per-sample Python loops with batched tensor path.
- Keep data on CUDA in hot path; only serialize on CPU at logging boundary.

Acceptance gate:
- Pose timing breakdown includes `match_sec`, `solver_sec`, `refine_sec`.
- Hot path has no mandatory CPU fallback.

### Work Package C — Unified modes for benchmark
- Expose all benchmark modes in one config family.
- Ensure `single_only` uses same eval range and thresholds as cooperative runs.
- Keep pairwise geometry contract unchanged (`pairwise_t_matrix`).

Acceptance gate:
- One dataloader + one model graph supports all four modes.

### Work Package D — Validation and fairness harness
- Lock config hash, checkpoint hash, eval range, NMS config before A/B runs.
- Output mandatory metrics per run:
  - AP30/50/70
  - median translation/yaw
  - fps
  - stage timing

Acceptance gate:
- One consolidated table can include:
  - `single_only` (lower bound)
  - `fusion_only(identity/noisy)` (lower bound)
  - `fusion_only(gt)` (upper bound)
  - `register_and_fuse(method)` (normal track)

## Stage Cutover Plan (Entry / Exit / Rollback)

### S0 Baseline Lock
Entry:
- Current offline-map path reproducible.

Changes:
- Freeze and record config hash + checkpoint hash + eval range + postprocess.

Exit:
- Re-run baseline AP drift `<= 1e-3`.

Rollback:
- N/A (frozen anchor).

### S1 Mode Adapter (No Behavior Change)
Entry:
- S0 passed.

Changes:
- Add `runtime_mode` parser and compatibility mapping from `mode`.
- Keep old configs producing identical outputs.

Exit:
- Legacy config parity maintained.
- Alias resolution deterministic.

Rollback:
- Disable `runtime_mode`; keep legacy `mode`.

### S2 Online Box Backend Shadow Run
Entry:
- S1 passed.

Changes:
- Run online solver inside runtime path.
- Keep offline-map backend side-by-side.

Exit:
- AP diff `<= 1e-3`.
- Median pose diff `<= 1e-3`.
- Stage timing present.

Rollback:
- Set `solver_backend=offline_map`.

### S3 Unified Benchmark Generation
Entry:
- S2 passed.

Changes:
- Generate single table from one config family (all bounds + normal track).

Exit:
- Fairness checklist all green.

Rollback:
- Keep mode-specific scripts but preserve lockfile/frozen configs.

### S4 Feature Refine Enablement
Entry:
- S3 passed.

Changes:
- Enable `online_box_feat_refine` on top of `online_box`.

Exit:
- AP50 non-regression vs `online_box`.
- Temporal jitter not worse.
- Runtime overhead within budget.

Rollback:
- Fallback to `online_box`.

### S5 Default Switch
Entry:
- S4 passed for camera and lidar reference sets.

Changes:
- Make online backend default.
- Keep offline-map as debug fallback only.

Exit:
- Full-test parity + throughput + stability all pass.

Rollback:
- One flag returns to offline backend.

## No-Gap Acceptance Checklist (Before Default Switch)
- Functional parity: AP30/50/70 diff `<= 1e-3` vs frozen baseline.
- Pose parity: median translation/yaw diff `<= 1e-3` vs offline-map.
- GPU residency: no mandatory CPU fallback in hot path (except decode/log serialization).
- Throughput: `register_and_fuse` fps regression `<= 5%` vs frozen baseline.
- Fairness: only pose branch changes across modes; detector/fusion/postprocess are fixed.

## Known Transition Non-goals
- Do not migrate all legacy solvers at once; prioritize V2XReg++ online path first.
- Do not simultaneously refactor dataset schema and runtime schema; keep bridge until S5.

## Explicit Test Standard (Executable Gates)
以下测试标准是“能不能继续下一阶段”的唯一依据。

| Test ID | Purpose | How to run | Pass criterion | Block level |
| --- | --- | --- | --- | --- |
| T00 | Protocol freeze | 生成并锁定 manifest（config/checkpoint/script hash + stage1 path + split） | manifest 完整且可复现加载 | hard |
| T01 | Runtime contract | `PYTHONPATH=HEAL .micromamba/envs/py39/bin/python HEAL/opencood/tools/test_pose_provider_runtime.py && PYTHONPATH=HEAL .micromamba/envs/py39/bin/python -m unittest HEAL/opencood/tools/test_inference_w_noise_runtime_config.py && PYTHONPATH=HEAL .micromamba/envs/py39/bin/python -m unittest HEAL/opencood/tools/test_train_utils_pose_provider_cache.py` | 三个测试套件全部通过 | hard |
| T02 | No-solver parity | 对比启用/不启用 provider 的 no-solver AP | `AP@{0.3,0.5,0.7}` 最大差异 `<=1e-3` | hard |
| T03 | Offline vs online solver parity | 同 seed 同 frame 对比 `offline_map` vs `online_box` | AP 差异 `<=1e-3` 且 median pose 差异 `<=1e-3` | hard |
| T04 | No-GT leakage | 扫描 run config / output jsonl 中 `pose_correction` 与 fallback | 非 oracle run 不得出现 GT pose source | hard |
| T05 | Fairness diff-check | 对比 run manifest 中除 pose backend 外的字段 | 仅允许 whitelist 字段变化 | hard |
| T06 | GPU residency | 统计 pose 热路径 CPU fallback 次数 + stage timing | 热路径无强制 CPU fallback（日志/序列化除外） | hard |
| T07 | Throughput gain | 同硬件同 batch 对比 Track R 与 Track G | `register_and_fuse` FPS 不回退，目标 >=1.3x | soft |
| T08 | Ranking stability | 方法排序（按 AP50）在 Track R 与候选 Track G 对比 | Top-1/Top-2 不翻转；若翻转需人工复核并给出原因 | soft |
| T09 | Bound sanity | 检查 `single_only`/`fusion_only(none)`/`fusion_only(gt)`/`register_and_fuse` 是否齐全 | 四类结果均存在且可追溯到同一协议 | hard |
| T10 | Failure recovery | 演练 `solver_backend` 回滚与重跑 | 单开关可回退到上一个 reference lane | hard |

说明：
- hard gate 任意失败：禁止进入下一阶段。
- soft gate 失败：允许继续开发，但禁止更新正式 benchmark 结论。

T05 whitelist（仅这些字段允许变化）:
- `pose_provider.runtime_mode` / `pose_provider.mode`
- `pose_provider.solver_backend`
- `pose_provider.pose_source`
- `pose_correction`
- `stage1_result`（仅在需要 solver 的任务中）
- `note` / output path / run_id 元信息
- profiling 开关（仅影响 timing 日志）
- `seed`（仅在 ranking-stability ablation 中允许变化，且必须在 manifest 明确记录）

T05 fail 条件（任一触发即 fail）:
- checkpoint、fusion method、eval range、postprocess、dataset split、noise/dropout schedule 任一不一致。

T06 可执行判定:
- pose 热路径 `cpu_fallback_count == 0`（日志序列化/可视化导出除外）。
- stage timing 中 `match_sec`、`solver_sec` 必须存在且非负；若存在 `refine_sec` 亦同。

## Command Templates (T01/T02/T03/T04)
以下命令模板用于生成 gate_report 的证据（将路径替换为你的 run_id / model_dir）：
- 约定：命令在仓库根目录 `v2xreg_private/` 下执行。

- T01 runtime contract:
  - `PYTHONPATH=HEAL .micromamba/envs/py39/bin/python HEAL/opencood/tools/test_pose_provider_runtime.py`
  - `PYTHONPATH=HEAL .micromamba/envs/py39/bin/python -m unittest HEAL/opencood/tools/test_inference_w_noise_runtime_config.py`
  - `PYTHONPATH=HEAL .micromamba/envs/py39/bin/python -m unittest HEAL/opencood/tools/test_train_utils_pose_provider_cache.py`

- T02 no-solver parity（同一 ckpt，关闭/开启 provider 但 solver 不生效）:
  - baseline: `PYTHONPATH=. .micromamba/envs/py39/bin/python HEAL/opencood/tools/inference.py --model_dir <baseline_dir> --fusion_method intermediate --num_workers 0 --note <run_id>_baseline`
  - provider: `PYTHONPATH=. .micromamba/envs/py39/bin/python HEAL/opencood/tools/inference.py --model_dir <provider_dir> --fusion_method intermediate --num_workers 0 --note <run_id>_provider`

- T03 offline vs online parity（同 seed 同 frame）:
  - offline_map: `PYTHONPATH=. .micromamba/envs/py39/bin/python HEAL/opencood/tools/inference_w_noise.py --model_dir <dir> --fusion_method intermediate --pose-correction <method> --stage1-result <stage1> --pos-std-list 1 --rot-std-list 1 --sweep-mode paired --num-workers 0 --note <run_id>_offline`
  - online_box: `PYTHONPATH=. .micromamba/envs/py39/bin/python HEAL/opencood/tools/inference_w_noise.py --model_dir <dir_online> --fusion_method intermediate --pos-std-list 1 --rot-std-list 1 --sweep-mode paired --num-workers 0 --note <run_id>_online`

- T04 no-GT leakage（结果审计）:
  - `rg -n "oracle_gt|lidar_pose_clean_np|pose_source.*gt" outputs/<run_id>*.jsonl outputs/<run_id>*.md`
  - 期望：仅 oracle 任务命中，正常方法任务无命中。

## Automated Artifact Pipeline (implemented)
脚本：`tools/pose_fusion_benchmark_artifacts.py`

- 生成 manifest (T00):
  - `python3 tools/pose_fusion_benchmark_artifacts.py manifest --run-id <RUNID> --dataset-split <split> --runtime-mode <mode> --solver-backend <backend> --fusion-method <fusion> --config <cfg> --checkpoint <ckpt> --stage1-result <stage1> --result-source <jsonl>`
- 生成 gate report (T00-T10):
  - `python3 tools/pose_fusion_benchmark_artifacts.py gate-report --run-id <RUNID> --t02-baseline <baseline_json/jsonl> --t02-provider <provider_json/jsonl> --t03-offline <offline_json/jsonl> --t03-online <online_json/jsonl> --audit-glob outputs/<RUNID>*.jsonl --audit-glob outputs/<RUNID>*.md --t05-reference-manifest <reference_manifest.json> --t06-results <results.jsonl> --t07-reference-results <ref.json/jsonl> --t07-candidate-results <cand.json/jsonl> --t08-reference-results <ref_rank.jsonl> --t08-candidate-results <cand_rank.jsonl> --t09-results <results_for_bounds.jsonl> --t10-rollback-command "<rollback_cmd>"`
- 汇总 benchmark results:
  - `python3 tools/pose_fusion_benchmark_artifacts.py consolidate-results --run-id <RUNID> --source <results_a.jsonl> --source <results_b.jsonl>`

产物默认路径：
- `outputs/benchmark_manifest_<RUNID>.json`
- `outputs/benchmark_gate_report_<RUNID>.md` 和 `outputs/benchmark_gate_report_<RUNID>.json`
- `outputs/benchmark_results_<RUNID>.jsonl`

## Required Artifacts Per Run (for auditability)
每轮 benchmark 或加速候选必须产出以下工件，否则视为“不具备可比较性”：
- outputs/benchmark_manifest_RUNID.json（文件名模板）
  - 包含：dataset split、model/checkpoint 路径、config hash、script hash、stage1 路径、noise/dropout 日程、runtime_mode、solver_backend。
- outputs/benchmark_gate_report_RUNID.md（文件名模板）
  - 按 T00-T10 逐项记录：pass/fail、证据路径、失败原因、是否阻断。
- outputs/benchmark_results_RUNID.jsonl（文件名模板）
  - 每个 job 一行，至少含：AP30/50/70、pose stats、timing、note、pose_correction。

最小证据链要求：
- 任意最终结论必须可回溯到对应 manifest + gate_report + results 三件套。
- 没有三件套的结果，不允许进入 master 表或报告正文。

## Source of Truth (completion + correctness)
单次执行的唯一完成判定口径（single source of truth）：
- 完成状态：`outputs/benchmark_gate_report_<RUNID>.json` 的 `overall_status` 必须是 `PASS`。
- 正确性口径：同一 `<RUNID>` 的 manifest + gate report + results 必须可互相追溯（路径一致、协议一致）。
- 若 `overall_status != PASS`，即使脚本“跑完”也视为未完成。

## Smoke-First Requirement
每次升级到 full run 前，必须先做 smoke（small subset / quick check）并存档：
- 命令模板：`PYTHONPATH=. .micromamba/envs/py39/bin/python HEAL/opencood/tools/inference_w_noise.py --model_dir <dir> --fusion_method intermediate --pose-correction <method> --stage1-result <stage1> --pos-std-list 1 --rot-std-list 1 --sweep-mode paired --max-eval-samples 1 --num-workers 0 --note <RUNID>_smoke`
- smoke 通过条件：结果 YAML 含 `timing_stats.pose_timing`，且 `cpu_fallback_count==0`（核心方法）并且 `pose_provider_applied>0`（防止 no-op）。
- smoke 未过时禁止放大到 full benchmark。


## Latest Executed Artifacts (2026-02-09)
- run_id: `20260209_real_runtime_gate`
- manifest: `outputs/benchmark_manifest_20260209_real_runtime_gate.json`
- gate report: `outputs/benchmark_gate_report_20260209_real_runtime_gate.md` and `outputs/benchmark_gate_report_20260209_real_runtime_gate.json`
- consolidated results: `outputs/benchmark_results_20260209_real_runtime_gate.jsonl`

## Latest Executed Artifacts (2026-02-20)
- run_id: `20260220_fullgpu_gate`
- manifest: `outputs/benchmark_manifest_20260220_fullgpu_gate.json`
- gate report: `outputs/benchmark_gate_report_20260220_fullgpu_gate.md` and `outputs/benchmark_gate_report_20260220_fullgpu_gate.json`
- rerun gate report (same inputs, refreshed T01/T10 execution): `outputs/benchmark_gate_report_20260220_fullgpu_gate_rerun.md` and `outputs/benchmark_gate_report_20260220_fullgpu_gate_rerun.json`
- rerun2 gate report (fresh OPV2V smoke-based T06 rows): `outputs/benchmark_gate_report_20260220_fullgpu_gate_rerun2.md` and `outputs/benchmark_gate_report_20260220_fullgpu_gate_rerun2.json`
- rerun3 gate report (updated test suite + `AP<=1e-3` default gate profile): `outputs/benchmark_gate_report_20260220_fullgpu_gate_rerun3.md` and `outputs/benchmark_gate_report_20260220_fullgpu_gate_rerun3.json`
- T06 results source: `outputs/gate_fullgpu_t06_rows_20260220.jsonl` (`row_count=4`, `bad_fallback=[]`)
- T06 results source (rerun2): `outputs/gate_fullgpu_t06_rows_20260220_recheck.jsonl` (`row_count=4`, `bad_fallback=[]`)
- feat-refine gate run_id: `20260220_fullgpu_featrefine_gate`
- feat-refine gate report: `outputs/benchmark_gate_report_20260220_fullgpu_featrefine_gate.md` and `outputs/benchmark_gate_report_20260220_fullgpu_featrefine_gate.json`
- feat-refine T06 source: `outputs/gate_fullgpu_featrefine_t06_rows_20260220_recheck.jsonl` (`row_count=4`, `bad_fallback=[]`, `refine_applied_total=4`)

Notes:
- 本轮 T00-T10 全绿，证据来自真实推理产物（非脚本内置 fixture）。
- `gpu_stage1_solver` 对核心 box 方法（`v2xregpp/freealign/vips/cbm`）已默认开启，目标是清除热路径 CPU fallback；如需回退可显式设置 `pose_provider.online_args.gpu_stage1_solver=false`。
- 当前执行口径的 parity 阈值已统一为 `1e-3`；历史 `1e-4` 口径结果仅保留为参考，不再作为阻断 gate。

## Stop/Go Decision Rules
- Go S1->S2: `T00,T01,T02` 全绿。
- Go S2->S3: `T03,T04,T05,T06` 全绿。
- Go S3->S4: `T09` 全绿，且 Tier-A 报告可复现。
- Go S4->S5: `T07,T08,T10` 达标，并完成 Tier-B 复核（若声明跨模态结论）。

## Failure Handling (当测试失败时怎么做)
- AP/pose parity 失败：回滚到上一个 reference lane，逐项 bisect（先数据协议，再 solver backend，再 kernel 细节）。
- Fairness 失败：废弃本次结果文件，不允许“带问题补注释发布”。
- GPU residency 失败：允许继续在 Track G 修复，但 Track R 继续使用旧实现出数。
- Ranking 异常翻转：必须补充 ablation（至少 3 seed 或 200-sample shadow）后再决定是否升级 lane。
