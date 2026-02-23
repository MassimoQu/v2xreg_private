# V2XReg Private Worktree — Master Index (2026-02-23)

这份仓库是一个“研究 + 复现 + 工程落地”的私有工作树：目标不是只跑出一两个数，而是把
**协同感知 AP** 与 **配准质量** 在 **DAIR / OPV2V** 上用统一口径打通，最后得到可复核的结论与产物。

如果你只看一个入口：
- **实验/结果主索引**：`docs/operations/config_experiment_map_20260220.md`
- **统一对比主报告（DAIR+OPV2V+Table III）**：`docs/operations/unified_benchmark_contract_and_comparison_20260220.md`
- **全矩阵（有初值/无初值/HKUST）补跑状态**：`docs/operations/fullmatrix_init_noinit_hkust_benchmark_status_20260220.md`
- **imagematch 断档领先排查（远端统一条件）**：`docs/operations/imagematch_initfree_remote_audit_20260223.md`

---

## 1) 你在这个仓库里做了什么（按“目的链路”梳理）

1. **把“配准是否真的能提升协同感知 AP”这件事做成可对比 benchmark**
   - DAIR：`outputs/pose_sweep_1to10_full_gpuvoxel20260218_results.jsonl`
   - OPV2V：`outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/`

2. **把“方法本体能力（注册）”和“下游 AP 增益”分开核验**
   - DAIR Table III（paper3737=3737 pairs）复现与对齐：
     - 报告：`docs/operations/table3_paper3737_repro_status.md`

3. **把“有初值 / 无初值 / HKUST 全局法”串到同一套下游协同感知流程里**
   - 调度矩阵与聚合脚本：
     - `tools/run_opv2v_fullbench_fast.py`
     - `tools/build_fullmatrix_benchmark_report.py`
     - `tools/build_unified_benchmark_report.py`

4. **把明显的 confound / 假象（尤其 imagematch）做成可追溯的证据链**
   - 远端统一条件审计：`docs/operations/imagematch_initfree_remote_audit_20260223.md`

---

## 2) 这是一个“多项目/多仓库”形态（怎么保存代码才算规范）

该工作树至少包含两层仓库：
- 主仓：`v2xreg_private/`（调度、报告、pipeline glue、docs）
- 子模块：`HEAL/`（HEAL/opencood 侧的 online pose provider、配准实现、inference）

规范保存流程见：
- `docs/operations/repo_hygiene.md`

关键约束（否则很容易“跑出来但不可复现”）：
- 改 `HEAL/` 必须在 `HEAL/` 内单独 commit；主仓只提交 submodule 指针。
- canonical benchmark 必须 **git clean**（至少要能从 `config_snapshot.json` 复原到同一 commit）。

---

## 3) “统一 benchmark 条件”到底指什么（口径冻结）

统一对比依赖 3 类 source-of-truth：

1. **语义冻结（Semantics Freeze）**
   - solver backend / runtime mode / pose source / comm-range gating 等必须显式写进命令或快照。
   - OPV2V fullbench 的快照文件：`outputs/*/config_snapshot.json`

2. **完成判定（Completion）**
   - OPV2V：`outputs/*/run_state.jsonl`（start/end + code）

3. **指标产物（Metrics Artifacts）**
   - OPV2V：模型目录下的 `AP030507_*.yaml`（AP + rel_error_stats + pose_timing）
   - 聚合后 CSV/JSON：
     - `outputs/benchmark_unified_20260220/*`
     - `outputs/benchmark_fullmatrix_20260220/*`

重要经验：`inference_w_noise.py` 在 pose-correction=online_* 时会**隐式**切换 comm-range gating 语义。
为了避免“方法 A 只因为 gating 不同而 AP 变好/变坏”的 confound，需要显式传 `--comm-range-gating` 并写入快照。

（对应实现入口：`tools/run_opv2v_fullbench_fast.py`）

---

## 4) 当前已收敛的结论（以可追溯产物为准）

以 `docs/operations/unified_benchmark_contract_and_comparison_20260220.md` 的聚合表为准：
- **LiDAR**（DAIR + OPV2V）：`v2xregpp/freealign` 对 AP 有稳定正增益，接近 oracle。
- **Camera**：整体增益弱且不稳定，是当前主瓶颈。

imagematch（camera raw image matching）：
- 在远端统一条件审计下，`image_match_initfree` 不会真正 apply pose update，AP 与 baseline 相同：
  见 `docs/operations/imagematch_initfree_remote_audit_20260223.md`。
- 在本地进一步验证中，imagematch 在严格安全门限下 `pose_provider_applied_count=0`（等价 no-op）；
  放松门限可以强行 apply，但配准误差爆炸并显著伤害 AP（说明 estimator 输出不可靠）。

---

## 5) 下一步（把“全矩阵大对比”跑成最终版）

你想要的“有初值/无初值/HKUST + 下游协同感知 AP + 配准指标”的最终版，需要：

1. **在 OPV2V 上重新跑一版完全统一条件的 fullbench**
   - 统一 python env / git commit / comm-range gating
   - 以最新方法版本为准（尤其 lidar_reg 的 T 修复、imagematch online payload）

2. **刷新全矩阵长表与统一出图**
   - `tools/summarize_opv2v_fullbench_from_yaml.py`
   - `tools/build_fullmatrix_benchmark_report.py`

3. **DAIR 补齐同口径矩阵（把 HKUST/with-init 也拼到下游 AP）**
   - 目前 DAIR canonical 仍以 core methods 为主；扩展线需要单独补跑并并入 fullmatrix 输出口径。

