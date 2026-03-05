# Benchmark 方法总览：Core vs Audit（含配准评估 → AP 评估的衔接）

更新：2026-02-24

> NOTE（2026-03-01）：benchmark 语义已冻结并更新：  
> - `single` 的 canonical 定义是 `single_ego_only=--force-ego-input-only`（保持 comm_range/GT 不变），**禁止**再用 `comm_range=0(single_comm0)` 当作 single。  
> - comm-range pruning 必须显式 pin `--comm-range-gating clean|noisy`，禁止 `auto`。  
> 统一说明见：`docs/operations/benchmark_semantics.md`。

这份文档把你目前“服务器上已经跑过/能跑的 benchmark 方法”按 **落脚点（benchmark 类型）** 与 **方法集合（core vs audit）** 做一次统一梳理，目标是：

- 你要找某个方法的结果时，知道该看哪类产物、看哪个文件是 source-of-truth；
- 你要新增/复跑某个方法时，知道它的输入契约、容易踩的坑（尤其是 online/no-op/合同漂移）；
- 你要把“只做配准评估”的结果衔接到“下游协同感知 AP”时，知道仓库里已有的映射工具与边界条件。

> “全面客观有理有据”的含义：本文不复述主结论的数值（那些在 CSV/报告里），而是把 **方法-基准-产物-有效性门槛** 说清楚，并明确哪些是 **可引用**、哪些是 **仅历史参考/需复跑**。

---

## 0) 快速入口（你要找什么就点什么）

- Benchmark 资产与 canonical/非 canonical 分类：`docs/operations/benchmark_inventory.md`
- 统一对比主报告（DAIR+OPV2V+Table III；含“OPV2V 结果不再 canonical”的更新说明）：`docs/operations/unified_benchmark_contract_and_comparison_20260220.md`
- 全矩阵（with-init/no-init/HKUST）扩展方法引入与执行状态：`docs/operations/fullmatrix_init_noinit_hkust_benchmark_status_20260220.md`
- ImageMatch（camera online）有效性审计（证明 no-op 的证据链）：`docs/operations/imagematch_initfree_remote_audit_20260223.md`
- LiDARReg/HKUST（lidar online）no-op 根因链路 + 复跑判定：`docs/operations/lidarreg_noop_root_cause_and_rerun_20260224.md`
- 配准评估 ↔ 协同感知 AP 的经验映射与预估：`docs/operations/pose_error_to_ap_mapping_report_20260224.md`

---

## 1) 你现在仓库里有哪些“基准/落脚点”（Benchmark Landing Points）

同一个方法可能在多个基准里出现，但 **指标与产物形态不同**；先把这些落脚点理清，后面方法表才能对上。

### 1.1 下游协同感知 AP（同时输出配准指标）

这是你最终想要收敛到的口径：同一套下游融合/检测链路下，对比不同 pose-correction 方法的 AP 曲线，同时从 YAML 中抽取 `rel_error_stats` 作为配准质量旁证。

核心产物形态：

- OPV2V：每个 fullbench run 是一个 run_dir（source-of-truth 以 `run_state.jsonl`/`config_snapshot.json` 为准），AP 与配准统计在模型目录的 `AP030507_*.yaml`，并由 `results_ap50_from_yaml.json` 汇总：
  - run_dir 示例：`outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/`
  - 汇总脚本：`tools/summarize_opv2v_fullbench_from_yaml.py`
  - 调度器：`tools/run_opv2v_fullbench_fast.py`

- DAIR：全量噪声 sweep 的 source-of-truth 是 jsonl（每行带 yaml_path），再聚合成统一表：
  - source sweep：`outputs/pose_sweep_1to10_full_gpuvoxel20260218_results.jsonl`
  - 统一聚合：`tools/build_unified_benchmark_report.py` 输出 `outputs/benchmark_unified_20260220/dair_noise10_ap_reg.csv`

用于“统一长表 + 同风格出图”的全矩阵产物（DAIR+OPV2V 合并）：
- 生成脚本：`tools/build_fullmatrix_benchmark_report.py`
- 产物（core 版完整）：`outputs/benchmark_fullmatrix_20260220/`（见 `summary.json`）
- 产物（audit 版严格门槛，但目前大多无效/不全）：`outputs/benchmark_fullmatrix_audit_20260224/`

### 1.2 只做配准评估（Table III / paper3737）

