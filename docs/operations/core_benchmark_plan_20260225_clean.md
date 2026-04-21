# Core Benchmark (DAIR / OPV2V / V2V4Real) — Clean Plan + Status (2026-02-25)

这份文档只回答三件事：
1) **现在有效/可引用的 core benchmark 到底是什么**（source-of-truth 在哪）；
2) **为什么会出现 single > cooperative**（是否是 bug / 是否可比）；
3) **接下来怎么把 DAIR/OPV2V/V2V4Real 的 core 方法都规范、公平、尽快地跑完**（含资源吃满与容错）。

> 说明：Slurm 在本机不可用（`sinfo` 无法连接 controller），所以本轮用 **tmux + 本地调度脚本** 做“自动流水线”。

---

## 1) Core 方法与 Audit 方法（本轮只交付 core）

### 1.1 Core methods（no-init / no-prior）
- `v2xregpp`（`initfree` + `stable`）
- `freealign`（`initfree` + `stable`）
- `vips`（`initfree` + `stable`；**不使用 prior**）
- `cbm`（`initfree` + `stable`；**不使用 prior**）

Bounds（用于解释现象/上界下界）：
- `baseline`：`pose_correction=none`
- `oracle`：`pose_correction=oracle_gt`（GT 外参上界）
- `single_ego_only`（canonical single）：`--force-ego-input-only`（只跑 noise=0；保持 comm_range/merged GT 不变）  
  > 禁止再用 legacy `comm_range_override=0(single_comm0)` 当作 single（会改变 agent/GT set，导致“变题”；证据见 `docs/operations/benchmark_semantics.md`）。

### 1.2 Audit（后续再做，不进入本轮 core-first 交付）
- `vips_prior / cbm_prior`
- `v2xregpp_occhint / occ_pose / 其它 ablation`
- `imagematch / lidar_reg / HKUST(teaser/quatro/fgr) ...`
- Table3 / 纯配准 benchmark 的耗时与口径复核

---

## 2) 现状：哪些结果已经“有效/可引用”（以及 source-of-truth）

### 2.1 DAIR-V2X（已完成；core methods 已齐）
- Source-of-truth：`outputs/pose_sweep_1to10_full_gpuvoxel20260218_results.jsonl`
- 该 jsonl 每行包含：方法标识 + 对应 YAML 路径 + mean(AP/rel_error/timing)。

> 备注：DAIR 这条链路目前是 offline_map sweep（不是 OPV2V 那种 online_box fullbench 调度形态）。若你后面要“完全统一成同一类调度合同”，再单独开工，不影响 core 数值是否存在。

### 2.2 OPV2V（已完成；本轮 core 的 canonical run）
- run_id：`opv2v_autopilot_full_fixv2xregpp_20260225_065926_a1`
- run_dir：`outputs/full_bench_opv2v_autopilot_full_fixv2xregpp_20260225_065926_a1/`
- 完成度（source-of-truth）：`run_state.jsonl` 显示 **404/404 tasks done, 0 failed**
- 汇总结果（长表）：`outputs/full_bench_opv2v_autopilot_full_fixv2xregpp_20260225_065926_a1/results_ap50_from_yaml.json`
- 证据审计：`docs/operations/opv2v_fullbench_evidence_autopilot_fixv2xregpp_20260225_065926.md`
- 配置快照（证明 core/no-prior & 语义冻结）：`config_snapshot.json`（methods=`v2xregpp,freealign,vips,cbm`；`solver_backend=online_box`；`comm_range_gating=noisy`）

OPV2V core 方法的整体效果（AP50，mean over noise=1..10）：
- **LiDAR / noise10**：oracle 0.959；v2xregpp(best) 0.934；freealign(best) 0.840；baseline 0.431
- **Camera / noise10**：oracle 0.302；v2xregpp(best) 0.111；baseline 0.106

### 2.3 V2V4Real（老结果不采信；已启动重跑）
- 历史输出：`outputs/v2v4real_core_20260225_034525/`（仅作历史参考；该批次与当前 core 合同不一致）
- 本轮重跑（正在跑）：`outputs/v2v4real_core_20260225_192705_corefix/`
  - manifest：`outputs/v2v4real_core_20260225_192705_corefix/manifest.json`（共 50 jobs：core_plus_stable × noise(0..4) split）
  - per-job logs：`outputs/v2v4real_core_20260225_192705_corefix/logs/*.log`
  - tmux session：`v2v4real_core_20260225_192705_corefix`

---

## 3) 为什么你可能看到 “single > cooperative / single > oracle”（不是 bug，但通常是“变题”）

先把结论写死：在当前 frozen 合同里，如果你看到 `single_ego_only > oracle_gt`，优先按 **语义错题/混语义** 处理（不是“方法突然很强”）。

历史上出现 “single 更好” 的最常见根因有两个（都有硬证据）：

1) **legacy single_comm0（comm_range_override=0）导致“变题”**：dataset pruning 改了 agent set 与 merged GT set，任务变容易，AP 会虚高，甚至可能出现 `single > oracle`。  
   证据与复现：`docs/operations/benchmark_semantics.md#11-禁止single_comm0legacy`（含 OPV2V/DAIR/V2V4Real 的 GT count 与 AP 对照）。

2) **把 single 的 noise=0 和 cooperative 的 noise=10 混着比**：这不是同一难度点；要比也必须对齐噪声点（例如都看 noise=0，或都看 noise=10）。

因此当前推荐的 single 规范只有一个：`single_ego_only`（`--force-ego-input-only`，noise=0），并且只作为 **bounds**（下界/参考线），不要再用 `comm_range_override=0` 画“单车曲线”。

---

## 4) 资源与速度：CPU/GPU 分工、为什么利用率看起来会低、怎么吃满

- GPU：网络 forward +（已启用）GPU voxelization。
- CPU：后处理/NMS + AP 评估（常见瓶颈，单进程往往把 GPU“饿住”）。

提升吞吐的稳定做法：
- **多进程并发（max-per-gpu>1）**：同一 GPU 跑多个独立 job，把 CPU 评估阶段的空档填满。
- **split-noise**：把一个方法的多噪声点拆成多个 job（更细粒度调度、更容易吃满）。
- 每进程固定 `OMP/MKL/OPENBLAS/NUMEXPR=1`，避免线程争用。

---

## 5) 后处理与统一对比（等 V2V4Real 跑完就做）

当 `outputs/v2v4real_core_20260225_192705_corefix/` 完成后，我会补一份“三数据集 core 对比表”（Markdown + CSV），最少包含：
- 每数据集（/modality）下：AP50 vs noise 的曲线（baseline/oracle/core methods）
- 同步给出：`rel_error_stats`（配准误差）与 `timing_stats`（耗时/fps）
- 明确标注：哪些点属于 bounds（single/oracle），哪些属于可比 core
