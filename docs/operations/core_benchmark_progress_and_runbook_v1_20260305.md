# Core Benchmark：当前进度 + 统一执行 Runbook（DAIR / OPV2V / V2V4Real）

更新：2026-03-05

本文件只解决两件事（按你的诉求写）：
1) **现在有效的 benchmark 到底是什么样**（哪些结果可引用、口径是什么、产物在哪）
2) **还差什么 & 接下来怎么做**（为了“统一/公平/有证据链”的最小闭环，怎么继续跑且尽量跑满 10×3090）

统一执行/引用规范（更短更“可执行”的版本）已单独收口为：
- `docs/operations/core_benchmark_runbook_v1_20260305.md`

---

## 0) 机器/调度现状（避免沟通错位）

- 当前这台 10×3090 机器上 **Slurm 已安装但未启用**（`slurmctld/slurmd` inactive），因此本仓库现阶段的“自动流水线”主要依赖：
  - `tools/run_*_core_benchmark.py` 这类 **多 GPU 本地调度器**（线程池 + 每 GPU 多进程并发）
  - `tools/opv2v_benchmark_autopilot.py` 的 **smoke->full + retry** 逻辑
  - `tools/run_core_benchmark_pipeline.py` 的 **串联 pipeline**（DAIR -> OPV2V -> V2V4Real）
- 如果你后续要用 Slurm：需要先把系统服务跑起来并确认 controller 可用；否则 `squeue` 会报 `Unable to contact slurm controller`。

---

## 1) “有效 benchmark”的统一口径（必须遵守；否则=变题）

本仓库现在把 **core benchmark** 定义为：

- **只比 core methods（无初值 / no-init / no-prior）**：
  - `v2xregpp_initfree / freealign_paper / vips_initfree / cbm_initfree`
  - bounds：`baseline(none) / single(single_ego_only) / oracle_gt`
- **统一下游评估**：检测 AP（AP30/50/70），主看 AP50 曲线；`rel_error_stats` 仅作旁证。
- **统一在线语义**（否则 online/offline 混了会出现“看起来合理但其实不同题”）：
  - `--solver-backend online_box`
  - `--runtime-mode register_and_fuse`
  - `--pose-source noisy_input`
- **统一 noise 轴**：
  - paired sweep：`pos_std_list = rot_std_list = 0..10`（离散点 `0,1,...,10`）
  - `--noise-target non-ego`
- **single 的唯一合法定义**：
  - `single = baseline + --force-ego-input-only`（保持 comm_range / merged GT set 不变）
  - single **只跑 noise=0**，出图画成水平线
  - 禁止 legacy `comm_range_override=0` 当 single（会改变 agent/GT set，能直接制造 `single > oracle` 假象）
- **oracle 必须具体化**：
  - core benchmark 里统一用 `oracle_gt`（dataset clean pose，理论上应平线）
  - 只写 “oracle” 属于不合格产物（会混 `v2vloc_oracle_*` 等）
- **comm-range gating 必须显式 pin**（禁止 auto）：
  - Track-D（诊断/公平）：`--comm-range-gating clean`（邻居集合不随噪声抖）
  - Track-S（系统/真实）：`--comm-range-gating noisy`（邻居集合会随噪声抖）

上面这套口径的 canonical 合同（最权威 source-of-truth）：
- `docs/operations/unified_core_benchmark_master_spec_results_v1_20260302.md`

---

## 2) 现有三数据集 core 结果（已跑完，可复盘/可引用）

### 2.1 DAIR-V2X（camera + lidar）
- run_dir：
  - `outputs/dair_core_core_clean_v4_laneD_20260303_run1/camera/`
  - `outputs/dair_core_core_clean_v4_laneD_20260303_run1/lidar/`
- 产物：`manifest.json` / `results_ap50_from_yaml.json` / `plots_yaml/*.png` / `summary.md`