这是“方法本体能力”落脚点：不接下游 AP，而是在固定 pair 集上输出 registration 指标（Success/mRTE/mRRE/Time），用于对齐论文、对齐传统基线，避免把“下游模型/融合”当作注册本体能力。

- 主报告（从 jsonl 重新计算，避免 metrics.json 口径混用）：`docs/operations/table3_paper3737_repro_status.md`
- 口径重点：默认使用 `te_re`（TE<thr 且 RE<thr）来对齐 Table III 的 V2X-Reg++ 行（见该文档开头说明）。

### 1.3 只做配准评估（benchmarks/ 下的独立脚本）

这类脚本更多是“单方法/单假设”的快速对照或工程验证，产物通常是 per-frame + aggregate metrics：

- VIPS baseline：`benchmarks/run_vips_benchmark.py`（DAIR-V2X pairs）
- CBM baseline：`benchmarks/run_cbm_benchmark.py`（DAIR-V2X pairs）
- LiDAR-Registration-Benchmark（teaser/icp/picp）：`benchmarks/run_dair_lidar_benchmark.py`
- HKUST 全局注册（TEASER++ 等）：`benchmarks/hkust_lidar_global_registration_benchmark.py`

> 这些脚本的输出与 Table III 的“论文对齐”不是一回事；它们更像是 microbench/ablation。要写到统一结论里，需要把口径对齐到 Table III 或下游 AP fullbench。

### 1.4 配准评估 → AP 评估的衔接（经验映射）

当某条方法线还没完全接上 fullbench AP（或你想先止损/筛选），可以用现有结果拟合一个经验映射：

- 报告与复跑命令：`docs/operations/pose_error_to_ap_mapping_report_20260224.md`
- 产物：`outputs/pose_error_to_ap_mapping_report_20260224/`（系数/RMSE/散点图/预测点表）

---

## 2) 方法轴与命名（method / strategy / init / 生效信号）

### 2.1 method vs pose_correction（名字不等价）

在 OPV2V fullbench 这条链路里：

- `method`：你在表格/曲线上看到的“方法线名”（例如 `v2xregpp`、`hkust_teaser`）
- `pose_correction`：实际传给 `HEAL/opencood/tools/inference_w_noise.py --pose-correction ...` 的后端实现名（会出现在 `AP030507_{pose_correction}_...yaml` 文件名里）

汇总脚本对 YAML 文件名的解析在：
- `tools/summarize_opv2v_fullbench_from_yaml.py`（`parse_ap_filename`）

### 2.2 strategy：bounds / best / stable

用于画线/聚合时的 “strategy” 定义（以 OPV2V fullbench 为例）：

- `bounds`：`baseline`（pose_correction=none）与 `oracle`（pose_correction=oracle_gt）
- `best`：对 pose-correction 线，调度器会附带 `--pose-compare-current`（对比估计 pose 与 current pose，取更好者）
- `stable`：不带 `--pose-compare-current`，并使用对应的 stable corrector（通常包含时间平滑/保守更新策略）

证据（best 的参数注入）：
- 调度器在 `tools/run_opv2v_fullbench_fast.py` 为 best-of 任务添加 `--pose-compare-current`。
- 参数定义在 `HEAL/opencood/tools/inference_w_noise.py`：`--pose-compare-current`。

### 2.3 “是否真的生效”的信号（no-op 的关键）

在 fullmatrix 长表里，方法线会被打上这些状态：

- `valid`：噪声轴覆盖完整（noise=1..10；single 例外为 0.0）且（对需要 apply 的方法）能看到 applied_count
- `incomplete`：缺噪声点
- `unknown_applied`：噪声点齐全，但 YAML 中缺少 applied_count（无法 gate no-op）
- `noop`：噪声点齐全，且 applied_count 全为 0（等价 baseline，常见 wiring 问题）

判定逻辑在 `tools/build_fullmatrix_benchmark_report.py` 的 `_line_status(...)`。

> 对 imagematch 与 lidarreg/hkust 这类 online 方法，**no-op 不是小概率事件**，且会直接把曲线“伪装成 baseline”。所以：没有 applied_count/或 applied 全 0 的线，不应进入最终对比结论。

---

## 3) Core 方法集合（下游 AP 主线；可作为统一对比的最小闭环）

这里的 **core** 指你“统一对比主报告/全矩阵出图”里最常用、且在 DAIR 上已经形成 canonical 资产闭环的方法集合。

核心方法（AP fullbench 口径）：

