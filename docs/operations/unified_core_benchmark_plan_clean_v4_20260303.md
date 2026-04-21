# Unified Core Benchmark Plan (Clean v4): DAIR / OPV2V / V2V4Real

更新：2026-03-03

这份文档只做“执行合同”一件事：把 **core(no-init/no-prior)** benchmark 在 **DAIR / OPV2V / V2V4Real** 上按统一语义跑完，并且把 **资源跑满 + 容错续跑 + 产物可复核** 写死。

语义定义的 source-of-truth（不要再被旧切片带歪）：
- `docs/operations/benchmark_semantics.md`（single/oracle/online-offline/gating/noise 轴）
- `docs/operations/fair_core_benchmark_setting_v1_20260301.md`（core 方法集合 + 必过 gate）
- `docs/operations/benchmark_method_catalog.md`（core vs audit 方法宇宙与落脚点）

---

## 0) Goal / Decision / DoD（跑完能做什么结论）

**Goal**：在每个数据集内（DAIR / OPV2V / V2V4Real 各自独立）且每个 modality 内，公平比较 core(no-init/no-prior) 配准方法对下游协同感知 AP 的影响。

**Decision**（你最终要用它做什么决策）：
- core 方法在各数据集的排序/增益是否一致？是否存在“某法只在某数据集有效”的规律？
- single / oracle / baseline 的上下界是否合理（避免“变题导致 single>oracle”）？

**DoD（可引用）**：每个 dataset×modality×lane 必须同时满足：
- 语义冻结（§1）PASS
- gates（§5）PASS
- 产物齐全（Source-of-truth 以 SoT 文件为准，不以 png 为准；见 §7.1）：
  - DAIR / V2V4Real：`manifest.json` + `results_ap50_from_yaml.json` + `plots_yaml/*noise10*` + `summary.md`
  - OPV2V：`config_snapshot.json` + `results_ap50_from_yaml.json` + `plots_yaml/*noise10*` + `task_summary_final.json`（run_id 指针在 autopilot report）

---

## 1) 语义冻结（P0 红线；违反即 FAIL）

> 下列项必须写进命令/manifest/config_snapshot，禁止靠默认值/记忆。

- **runtime**：`--solver-backend online_box --runtime-mode register_and_fuse --pose-source noisy_input`
- **noise sweep**：paired sweep（pos_std 与 rot_std 同步），`pos_std_list=rot_std_list=0,1,...,10`；`--noise-target non-ego`
- **comm-range gating**：必须显式 `--comm-range-gating clean|noisy`（禁止 `auto`）
- **single（唯一可比）**：`single_ego_only = baseline + --force-ego-input-only`，只跑 noise=0，但出图画成水平线（禁止 `comm_range_override=0`）
- **oracle（命名必须精确）**：
  - canonical bound：`--pose-correction oracle_gt`（按当前实现应当严格平线）
  - 允许额外画：`v2vloc_oracle_*`（会保留注噪/裁剪抖动，曲线可能轻微漂移；必须在 legend 里显式叫这个名字）
- **禁止**：`offline_map` 作为 core 结论来源（只能做 parity/调试）

两条 lane（不要混在一张“主表”里）：
- **Lane-D（Diagnostic）**：`--comm-range-gating clean`（固定邻居集合，最可解释）
- **Lane-S（System）**：`--comm-range-gating noisy`（邻居集合随噪声抖动，更贴近系统）

---

## 2) 方法集合（core-first）

### 2.1 Bounds（必须有）
- `baseline`：`--pose-correction none`
- `single`：`--pose-correction none --force-ego-input-only`（仅 noise=0）
- `oracle_gt`：`--pose-correction oracle_gt`

### 2.2 Core（no-init / no-prior；必须全跑）
> method 名必须等于 `--pose-correction`（避免“看起来像跑了，实际不是同一方法”）。

- `v2xregpp_initfree`
- `freealign_paper`
- `vips_initfree`
- `cbm_initfree`

可选附录（不影响 core 主结论）：
- stable lane：`v2xregpp_stable / freealign_paper_stable / vips_stable / cbm_stable`
- with-init / audit 方法（Imagematch/LiDARReg/HKUST/...）：单独开 audit 合同，禁止混表

VIPS/CBM 公平性强制项：
- 禁止 `--vips-use-prior / --cbm-use-prior`（core 只做 no-init）
- pose 方向必须是 `(cav -> ego)`（已有回归测试：`tools/tests/test_stage1_vips_cbm_direction.py`）

---

## 3) 数据集输入契约（paths + comm_range）