DAIR mean AP50（来自各自 summary.md）：
- lidar：`oracle_gt(0.4836) > baseline(0.3504) ~= single_ego_only(0.3413) > vips_initfree(0.3286) > freealign_paper(0.2891) > v2xregpp_initfree(0.2724) > cbm_initfree(0.2256)`
- camera：整体数值很低（stage1/模型链路本身弱），但排序可用于“是否变题/是否 no-op”的 sanity check。

### 2.2 V2V4Real（当前只有 lidar lane）
- run_dir：`outputs/v2v4real_core_core_clean_v4_laneD_20260303_run1/`
- 产物：`manifest.json` / `results_ap50_from_yaml.json` / `plots_yaml/*.png` / `summary.md`

V2V4Real mean AP50：
- `oracle_gt(0.5793) > v2xregpp_initfree(0.5711) > freealign_paper(0.5685) ~= cbm_initfree(0.5676) > vips_initfree(0.5647) ~= baseline(0.5632) > single_ego_only(0.5495)`

### 2.3 OPV2V（fullbench：camera + lidar；含 noise10 + drop20）
- run_dir：`outputs/full_bench_opv2v_autopilot_full_core_clean_v4_laneD_20260303_run1_a1/`
- 产物：`config_snapshot.json` / `run_state.jsonl` / `results_ap50_from_yaml.json` / `plots_yaml/*.png` / `summary.md`
- 完成性：`task_summary_final.json` 显示 `final_done_tasks=444, final_failed_tasks=0`
- 注：OPV2V 的 `plots_yaml/` 已更新为与 DAIR/V2V4Real 一致的出图规范（固定 `ylim=[0,1]`、显式 `xticks`、支持 `--clean-plot-dir` 防止旧图残留）。

---

## 3) 已经定位并纠正过的“坑”（为什么你会看到怪现象）

### 3.1 为什么会出现 `single > oracle`？
根因不是方法真变强，而是 **single 定义变题**：
- legacy single 用 `comm_range_override=0` 会改变可融合 agent 集合，进而改变 merged GT set（任务难度变了）
- 这时把 “single(comm0)” 和 “oracle(comm>0)” 画在一起，会产生看似反直觉的比较

当前 canonical 已强制 single=ego-only（保持 comm_range/GT 不变），因此这类假象不再成立。

### 3.2 为什么 V2V4Real 早期看起来“曲线都一样/oracle 不平/趋势怪”？
核心是两个 confound：
1) **head 子集偏置**：V2V4Real 在 `comm_range=70 + gating=clean` 下，前缀样本（例如 head200）可能几乎全是单车（record_len=1），导致所有方法退化到同一题（看起来曲线一样）。  
   - 解决：使用 `--eval-sample-start 294` 跳过 out-of-range 前缀（证据链见 gating 文档）
2) **compare-current gate 未 pin**：只传 `--pose-compare-current` 不 pin 阈值会导致 noise=0 也大量 apply（bad-apply），表现为 oracle/方法线不稳定或非平线。

对应证据链（代码+对照实验）：
- `docs/operations/comm_range_gating_cbm_sensitivity_evidence_20260304.md`
- `docs/operations/unified_core_benchmark_master_spec_results_v1_20260302.md`（§5 compare-current）

### 3.3 `comm-range-gating clean vs noisy` 为何会显著影响 CBM/VIPS（以及为何有时看起来又不影响）？
一句话：gating 会改变 **输入 agent set + merged GT set**，而 CBM/VIPS 对“是否存在可匹配 box”极敏感；如果还叠加 head 子集偏置/compare gate 未 pin，就会被放大成“巨大差异”。  
在严格控制变量的对照里（唯一差别=gating），OPV2V/V2V4Real 的 AP 差异其实很小（见证据链文档）。

---

## 4) 还差什么（最小闭环缺口）