- `baseline`（bounds）：pose_correction=`none`
- `oracle`（bounds）：pose_correction=`oracle_gt`
- `single`（bounds，OPV2V）：`--force-ego-input-only` + noise=0（保持 comm_range/merged GT labels 不变；参见 `benchmark_semantics`）
- `v2xregpp`（best/stable）
- `freealign`（best/stable）
- `vips`（best/stable）
- `cbm`（best/stable）
- `v2xregpp_occhint`（best/stable，**camera-only 扩展**；不纳入跨模态 core 主表）

核心方法在 OPV2V 调度矩阵的定义来源：
- `tools/run_opv2v_fullbench_fast.py` 的 `METHODS` 字典（method → pose_correction + 额外参数 + stage1 需求）。

### 3.1 OPV2V fullbench（调度矩阵）里 core/audit 方法的“实现映射表”

下面表格是从 `tools/run_opv2v_fullbench_fast.py` 的 `METHODS` 字典直接抽取出来的（因此是代码层面的 source-of-truth）。

| method | group | modalities | needs_stage1 | pose_correction(best/initfree) | pose_correction(stable) | extra_args |
| --- | --- | --- | --- | --- | --- | --- |
| `cbm_prior` | audit | camera,lidar | True | `cbm_initfree` | `cbm_stable` | `--cbm-use-prior` |
| `hkust_fgr` | audit | lidar | False | `lidar_reg_initfree` | `lidar_reg_stable` | `--lidar-reg-global-method teaser_fgr` |
| `hkust_quatro` | audit | lidar | False | `lidar_reg_initfree` | `lidar_reg_stable` | `--lidar-reg-global-method teaser_quatro` |
| `hkust_teaser` | audit | lidar | False | `lidar_reg_initfree` | `lidar_reg_stable` | `--lidar-reg-global-method teaser_gnctls` |
| `imagematch_current` | audit | camera | False | `image_match_initfree` | `image_match_stable` | `--image-match-init-source current` |
| `imagematch_noinit` | audit | camera | False | `image_match_initfree` | `image_match_stable` | `--image-match-init-source none` |
| `lidarreg_ransac` | audit | lidar | False | `lidar_reg_initfree` | `lidar_reg_stable` | `--lidar-reg-global-method ransac` |
| `vips_prior` | audit | camera,lidar | True | `vips_initfree` | `vips_stable` | `--vips-use-prior` |
| `cbm` | core | camera,lidar | True | `cbm_initfree` | `cbm_stable` | `` |
| `freealign` | core | camera,lidar | True | `freealign_paper` | `freealign_paper_stable` | `` |
| `v2xregpp` | core | camera,lidar | True | `v2xregpp_initfree` | `v2xregpp_stable` | `` |
| `vips` | core | camera,lidar | True | `vips_initfree` | `vips_stable` | `` |
| `v2xregpp_occhint` | core_extra | camera,lidar | True | `v2xregpp_initfree` | `v2xregpp_stable` | `--v2xregpp-use-occ-hint` |
| `cbm_noprior` | other | camera,lidar | True | `cbm_initfree` | `cbm_stable` | `` |
| `vips_noprior` | other | camera,lidar | True | `vips_initfree` | `vips_stable` | `` |

说明：
- `vips_noprior/cbm_noprior` 当前等价于 `vips/cbm`（保留它们主要是为了把“是否用 prior”显式写进 method 名）。
- `v2xregpp_occhint` 在代码上未强制 camera-only，但在现有统一聚合里只保留 camera 线（见 `outputs/benchmark_unified_20260220/coverage_checks.json` 的 occhint_counts 注释）。

### 3.2 Core 结果与产物（“看哪里算数”）

建议把 core 的“数值结论”与“方法目录”解耦：

- 你要看 core 的统一对比结果：看 `docs/operations/unified_benchmark_contract_and_comparison_20260220.md`（它会指向具体 CSV）。
- 你要看 core 的全矩阵长表/出图：看 `outputs/benchmark_fullmatrix_20260220/`（由 `tools/build_fullmatrix_benchmark_report.py` 生成）。

术语提醒（避免混淆）：
- `tools/build_unified_benchmark_report.py` 里变量名叫 `CORE_METHODS`，但它实际更像是“统一聚合脚本当前愿意收集的 method 宇宙”（包含 core + audit 的多条线），不等价于本文的“core vs audit”分组。

