# Unified Core Benchmark Execution Plan v1 (DAIR / OPV2V / V2V4Real)

更新：2026-02-26

目标：在 **DAIR / OPV2V / V2V4Real**（以及未来新增数据集）上，用同一套“输入语义 + runtime 语义冻结 + fail-fast gate”跑出 **core(no-init/no-prior)** 的可比曲线与表格；并确保 **资源尽量跑满、出错可恢复、不会因为合同漂移/语义错题而“跑完才发现白跑”**。

> WARNING（2026-03-01）：本文是 v1 执行计划，早于当前“语义冻结”版本。  
> - `single(comm=0)` 属于 legacy，会改变 agent/GT set，导致“变题”；canonical single 是 `single_ego_only=--force-ego-input-only`（noise=0）。  
> - online benchmark 必须显式 pin `--comm-range-gating clean|noisy`（禁止 auto）。  
> 统一以 `docs/operations/benchmark_semantics.md` 为准。

---

## 1) 方法集合：Core vs Audit（本 plan 只跑 Core）

### 1.1 Core（无初值 / no prior）

统一在下游 AP 评测里对比（`inference_w_noise.py`）：

- bounds：
  - `baseline`: `--pose-correction none`
  - `oracle`: `--pose-correction oracle_gt`（用 clean pose 覆盖 noisy）
  - `single_ego_only`: `--pose-correction none --force-ego-input-only`（只跑 noise=0；保持 comm_range/merged GT 不变）
- core(initfree)：
  - `v2xregpp_initfree`
  - `freealign_paper`
  - `vips_initfree`
  - `cbm_initfree`

建议统一加：`--pose-compare-current`（避免 noise=0 时“估到 identity 还被错误 apply”的风险；并且与 OPV2V fullbench 一致）。

### 1.2 Audit（不在 core 主表里；后续单独做）

- with-init：`vips_prior / cbm_prior`（仅在 init_pose 误差很小 or 丢失场景下做对照）
- raw payload：`imagematch_*`、`lidarreg_* / hkust_*`（必须先过 no-op gate）

---

## 2) 统一合同（Semantics Freeze）

跨数据集/方法统一冻结（核心是“别换题”）：

- `--fusion_method intermediate`
- `--sweep-mode paired`
- `--noise-target non-ego`
- `--num-workers 0`
- `--pose-timing`
- online runtime（**core 统一对比必须**）：
  - `--solver-backend online_box`
  - `--runtime-mode register_and_fuse`
- `--pose-source noisy_input`
- `--comm-range-gating noisy`（禁止 `auto`）
- pose solver device：`--pose-device cuda`

数据集维度允许不同但必须 **在同一数据集内一致**：
- `--comm-range-override`（DAIR 历史为 100；OPV2V 多数走 model cfg；V2V4Real 目前按 200）
- noise axis（canonical）：`pos_std_list=rot_std_list=0..10`（如果历史 run 没跑 0 或只跑 0..4，必须标注为 legacy/partial）

---

## 3) Fail-fast Gates（跑 full 之前必须过）

### 3.1 stage1 cache 结构 gate（硬门槛）

工具：`tools/validate_stage1_cache.py`

要求：
- JSON dict（key=sample_idx str）
- `cav_id_list / pred_corner3d_np_list / lidar_pose_clean_np` 三者齐全且长度一致
-（推荐）key 连续：`0..N-1`

### 3.2 stage1 cache 语义 gate（硬门槛，决定“是不是同一道题”）

工具：`tools/validate_stage1_semantics.py`

核心判据：对 sampled entries 比较
`matched(identity)` vs `matched(rel_clean)`。

- 若大量出现 `identity > rel_clean` 且总体 ratio<阈值 → **boxes 已在 common frame** → 对 box-based pose solver 致命（会出现 single>oracle / noise=0 巨大 rel_error 等异常）。

### 3.3 online/no-op gate（软门槛，但强烈建议）

看 `timing_stats[*].pose_timing.pose_provider_applied_count`：
- 对 core 方法（非 bounds）应当 **>0**（否则就是 no-op，AP 会“看起来跑了但其实没生效”）。

> 该信号在 offline_map/旧链路里可能缺失；所以 core 统一对比建议都走 online_box。

---

## 4) 数据集落地（当前 repo 的“可执行入口”）

### 4.1 OPV2V（已完成 canonical fullbench）

- Source-of-truth run_dir：
  - `outputs/full_bench_opv2v_autopilot_full_fixv2xregpp_20260225_065926_a1/`
  - 完整性：`run_state.jsonl`（404/404 end_code=0）
  - 语义冻结：`config_snapshot.json`
- 证据文档：
  - `docs/operations/opv2v_fullbench_evidence_autopilot_fixv2xregpp_20260225_065926.md`

（以后要重跑：用 `tools/run_opv2v_fullbench_fast.py`，并保持 `--comm-range-gating noisy` + stage1 semantic gate 开启。）

### 4.2 DAIR（已有全量 sweep，但 schema 偏旧；建议后续按 online 合同补一版）

已有结果：
- `outputs/pose_sweep_1to10_full_gpuvoxel20260218_results.jsonl`