### P0-1：召回率低 / 方法“看似失效”的根因缺硬统计（需要 reason breakdown）
现状：我们有 `pose_provider_applied_count`（是否 apply），但缺 “为什么没 apply/为什么失败” 的可量化分解。

本次已落地的修复（代码已加）：
- online pose provider 会把 stage1 corrector 的 `last_stats`（empty/no_match/svd_failed/compare_gate/exception/other）以 `pose_corr_*_count` 形式写进 `pose_timing`  
  - 代码：`HEAL/opencood/utils/pose_provider_runtime.py`

还需要补的（run 级产物）：
- 在 DAIR/OPV2V/V2V4Real 各跑 1 个 smoke（例如 noise=0..10，max_eval_samples=200），并在 `results_ap50_from_yaml.json`/summary 里汇总这些字段，形成“失败原因占比”的表格。

### P0-2：V2V4Real camera lane 仍缺（如果你的统一公平标准要求 camera+lidar 都齐）
两条路二选一（需要你确认优先级/预算）：
1) 找到现成可用的 V2V4Real camera checkpoint（优先 v2xvit，和 DAIR/OPV2V 形态更一致），跑同口径 core；
2) 训练一个最小可复现的 v2xvit camera + lidar 模型，然后跑 core（工程量/时间更大，但跨数据集“网络形态一致”的公平性更强）。

---

## 5) 统一执行 Runbook（怎么“尽快且不出错地跑完”）

### 5.1 开跑前 Preflight（必须做；否则=浪费算力）
- stage1 cache 结构/语义校验（避免 frame convention 错导致“配准方向反了”）：
  - `tools/validate_stage1_cache.py`
  - `tools/validate_stage1_semantics.py`
- checkpoint config gate：
  - comm_range mismatch（训练配置 vs override）必须显式允许
  - 禁止 `pose_override.enabled=true` 混入 core（会取消 noise 轴）
- 固定 compare-current pins（best-state）并写入 manifest/config_snapshot

### 5.2 建议的跑法（本地 10×3090）
推荐直接跑 pipeline（串联 + 容错）：

```bash
.micromamba/envs/py39/bin/python -u tools/run_core_benchmark_pipeline.py \
  --tag core_clean_v4_laneD_$(date +%Y%m%d_%H%M%S) \
  --gpus 0,1,2,3,4,5,6,7,8,9 \
  --comm-range-gating clean \
  --dair-max-per-gpu 2 \
  --opv2v-max-per-gpu 3 \
  --v2v4real-max-per-gpu 2
```

想进一步“吃满 CPU/GPU”时，优先调这两个旋钮（注意显存/IO）：
- `--max-per-gpu`（每张卡并发子进程数；最有效的利用率拉升手段）
- `--split-noise`（把每个 noise 点拆成独立 job，提高并行度；但会产生更多 YAML shard，需要 merge）

### 5.3 出图/产物验收（DoD）
每个 run_dir 必须齐全：
- `manifest.json` 或 `config_snapshot.json`
- `results_ap50_from_yaml.json`
- `plots_yaml/*.png`（且 plot-dir clean，无旧图残留）
- `summary.md`

硬 gate（FAIL=不可引用）：
- single 必须是 `--force-ego-input-only`（且只跑 noise=0）
- oracle 必须是 `oracle_gt` 且应平线
- comm-range-gating 必须显式为 clean/noisy（禁止 auto）
- 同一 noise 点各方法 `samples` 一致（非 single）

---

## 6) 本文件之后的“下一步”清单（按优先级）

1) **补 P0-1 的 smoke 统计与汇总表**（DAIR/OPV2V/V2V4Real 各 200 样本）：把 `pose_corr_skip_*_count` 汇总到可读表格并写进各 run 的 `summary.md`（证据链闭环）
2) 如果你坚持“跨数据集网络形态一致（v2xvit）”：启动 V2V4Real v2xvit camera+lidar 的 checkpoint 寻找/训练计划（单开 lane，不污染当前已跑 core）