> 重要更新：截至 2026-02-24，OPV2V legacy run（`opv2v_autopilot_full_20260216_auto3_a1`）因 online 合同未冻结 + mixed-version 等问题，被明确标注为 **非 canonical**（见 `docs/operations/unified_benchmark_contract_and_comparison_20260220.md` 的 Update 与 `docs/operations/benchmark_inventory.md` 的 OPV2V 章节）。  
> 但 core 方法集合本身（及其代码映射）仍然成立；只是 **OPV2V 的“可信数值”需要在新 unified run_id 下重跑收口**。

---

## 4) Audit/扩展方法集合（with-init / image-match / LiDARReg/HKUST）

这里的 **audit** 指：为了把“有初值 vs 无初值 vs HKUST 全局法”拼到同一套下游 AP fullbench 里，新增/扩展的那些方法线。

它们的共同特点是：

- 需要更严格的“生效 gate”（否则极易出现 no-op 伪象）；
- 其中一部分依赖 online payload（raw image / per-CAV raw lidar points），在历史 run 中确实发生过 payload 缺失/语义绑定错误；
- 因此，**这些方法线“跑过”不等于“可引用”**，需要用 applied_count / match_sec / 统一合同重新验收。

### 4.1 with-init（仍走 stage1 的对象级路线）

- `vips_prior`：在 VIPS 的基础上使用 current pose 作为 init（通过 `--vips-use-prior` 打开）
- `cbm_prior`：同理（`--cbm-use-prior`）

它们仍然依赖 stage1（因为本体是基于 stage1 boxes 的对象匹配）；因此仍需满足 stage1 输入契约。

### 4.2 camera-only：ImageMatch（raw image matching）

- `imagematch_noinit`：`--image-match-init-source none`
- `imagematch_current`：`--image-match-init-source current`

已验证风险（强证据）：

- 在远端“统一条件冻结”的审计里，imagematch 的 `pose_provider_applied_count=0`，AP 与 baseline 完全一致 → **online no-op**。
- 该证据链与原因解释见：`docs/operations/imagematch_initfree_remote_audit_20260223.md`

因此：imagematch 要进入 fullmatrix 最终结论，必须先满足：
- online payload 完整（images + intrinsics + extrinsics/cords）
- 且 `pose_provider_applied_count > 0`（至少在一部分样本上）

### 4.3 lidar-only：LiDARReg/HKUST（raw lidar global reg）

这些方法共享同一对 pose_correction（`lidar_reg_initfree` / `lidar_reg_stable`），主要区别在 global method：

- `lidarreg_ransac`：RANSAC
- `hkust_teaser`：TEASER++ GNCTLS（`teaser_gnctls`）
- `hkust_fgr`：TEASER++ FGR 变体（`teaser_fgr`）
- `hkust_quatro`：TEASER++ Quatro 变体（`teaser_quatro`）

已验证风险（强证据）：

- 历史 run 中存在“AP 完全等于 baseline + match_sec 极小”的典型 no-op 点；
- 根因链路与复跑判定见：`docs/operations/lidarreg_noop_root_cause_and_rerun_20260224.md`

建议（成本/止损）：
- 先预计算 OPV2V lidar_reg cache，再跑 fullbench（避免重复算同一对点云注册）：
  - 入口脚本：`scripts/precompute_opv2v_lidarreg_caches.sh`

---

## 4.4 截至 2026-02-24 的“覆盖/有效性”快照（用事实解释你为什么会觉得乱）

这一段只做“现状盘点”，不做价值判断；目的是把你看到的不同报告之间的矛盾解释清楚。

- core 全矩阵（可复算的长表/出图口径，OPV2V 部分仍属 legacy 来源）：
  - `outputs/benchmark_fullmatrix_20260220/summary.json`：`rows_registry=68, valid_lines=68, incomplete_lines=0`
- audit 全矩阵（更严格的 applied gate + 追加方法线，但当前大多无法通过 gate 或覆盖不全）：
  - `outputs/benchmark_fullmatrix_audit_20260224/summary.json`：`rows_registry=96, valid_lines=16, incomplete_lines=80`
  - 其中 `outputs/benchmark_fullmatrix_audit_20260224/method_registry.csv` 的状态分布为：`valid=16, unknown_applied=68, incomplete=12`（对应“缺 applied 信号/缺噪声点”的两类问题）
