# Unified Core Benchmark Execution Plan v3 (DAIR / OPV2V / V2V4Real)

更新：2026-03-01

本计划只解决一件事：在 **语义冻结** 的前提下，把 core(no-init/no-prior) 方法在 DAIR / OPV2V / V2V4Real 上跑成 **可复核、可追责、可复跑** 的 benchmark curves（并且尽量把 10x3090 + CPU 跑满）。

依赖的“题目定义/合同”：
- `docs/operations/benchmark_semantics.md`（single/oracle/comm-range gating/online vs offline 的语义合同）
- `docs/operations/fair_core_benchmark_setting_v1_20260301.md`（两条 lane + 必过 gate）

---

## 0) 交付物（Definition of Done）

对每个数据集 *每条 lane*（见下）交付：
- 1) 每个 method 的 `AP030507_*.yaml`（完整曲线；single 只有 noise=0 但会画成平线）
- 2) `outputs/<run_dir>/manifest.json`（DAIR/V2V4Real core）或 `config_snapshot.json`（OPV2V fullbench）：必须包含语义冻结项（fusion/online/offline/comm_range/comm_range_gating/noise_axis/num_workers 以及 compare-current gate pins）
- 3) `results_ap50_from_yaml.json`（长格式点；作为审计入口）
- 4) `summary.md`（必须显式写出 gates PASS/FAIL + compare-current gate pins）
- 3) `plots_yaml/*.png`（AP30/50/70：全量 [0,1] 版 + core zoom 版）
- 4) gates 全部 PASS（样本一致性、no-op、single/oracle 语义等）

Done 不是“跑完了”，而是上述产物齐全且 gates 通过。

---

## 1) 统一语义（必须写死，不可漂移）

### 1.1 两条 lane（禁止混表）

- **Track-D (Diagnostic / 更公平可解释)**：`online_box + comm-range-gating=clean`
- **Track-S (System / 更真实)**：`online_box + comm-range-gating=noisy`

两条 lane **共同冻结项**：
- `fusion_method=intermediate`
- `solver_backend=online_box`
- `runtime_mode=register_and_fuse`
- `pose_source=noisy_input`
- `sweep_mode=paired`，`noise_target=non-ego`
- `pos_std_list=rot_std_list=0,1,2,3,4,5,6,7,8,9,10`
- `num_workers=0`
- **best-state(compare-current) 冻结（P0）**：
  - core(initfree) 线必须带 `--pose-compare-current`（best = compare-current best-state）
  - compare gate 必须显式 pin（并写入 manifest/config_snapshot 以便审计/复现）：
    - `--pose-min-precision-improvement <PIN>`
    - `--pose-min-matched-improvement <PIN>`
    - `--pose-current-precision-threshold <PIN>`（`-1`=禁用该 gate；否则按数据集校准后 pin）
    - （建议同时 pin）`--pose-compare-distance-threshold 3.0`
  - 推荐的“第一版统一 pin”（后续若某数据集 noise=0 安全 gate 不过，再做校准）：\n    `--pose-current-precision-threshold 1.8 --pose-min-precision-improvement 0.0 --pose-min-matched-improvement 0`
- bounds：
  - baseline：`--pose-correction none`
  - **single_ego_only（唯一可比 single）**：`--force-ego-input-only`（只跑 noise=0；画图为水平线；严禁 `comm_range=0`）
  - oracle：`--pose-correction oracle_gt`（按当前实现禁噪 → 必须严格平线；表格必须写 `oracle_gt`）

### 1.2 core 方法集合（no-init/no-prior）

固定为：
- `v2xregpp_initfree`
- `freealign_paper`
- `vips_initfree`
- `cbm_initfree`

可选附录（不影响 core-first 交付）：
- `*_stable` variants（需要时再跑）

> 实现一致性提示：VIPS/CBM estimator 的 `T` 语义是 (arg1 -> arg2)，corrector 必须按 (cav -> ego) 方向调用；已用回归测试锁死：`tools/tests/test_stage1_vips_cbm_direction.py`。

---

## 2) Dataset freeze（同数据集内一致；跨数据集不强行统一）

- **DAIR-V2X**：`comm_range=100`
- **OPV2V**：`comm_range=70`
- OPV2V P0：必须把最终 comm_range 写进 source-of-truth（建议通过 `--comm-range-override 70` 强制；或 preflight 断言两模态 checkpoint/config 的 comm_range=70）
- **V2V4Real (PASTAT checkpoint canonical)**：`comm_range=70`
  - 如要跑 `comm_range=200`（paper setting），必须单独成 lane（文件名/标题写死 `cr200`），并显式传 `--allow-comm-range-mismatch`（因为与该 checkpoint 的训练 config 可能不一致）。