### 3.1 DAIR-V2X（camera + lidar）
- runner：`tools/run_dair_core_benchmark.py`
- defaults（见脚本顶部常量）：
  - camera model：`HEAL/opencood/logs/HeterBaseline_DAIR_camera_v2xvit_2023_09_09_11_27_38`
  - lidar  model：`HEAL/opencood/logs/HeterBaseline_DAIR_lidar_v2xvit_2023_09_09_11_19_26`
  - camera stage1：`data/DAIR-V2X/detected/camera_v2xvit_stage1/stage1_boxes.json`
  - lidar stage1（per-CAV）：`data/DAIR-V2X/detected/lidar_v2xvit_stage1_percav/test/stage1_boxes.json`
- comm_range：`100`

### 3.2 OPV2V（camera + lidar）
- runner：`tools/opv2v_benchmark_autopilot.py`（smoke -> full；自愈 stage1；严格 applied gate）
- defaults（见 autopilot args 默认值）：
  - camera model：`HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope`
  - lidar  model：`HEAL/opencood/logs/freealign_repro_opv2v_baseline`
  - camera stage1（per-CAV）：`data/OPV2V/detected/opv2v_camera_v2xvit_stage1_percav/test/stage1_boxes.json`
  - lidar stage1：`data/OPV2V/detected/opv2v_lidar_v2xvit_stage1/test/stage1_boxes.json`
- comm_range：`70`

### 3.3 V2V4Real（本仓库现状：LiDAR only）
- runner：`tools/run_v2v4real_core_benchmark.py`
- defaults：
  - model：`HEAL/opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25`
  - stage1（per-CAV, canonical）：`HEAL/opencood/logs/v2v4real_stage1_pointpillar_from_pastat_bestval17_percav/test/stage1_boxes.json`
- comm_range：`70`（如需跑 `cr200` 必须单独成 lane，禁止与 `cr70` 混表）

---

## 4) 一键执行（10×3090 本机/无 slurm 依赖）

> 当前机器 `squeue` 无法连接 controller 时，优先用本地调度（脚本内部已经实现 GPU-slot 级并发 + 断点跳过完整 YAML）。

### 4.1 跑 Lane-D（推荐先跑，最稳定可解释）

```bash
./.micromamba/envs/py39/bin/python -u tools/run_core_benchmark_pipeline.py \
  --tag core_clean_v4_laneD_20260303 \
  --comm-range-gating clean \
  --dair-split-noise --v2v4real-split-noise \
  --dair-max-per-gpu 2 --opv2v-max-per-gpu 3 --v2v4real-max-per-gpu 2
```

### 4.2 跑 Lane-S（可选：更贴近系统）

```bash
./.micromamba/envs/py39/bin/python -u tools/run_core_benchmark_pipeline.py \
  --tag core_clean_v4_laneS_20260303 \
  --comm-range-gating noisy \
  --dair-split-noise --v2v4real-split-noise \
  --dair-max-per-gpu 2 --opv2v-max-per-gpu 3 --v2v4real-max-per-gpu 2
```

**util 提升建议（逐步加，不要盲目拉满）**：
- 若显存余量大：把 `--dair-max-per-gpu/--v2v4real-max-per-gpu` 从 2 提到 3（3090 上常见可行，但以 OOM 为准）
- 通过 `--split-noise` 把长 sweep 切成 11×方法的小任务，避免“某个长任务卡死导致整机空转”

---

## 5) Preflight + Gates（Fail-fast）

### 5.1 必跑 preflight（不通过就别跑 full）
- stage1 结构：`./.micromamba/envs/py39/bin/python tools/validate_stage1_cache.py --stage1 <stage1_boxes.json>`
- stage1 语义（local frame）：`./.micromamba/envs/py39/bin/python tools/validate_stage1_semantics.py --stage1 <stage1_boxes.json> --prefer-head200 --num-samples 50`
- single 合同：禁止 `comm_range_override=0`；single 必须来自 `--force-ego-input-only`

### 5.2 运行后 gates（可引用判定）
- **samples 一致**：同一张图/表里，各方法的 `timing_stats[*].samples` 必须一致
- **non-noop**：core 方法 `pose_provider_applied_count` 不能全为 0（否则视为 no-op）
- **oracle_gt 平线**：若 `oracle_gt` 明显随噪声漂移，优先判定“混语义/未走 gt 禁噪分支”，不要硬解释
- **plot hygiene**：出图必须用 `--clean-plot-dir`（避免 stale 的 `noise4` 残留误导）
- **OPV2V autopilot 验收**：`docs/operations/opv2v_autopilot_report_<tag>.md` 必须 `status: success`，且 `outputs/full_bench_<full_run_id>/task_summary_final.json` 里 `final_failed_tasks=0 && final_missing_tasks=0`
- **baseline 形状验收（防“噪声没生效”）**：baseline 在 noise=0 与 noise=max 的 AP50 差值应明显（建议 |Δ|>=0.005；smoke 可放宽到 0.003；与 autopilot gate 对齐）
- **oracle_gt 上界验收（防 single>oracle / 命名混乱）**：noise=0 处 `oracle_gt >= baseline - 1e-3`；否则按语义错判 FAIL

