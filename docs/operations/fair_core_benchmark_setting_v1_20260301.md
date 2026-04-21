# Fair Core Benchmark Setting v1（DAIR / OPV2V / V2V4Real）

更新：2026-03-01

这份文档只做一件事：给出一套**最合理、最公平、且可复核的 core(no-init/no-prior) benchmark 合同**，并把容易“看文档切片被带歪”的坑一次性写死。

> Canonical 语义来源：`docs/operations/benchmark_semantics.md`（single / oracle / comm-range gating / online vs offline）。

---

## 0) 目标（跑完能做什么决策）

- 在每个数据集内（DAIR / OPV2V / V2V4Real 各自独立）并且在每个 **modality 内**（camera/lidar 各自独立）公平比较 core 方法：`v2xregpp / freealign / vips / cbm`（均为 no-init/no-prior）。
- 解释清楚：single/oracle/online/offline/noisy/clean 的语义边界；保证不会因为 `comm_range=0(single_comm0)`、`comm-range-gating=auto`、`offline_map` 等造成“变题/混语义”。
- 产物必须可复核：每个 run 都能从 artifact 反推出“到底跑了什么”（而不是靠记忆/截图）。

非目标：
- 不把跨数据集 AP 绝对值硬横比（只看各数据集内排序/增益）。
- 不补 VIPS/CBM prior（本合同只评 no-init）。

---

## 1) 单一答案：什么设置最公平？

结论：建议把 core benchmark 明确分成两条 lane（不要混在一张主表里）：

1) **Track-D（Diagnostic / 更公平可解释）**：`online_box + comm-range-gating=clean`  
   - 固定 agent set（通信裁剪不随噪声抖动），最大化“只测 pose 对齐误差→AP”的可解释性。
2) **Track-S（System / 更真实）**：`online_box + comm-range-gating=noisy`  
   - 包含真实系统中的邻居裁剪抖动；更贴近部署（不同数据集抖动幅度不同，必须附证据解释）。

两条 lane **共同冻结项（必须完全一致）**：

- fusion：`--fusion_method intermediate`
- runtime：`--solver-backend online_box --runtime-mode register_and_fuse --pose-source noisy_input`
- sweep：`--sweep-mode paired --noise-target non-ego`
- noise axis：`pos_std_list=rot_std_list=0..10`（除非明确标注为 partial/legacy）
- dataloader：`--num-workers 0`
- bounds：
  - baseline：`--pose-correction none`
  - **single_ego_only（canonical）**：`--force-ego-input-only`（只跑 noise=0；画图当作水平线；严禁用 comm=0 造曲线）
  - oracle（上界，**必须按 pose_correction 精确命名**）：默认 `--pose-correction oracle_gt`（online_box 下禁噪，严格平线）；可选再画 `v2vloc_oracle_initfree|stable`（保留注噪/裁剪抖动，Track‑S 下允许轻微漂移）。**图例/表格禁止只写 “oracle”**。

本合同的 core 方法（no-init/no-prior）按**精确字符串**写死（避免“看起来像跑了其实不是同一个方法”）：

| 方法族 | canonical（best/initfree） | canonical（stable，可选） |
|---|---|---|
| V2X-Reg++ | `v2xregpp_initfree` | `v2xregpp_stable` |
| FreeAlign | `freealign_paper` | `freealign_paper_stable` |
| VIPS | `vips_initfree` | `vips_stable` |
| CBM | `cbm_initfree` | `cbm_stable` |

实现一致性提示（VIPS/CBM）：
- VIPS/CBM estimator 的 `T` 语义是 **(arg1 -> arg2)**；core benchmark 里我们统一使用 **(cav -> ego)** 的相对位姿。`Stage1VIPSPoseCorrector/Stage1CBMPoseCorrector` 必须按该方向调用 estimator，否则会系统性劣化 VIPS/CBM（属于实现 bug，而不是方法不行）。回归测试：`tools/tests/test_stage1_vips_cbm_direction.py`。

---

## 2) 必须禁止的“看起来合理但其实变题”的做法

### 2.1 禁止 legacy `single_comm0`

- 禁止：`--comm-range-override 0` 当 single（会改变 agent/GT set，导致 AP 虚高，甚至 single>oracle）。
- 证据与复现：`docs/operations/benchmark_semantics.md#11-禁止single_comm0legacy`（含 OPV2V/DAIR/V2V4Real 的 GT count + AP 对照）。