- OPV2V 扩展追加（audit 方法线）在 legacy run_dir 的完成情况（为何你会看到“跑过但缺点”）：
  - `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/task_summary.json`：`scope_tasks=400, done_total_in_scope=194, pending=206`

这三条合在一起就是：
- core（旧）报告看起来“全都有”，但 OPV2V 的可信性被更后期的合同审计推翻了 → 需要新 unified run_id 复跑收口；
- audit（新）报告更严格，直接把“没有 applied 证据/覆盖不全”的线标成不可用 → 所以看起来“几乎全 invalid”；
- legacy run_dir 里确实做过 append，但没跑完 + mid-run 修复混写 → 不能直接当最终 fullmatrix。

## 5) Table III（paper3737）里有哪些“注册方法”（以及它们怎么对应到 fullbench 方法）

Table III 更像是“注册本体能力对照表”，方法集合比 fullbench 更广。你至少已经有这些家族：

- 有初值（with-init）：
  - ICP / PICP（见 `docs/operations/table3_paper3737_repro_status.md` 的 ICP/PICP 行）

- 无初值全局法（HKUST baselines）：
  - FGR / Quatro / Teaser++（Table III 行名一般是 `FGR` / `Quatro` / `Teaser++`）
  - 这类方法在 fullbench 里对应的是 audit 的 `hkust_*` 与 `lidarreg_ransac`（因为它们共享 lidar_reg 后端，只是 global_method 不同）

- 无初值对象级（V2X-Reg / V2X-Reg++）：
  - `V2X-Reg`、`V2X-Reg++ (GT/PP/SC/...)` 的多行
  - 这类方法在 fullbench 里对应的是 core 的 `v2xregpp`（以及其 occhint 变体）

- VIPS / CBM：
  - 在 Table III 里有对应行（注册-only）
  - 在 fullbench 里也有 `vips/cbm`（接下游 AP）

> “对齐使用方式”：  
> Table III 用来回答“注册本体是否在该 pair 集上可信/对齐论文”；fullbench 用来回答“注册能否带来下游 AP 增益”。  
> 两者不是互相替代，而是互相做 sanity check：如果注册本体在 Table III 上离谱或极不稳定，下游 AP 的好看结果要优先怀疑 confound/no-op。

---

## 6) 从“配准评估”过渡到“AP 评估”（你文档里已有的转换/预估）

当你只有 registration metrics（例如 success@2m / rel_yaw）但还没跑 full AP 时：

- 你可以用 `docs/operations/pose_error_to_ap_mapping_report_20260224.md` 里的经验映射来做：
  1) 粗预估 AP50（带误差尺度 RMSE）；
  2) 或用来筛选值得跑 fullbench 的方法/参数；
  3) 或用来诊断“配准看似变好但 AP 不涨”的异常（区分 confound/no-op vs 真非线性）。

关键边界条件（该文档已写明，这里再强调）：

- 映射是 **经验描述**，不是因果证明；
- 必须同一套 benchmark 合同（尤其 online 下的 comm-range gating）；
- 必须先过“生效 gate”（例如 applied_count > 0），否则任何预估无意义。

---

## 7) 统一对比前的“有效性 Gate Checklist”（强烈建议作为 DoD）

当你要把某条方法线纳入最终 fullmatrix / paper-level 对比时，建议最少满足：

1) **语义冻结（Semantics Freeze）**
   - online backend 下显式指定 `--comm-range-gating {noisy|clean}`，拒绝 `auto`（调度器已有硬 precheck）。

2) **输入契约**
   - stage1 依赖方法：stage1 cache 样本数与结构一致；
   - lidar_reg/hkust：raw lidar payload 能注入、且（最好）cache 满足 full split。

3) **完成判定**
   - OPV2V：以 run_dir 的 `run_state.jsonl` 为 source-of-truth（不要靠 log grepping 或 task_summary）。

4) **生效信号**
   - 对应方法线：`pose_provider_applied_count`（或聚合后的 `pose_applied_count`）必须能采集；
   - applied 全 0 → 视为 no-op（等价 baseline），不进最终对比。

5) **覆盖完整**
   - 噪声轴 1..10 完整；缺点的线应标注 `incomplete`，不做排名结论。

这些 gate 的“机器可见产物”就是 fullmatrix 的 `method_registry.csv`（状态字段由脚本自动打标）。

---

## 8) 你要“用好这些方法”，推荐的工作流（按省返工优先）