---

## 6) 容错/续跑（最少人工）

- DAIR / V2V4Real：rerun 同一个 `--tag` 会跳过“已完整写入的 final YAML”（resume-friendly）。
- OPV2V：resume 的最小单位是 `--run-id`（`outputs/full_bench_<run_id>/run_state.jsonl`）；重跑 autopilot 会创建新的 attempt run_id（不等价于 resume）。
- OPV2V autopilot：`outputs/opv2v_autopilot_<tag>/autopilot.log` 会记录 smoke/full 的 run_id；full 的 source-of-truth 在 `outputs/full_bench_<full_run_id>/`。
- 若你只想重出图：直接跑 summarizer，并带 `--clean-plot-dir`：
  - V2V4Real/DAIR：`tools/summarize_v2v4real_core_from_yaml.py --run-dir <run_dir> --clean-plot-dir`
  - OPV2V：`tools/summarize_opv2v_fullbench_from_yaml.py --run-dir <full_bench_run_dir>`

### 6.1 Stop-loss / Budget（P0；触发任一条立刻停）

- 只允许“同 tag 续跑”用于 **完全相同语义** 的 resume；任何语义项变更（§1 红线、comm_range、stage1、checkpoint、compare-current pins）=> 必须换新 tag（否则会吃旧 YAML/旧图，直接变题）。
- OPV2V autopilot：smoke/full 任一阶段在 `--max-*-retries`（默认 2）仍失败 => STOP（不要无限重试）。
- `outputs/core_pipeline_<tag>/SUMMARY.md` 出现任一 failure => STOP；`--allow-incomplete` 生成的 plots 仅供 debug，不计入 DoD/验收。
- DAIR / V2V4Real precheck 报 `comm_range mismatch` 或 `pose_override.enabled=true` => STOP（除非你明确在做 ablation，并单独 lane/tag）。

---

## 7) 产物在哪看（source-of-truth）

每次 pipeline run 会生成：
- `outputs/core_pipeline_<tag>/SUMMARY.md`（一眼看成功/失败 + 关键目录）
- `outputs/dair_core_<tag>/`（每个 modality 一个子目录 + `plots_yaml/`）
- `outputs/opv2v_autopilot_<tag>/`（autopilot 日志 + 报告 md；fullbench run_id 在 report 里）
- `outputs/v2v4real_core_<tag>/`（`manifest.json` + `results.jsonl` + `results_ap50_from_yaml.json` + `plots_yaml/`）

### 7.1 SoT（完成/正确性以这些文件为准；不要以 png 为准）

- Pipeline 完成状态 SoT：`outputs/core_pipeline_<tag>/SUMMARY.md`
- DAIR SoT（每个 modality 各一份）：
  - 数字 SoT：`outputs/dair_core_<tag>/<modality>/results_ap50_from_yaml.json`
  - 语义/输入 SoT：`outputs/dair_core_<tag>/<modality>/manifest.json`
- V2V4Real SoT：
  - 数字 SoT：`outputs/v2v4real_core_<tag>/results_ap50_from_yaml.json`
  - 语义/输入 SoT：`outputs/v2v4real_core_<tag>/manifest.json`
- OPV2V SoT（注意：autopilot 目录不是数字 SoT）：
  - run_id 指针 SoT：`docs/operations/opv2v_autopilot_report_<tag>.md`
  - 数字 SoT：`outputs/full_bench_<full_run_id>/results_ap50_from_yaml.json`
  - 语义/输入 SoT：`outputs/full_bench_<full_run_id>/config_snapshot.json`
  - 完成/缺失任务 SoT：`outputs/full_bench_<full_run_id>/task_summary_final.json` + `run_state.jsonl`

---

## 8) Slurm（可选）：推荐“单 allocation + 本地调度器”

当 slurm controller 可用时，不推荐把 200+ 小任务全丢给 slurm array；更稳的是：
- `sbatch` 申请 `gpu:10` 的一个 job
- job 内直接跑 §4 的 pipeline（行为与本机一致；不依赖 `squeue`）

---

## 9) 备注（防止再被历史资产误导）

- 你看到的 “single > oracle” 基本只可能来自两类问题：
  1) 把 `comm_range_override=0` 当 single（变题：merged GT 变少）
  2) 把 `v2vloc_oracle_*` 叫成 “oracle_gt”（实现不同，曲线不必平）
  对应证据链与复现路径见：`docs/operations/benchmark_semantics.md`。

- V2V4Real 旧 run_dir 里可能残留 `noise4_*.png`（历史 sweep=0..4），必须用 `--clean-plot-dir` 清理再看；否则会误以为“噪声范围不一致”。