### 2.2 禁止 `comm-range-gating=auto`（用于 benchmark）

- 必须显式 pin：`--comm-range-gating clean|noisy`。
- 理由与根因：`auto` 可能被 solver_backend/runtime/pose_correction 隐式影响，形成 cross-method confound。

### 2.3 禁止用 `offline_map` 做 core 方法结论

- `offline_map` 与 `online_box` 不是同一个 benchmark（见 `docs/operations/benchmark_semantics.md#4-online-vs-offline`）。
- offline_map 可用于 parity/调试/止损，但主结论必须来自 online_box。

---

## 3) 必过 Gate（Fail-fast；不过就别跑 full）

0) **backend/runtime gate**：artifact（`manifest.json` / YAML 头部）必须明确包含 `solver_backend=online_box`、`runtime_mode=register_and_fuse`、`pose_source=noisy_input`，且 `comm_range_gating!=auto`；否则直接判定不可引用。
1) **禁用 auto gating**：online_box 下必须 `--comm-range-gating clean|noisy`（禁止 auto）。
2) **stage1 结构**：`tools/validate_stage1_cache.py --stage1 <stage1_boxes.json>`
3) **stage1 语义（local frame）**：`tools/validate_stage1_semantics.py --stage1 <stage1_boxes.json> --prefer-head200 --num-samples 50`
4) **single 公平**：任何脚本不得为 single 设置 `comm_range_override=0`；single 必须来自 `--force-ego-input-only`。
5) **no-op gate**：对非 bounds 方法，`timing_stats[*].pose_timing.pose_provider_applied_count` 不能全为 0（否则视为无效曲线）。
6) **pose_override gate**：core benchmark 禁止使用 `pose_override.enabled=true`（尤其 `mode=zero` 会抵消 noise sweep）；除非你明确在跑 no-extr suite，并且单独成表。
7) **样本一致性 gate**：同一张表/同一条曲线的各方法必须保证 `timing_stats[*].samples` 一致（且与 split/max_eval_samples 一致）；否则属于“不同子集的数字”，不可比。

---

## 4) Dataset-specific freeze（允许不同，但必须“同数据集内一致”）

- **DAIR-V2X**：comm_range 推荐 100（vehicle-infra；保持与模型/数据设置一致）。
- **OPV2V**：comm_range 推荐 70（保持与模型/论文常用设置一致）。
- **V2V4Real**：在本代码库/现有 checkpoint（PASTAT）里，comm_range **默认/推荐就是 70**（与训练 hypes 一致）。
  - 训练 hypes 锚点：`HEAL/opencood/hypes_yaml/v2v4real/LiDAROnly/lidar_pastat_noise1.yaml:17`
  - runner 默认锚点：`tools/run_v2v4real_core_benchmark.py:393`
  - 如需跑 paper 常见的 200m：必须显式传 `--comm-range 200`，并在产物命名/表格里标注 `cr200`；同时注意这会改变 agent set/任务分布，且可能与现有 checkpoint 的训练设置不一致（建议作为附录 lane，不要与 `cr70` 混表）。

> 证据：强行统一 comm_range 会引入新 confound（距离分布耦合）；解释工具见 `docs/operations/dataset_comm_range_and_gating_analysis_20260228.md`。
>
> ⚠️ 易踩坑：V2V4Real 的 `cr70/cr200` 是“不同题目”（agent set/merged GT 分布不同），绝对禁止混表；需要同时跑时请明确拆成两条 lane（并在标题/文件名里写死 `cr70` 或 `cr200`）。

---

## 5) 推荐执行入口（10×3090 跑满 + 容错）

- OPV2V：`tools/opv2v_benchmark_autopilot.py`（smoke→full，自愈；产出 `run_state.jsonl/config_snapshot.json/plots_yaml`）
- DAIR：`tools/run_dair_core_benchmark.py`（统一 online 语义 + 出图）
- V2V4Real：`tools/run_v2v4real_core_benchmark.py` + `tools/summarize_v2v4real_core_from_yaml.py`

如果要一键：
- `tools/run_core_benchmark_pipeline.py --comm-range-gating clean|noisy`