---

## 3) 必过 Gate（Fail-fast）

跑 full 之前必须完成：
- stage1 结构：`tools/validate_stage1_cache.py`
- stage1 语义（local frame）：`tools/validate_stage1_semantics.py`
- 禁止：`single_comm0` / `comm-range-gating=auto` / `offline_map` 混入 core 结论
- no-op gate：非 bounds 方法 `pose_provider_applied_count` 不能全为 0
- 样本一致性 gate：同一噪声点各方法 `samples` 必须一致

（上述 gates 已写进 `docs/operations/fair_core_benchmark_setting_v1_20260301.md`，并在 V2V4Real summarizer 里加了 hard gate。）

---

## 4) 推荐执行（本机/直跑；10x3090 跑满 + 容错）

### 4.0 P0 执行冻结（环境 / I/O / Slurm）

在跑 full lane 之前，先把以下 P0 约束“写死”为 sbatch/父进程 export（不要靠隐式默认）：
- 环境变量（稳定性/吞吐）：`OPENCOOD_VOXEL_GPU=1`；并 export `OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1`。
- OPV2V I/O（吞吐/配额风险）：确保禁用 `inference_w_noise.py` 可视化落盘（必须包含 `--save_vis_interval 100000000`；否则默认每 40 帧写 png）。
- Slurm GPU 映射：避免 runner 把 `CUDA_VISIBLE_DEVICES` 当物理卡号写死（Slurm 常会 remap 成 slot/UUID）。
  - 最稳策略：单个 job 独占 10 卡跑 pipeline（`--gpus 0..9` 作为 slot）。
  - 若用 job-array/部分 GPU，必须确保 runner 做了 slot->parent_visible 映射（否则可能跑到未分配 GPU / 多进程挤同卡）。

### 4.1 一键 pipeline（推荐）

分别跑两条 lane（不要混）：

```bash
TAG=core_20260301

# Track-D
./.micromamba/envs/py39/bin/python -u tools/run_core_benchmark_pipeline.py \
  --tag ${TAG}_trackD \
  --comm-range-gating clean \
  --dair-max-per-gpu 2 --dair-split-noise \
  --opv2v-max-per-gpu 3 \
  --v2v4real-max-per-gpu 2 --v2v4real-split-noise

# Track-S
./.micromamba/envs/py39/bin/python -u tools/run_core_benchmark_pipeline.py \
  --tag ${TAG}_trackS \
  --comm-range-gating noisy \
  --dair-max-per-gpu 2 --dair-split-noise \
  --opv2v-max-per-gpu 3 \
  --v2v4real-max-per-gpu 2 --v2v4real-split-noise
```

输出（source-of-truth）：
- `outputs/core_pipeline_<tag>/SUMMARY.md`
- `outputs/dair_core_<tag>/`（每个 modality 一个子目录，含 plots）
- `outputs/full_bench_<opv2v_run_id>/`（opv2v autopilot full）
- `outputs/v2v4real_core_<tag>/`（含 `plots_yaml/`）

### 4.2 利用率调参（目标：CPU80%+ / GPU80%+）

经验规则（最稳）：
- AP 评估（Shapely IoU）是 CPU 单线程热点；要提高整体吞吐，优先 **每卡多进程**：
  - 把 `--*-max-per-gpu` 从 1→2→3 逐步加（直到显存/CPU 饱和）
  - DAIR/V2V4Real 建议配合 `--split-noise`，把 (pos,rot) 点拆成小任务，提高调度粒度
- 仍然偏低时，再把 `--opv2v-max-per-gpu` 提到 4（前提：CPU 核心够 + 显存不爆）

---

## 5) Slurm（可选：把两条 lane 自动排队跑完）

说明：不同集群的 partition/account/time-limit 不同，下面只提供模板思想：
- 一个 job 跑一个 lane（Track-D 或 Track-S）
- `--gpus 0..9` 使用同一个节点的 10 卡
- job 失败不影响另一个 lane（两条 lane 独立 sbatch）

（如需要我落地 `scripts/slurm/submit_core_benchmarks.sh` 模板，可以基于你们集群的 `sinfo/squeue` 信息再定参数。）