1) 先用 Table III（registration-only）筛掉明显不靠谱/不对齐的基线或实现口径。
2) 再在 fullbench（AP+registration）里用 core 方法建立稳定对比锚点（baseline/oracle/single + v2xregpp/freealign/vips/cbm）。
3) 对 audit 方法，先做“生效审计”（applied_count / match_sec / payload），再补齐全噪声轴后才进入 fullmatrix 排名。
4) 在需要止损时，用“配准→AP 映射”做粗筛选，但不要替代真实 fullbench AP。

---

## Appendix A) Method → 基准/产物快速对照（你找结果/找入口时用）

| 方法线/家族 | 主要落脚点 | source-of-truth 产物（示例） | 状态与注意事项（截至 2026-02-24） |
| --- | --- | --- | --- |
| baseline / oracle | 下游 AP fullbench + 配准旁证 | `outputs/benchmark_unified_20260220/*.csv`；`outputs/benchmark_fullmatrix_20260220/*` | 作为 bounds 锚点；不依赖 applied gate |
| single（comm0） | OPV2V 下游 AP fullbench | `outputs/benchmark_unified_20260220/opv2v_dual_suite_ap_reg.csv`；`outputs/benchmark_fullmatrix_20260220/*` | 仅 OPV2V；noise=0.0 单点 |
| v2xregpp（含 occhint） | Table III（注册本体）+ 下游 AP fullbench | Table III：`docs/operations/table3_paper3737_repro_status.md`；AP：`outputs/benchmark_fullmatrix_20260220/*` | occhint 目前只保留 camera 扩展线；跨模态主表不混入 |
| freealign | 下游 AP fullbench | `outputs/benchmark_fullmatrix_20260220/*` | 不属于 Table III 行；主要看 DAIR/OPV2V 的 AP+rel_error_stats |
| VIPS / CBM | Table III（注册本体）+ 下游 AP fullbench | Table III：`docs/operations/table3_paper3737_repro_status.md`；AP：`outputs/benchmark_fullmatrix_20260220/*` | 既能做注册-only 对齐，也能做下游 AP 增益评估 |
| vips_prior / cbm_prior | 下游 AP fullbench（扩展线） | legacy run：`outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/results_ap50_from_yaml.json`；audit fullmatrix：`outputs/benchmark_fullmatrix_audit_20260224/*` | 目前 audit fullmatrix 多为 unknown/incomplete；需要 unified run_id + applied gate 收口 |
| imagematch_* | 下游 AP fullbench（扩展线，camera-only） | 审计文档：`docs/operations/imagematch_initfree_remote_audit_20260223.md`；smoke：`outputs/full_bench_opv2v_unified_smoke_20260223_fix1/` | 已证实 online no-op 风险高；必须先补齐 payload + applied_count 才能进最终对比 |
| lidarreg_ransac / hkust_* | Table III（全局法）+ 下游 AP fullbench（扩展线，lidar-only） | Table III：`docs/operations/table3_paper3737_repro_status.md`；no-op 根因：`docs/operations/lidarreg_noop_root_cause_and_rerun_20260224.md` | 历史 run 存在典型 no-op；强烈建议先做 cache，再在 unified 合同下复跑 |
| ICP / PICP（注册-only） | Table III / 独立注册基准 | Table III：`docs/operations/table3_paper3737_repro_status.md`；脚本：`benchmarks/run_dair_lidar_benchmark.py` | 目前未拼到下游 AP fullbench；更多用于“有初值路线”上限参考 |
| 配准→AP 映射（工具，不是方法） | 连接 registration-only 与 AP | `docs/operations/pose_error_to_ap_mapping_report_20260224.md`；`outputs/pose_error_to_ap_mapping_report_20260224/*` | 只能做粗预估/筛选/诊断；必须先过 applied gate 与合同冻结 |

## Appendix B) 常用脚本与产物一览（便于复跑/复核）

- OPV2V fullbench 调度：`tools/run_opv2v_fullbench_fast.py`
- OPV2V fullbench 汇总：`tools/summarize_opv2v_fullbench_from_yaml.py`
- OPV2V run evidence 审计：`tools/audit_opv2v_fullbench_run.py`
- 统一聚合报告（DAIR+OPV2V+Table III）：`tools/build_unified_benchmark_report.py`
- 全矩阵长表与出图：`tools/build_fullmatrix_benchmark_report.py`
- 配准→AP 映射报告：`tools/build_pose_error_to_ap_mapping_report.py`