现状问题（影响“统一合同”）：
- YAML 里缺少 online pose_provider 的 applied_count 等信号（难以做 no-op gate）。

建议（待办）：
- 按第 2 节合同，用 `inference_w_noise.py` 的 online_box 跑一版 DAIR core（生成 manifest + 新 YAML schema）。

### 4.3 V2V4Real（必须先修 stage1：per-CAV local-frame）

现状：
- 旧 stage1（`..._80boxes/test/stage1_boxes.json`）语义 FAIL（common frame）→ 旧 core 结果 **不可信**。
- 证据链见：`docs/operations/core_benchmark_unified_standard_v1_20260226.md`。

必须动作：导出 per-CAV stage1（sharded + merge + gate）。

---

## 5) 执行步骤（按优先级，保证“跑得快且不白跑”）

### Step A：停掉 watchdog（避免后台任务抢资源/污染日志）

我已在本机停掉以下长期 watch 进程：
- `HEAL/opencood/tools/pgc_quick_eval_watch.py`
- `opencood/tools/live_train_status.py`

你可用以下命令复查：
```bash
pgrep -af "pgc_quick_eval_watch.py|live_train_status.py" || true
```

### Step B：导出 V2V4Real per-CAV stage1（10 shards x 10 GPUs）

一键脚本（已落地，带 merge + head200 + gate）：
- `tools/run_v2v4real_stage1_export_per_cav.py`

建议直接跑满 10 卡：
```bash
./.micromamba/envs/py39/bin/python -u tools/run_v2v4real_stage1_export_per_cav.py \
  --tag v2v4real_percav_stage1_$(date +%Y%m%d_%H%M%S) \
  --gpus 0,1,2,3,4,5,6,7,8,9 \
  --num-shards 10 \
  --skip-existing-shards
```

产物：
- merged stage1：`HEAL/opencood/logs/v2v4real_stage1_pointpillar_from_pastat_bestval17_percav/test/stage1_boxes.json`
- head200：同目录 `stage1_boxes_head200.json`
- 可追溯 run_dir：`outputs/v2v4real_stage1_export_<tag>/`

### Step C：跑 V2V4Real core benchmark（online 合同 + 高利用率）

跑 core（可选 `--split-noise` + `--max-per-gpu 2/3` 提升利用率）：
```bash
./.micromamba/envs/py39/bin/python -u tools/run_v2v4real_core_benchmark.py \
  --tag v2v4real_core_$(date +%Y%m%d_%H%M%S) \
  --gpus 0,1,2,3,4,5,6,7,8,9 \
  --max-per-gpu 2 \
  --split-noise \
  --suite core_plus_stable \
  --stage1-result opencood/logs/v2v4real_stage1_pointpillar_from_pastat_bestval17_percav/test/stage1_boxes.json
```

说明：
- `--max-per-gpu>1` 是为了吃满 CPU（AP 评测 IoU 很吃 CPU，单进程 GPU 会空）。
- `--split-noise` 把 5 个噪声点拆成独立 job，更容易把 10 卡跑满。

### Step D：生成“与 OPV2V 同风格”的曲线图 + 长表 JSON（V2V4Real）

```bash
./.micromamba/envs/py39/bin/python -u tools/summarize_v2v4real_core_from_yaml.py \
  --run-dir outputs/v2v4real_core_<tag>
```

产物：
- `outputs/v2v4real_core_<tag>/results_ap50_from_yaml.json`
- `outputs/v2v4real_core_<tag>/plots_yaml/noise4_lidar_ap50.png`（以及 AP30/AP70）

### Step E（可选）：补一版 DAIR online core（让三数据集 schema 一致）

建议在 V2V4Real 稳定后再做（避免并行把问题叠在一起）。

---

## 6) CPU / GPU 分工（为什么“看起来利用率低”，怎么提高）

- GPU 主要负责：网络 forward、部分 voxelization、online pose solver（若启用 cuda）。
- CPU 主要负责：AP 评测（IoU/多边形运算，通常是瓶颈）。

因此：
- “一张卡一个进程”常见现象是 **GPU 空、CPU 单核满**；
- 最稳的加速方式是：`--max-per-gpu` 多进程 + `--split-noise` 拆任务；
- 同时把 `OMP_NUM_THREADS/MKL/OPENBLAS/NUMEXPR=1`（runner 已默认设置）避免线程互抢。

---

## 7) 成功判据（跑完立刻能自证“结果正常”）

V2V4Real 修复后你应该看到：
- stage1 semantic gate：`inverted_rate` 明显下降且 `ratio_rel_over_id` > 1（至少不应 < 0.95）
- bounds：`oracle` ≥ `baseline`（所有噪声点都成立）
- 单车：`single` 不应长期优于 `oracle`
- core 方法：`pose_provider_applied_count` 不是全 0（否则是 no-op）

---

## 8) Slurm（现状与建议）

当前机器上 `sinfo` 报：
`slurm_load_partitions: Unable to contact slurm controller (connect failure)`，
因此本计划默认 **不依赖 Slurm**，用本机并行脚本跑满 10 卡。

如果你切到能正常连 slurm controller 的节点，再把 Step B/C 的每个 shard/job 换成 `sbatch` 队列即可（原则不变：shard 化 + fail-fast gate + 可恢复）。
