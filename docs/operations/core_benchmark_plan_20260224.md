# Core Benchmark Plan (DAIR / OPV2V / V2V4Real) + Slurm Pipeline（2026-02-24）

> 目标：把 **core methods（无初值 / no-init）** 在 **DAIR / OPV2V / V2V4Real** 上用统一口径跑成“可引用”的 benchmark；同时把执行过程做成 **尽可能快** 且 **不出错** 的可执行合同（plan contract）。

> WARNING（2026-03-01）：本文是 2/24 的早期计划切片，存在已被“语义冻结”版本替代的内容：  
> - `single(comm0)`（`comm_range_override=0`）是 legacy，会改变 agent/GT set；canonical single 是 `single_ego_only=--force-ego-input-only`（noise=0）。  
> - V2V4Real 的 stage1 必须用 per-CAV（local-frame）cache；`..._80boxes/...` 已证实语义 FAIL。  
> 统一以 `docs/operations/benchmark_semantics.md` 与 `docs/operations/unified_core_benchmark_standard_and_plan_v2_20260228.md` 为准。

本计划优先满足你的约束：
- **主线只做无初值（no-init）**：`v2xregpp / freealign / vips / cbm`（VIPS/CBM 不补 prior）。
- 允许“轻微误差换速度”的加速实现，但必须有 **语义冻结 + 证据链**，避免 mixed-version/no-op/合同漂移。
- 你有 **10×3090**，希望尽可能吃满 GPU/CPU，并用 Slurm 形成自动流水线。

关联入口（现状与结果的 source-of-truth）：
- 方法/落脚点梳理（core vs audit + AP/配准衔接）：`docs/operations/benchmark_method_catalog.md`
- canonical vs non-canonical 资产清单：`docs/operations/benchmark_inventory.md`
- DAIR canonical（noise10）的统一表：`outputs/benchmark_unified_20260220/dair_noise10_ap_reg.csv`
- V2V4Real 现有 sweep（缺 VIPS/CBM）：`docs/operations/v2v4real_noise_sweep_methods.md`
- OPV2V unified fullbench（canonical 目标）合同：`docs/operations/opv2v_unified_fullbench_plan_20260223.md`

---

## 0) 先把你“到底什么有效”这件事说清楚（Status Snapshot）

> 这里说的“统一口径/公平”，默认指 **同一数据集内** 的横向对比：同一个 `model_dir + stage1 cache + noise schedule + comm-range 语义` 下只替换 pose backend。  
> 不同数据集之间（DAIR vs OPV2V vs V2V4Real）由于模型/训练/数据分布不同，AP 绝对值不做直接横比，重点看 **各自数据集内的排序与增益**。

### DAIR-V2X（已 canonical，core methods 已齐）
- source-of-truth：`outputs/pose_sweep_1to10_full_gpuvoxel20260218_results.jsonl`
- 汇总对比（AP+配准）：`outputs/benchmark_unified_20260220/dair_noise10_ap_reg.csv`
- 结论：**DAIR 的 core benchmark 不需要重跑**（除非你想把 DAIR 也并入 OPV2V 同样的 fullbench 调度形态；那是工程统一，不是缺数）。

### OPV2V（core methods 需要“新 run_id 的 canonical 重跑”才能引用）
- 现有 legacy run 只能作历史参考（原因见 `docs/operations/benchmark_inventory.md` 的 OPV2V 章节）。
- 本计划产出：用 **全新 run_id** 在冻结语义下把 core 跑成可引用 numbers。

### V2V4Real（需要补齐：VIPS / CBM，并把口径统一成严格可比）
- 现状：已有 `none/v2xregpp/freealign/v2vloc_oracle`，但 **VIPS/CBM 未跑**；且历史 run 存在 `--num-workers` 不一致等可比性瑕疵（见 `docs/operations/v2v4real_noise_sweep_methods.md`）。
- 本计划产出：把 core methods 在同一环境下补齐，并提供可复核 YAML。

---

## 1) 术语澄清：Track R / Track G（你问的 “track R 是啥”）

以 `docs/operations/heal_pose_fusion_execution_playbook.md` 为准：
- **Track R（Reference Benchmark Lane）**：更强调“公平/可复现/语义冻结”，不以速度为第一优先级。
- **Track G（GPU Acceleration Lane）**：允许实现替换以提速（例如 full GPU voxelization），但必须通过 parity gate（当前阈值档：`AP<=1e-3`）后才能“升格”当作可引用 benchmark。

你说的“偏向更快允许轻微误差”，语义上更接近 **Track G**。本计划执行时会：
- 以 **Track G 的在线/全 GPU 路径**跑 core（因为你要快），
- 但把 **语义冻结 / git clean / gate 证据**做足，确保 numbers 可引用、可复核。

---

## 2) Benchmark 合同（Plan Contract）

### 2.1 Goal / Decision（G0）
跑完后你能做的决策：
- 在 DAIR / OPV2V / V2V4Real 上，用同一口径回答：**no-init 的 core pose correction 方法到底谁更好、提升多少、代价多少**；
- 哪些曲线是“真实生效”，哪些是 **no-op/退化到 baseline**（直接剔除，不参与结论）。

### 2.2 Scope / Non-goals
Scope（本计划必须交付）：
- core methods（no-init）：`v2xregpp / freealign / vips / cbm` + bounds（`baseline/oracle/single_ego_only`）
- 数据集：DAIR / OPV2V / V2V4Real
- 统一产物：每个 run 的 YAML + 调度快照 + 聚合 CSV/图（见 DoD）

Non-goals（明确不做/不作为主线）：
- **不补 VIPS/CBM prior**（with-init 仅可作为“附录/可选”）
- HKUST / lidar_reg / imagematch 等 **audit 方法线**不纳入本轮 core-first 交付（后续单独开 audit 合同）

### 2.3 Semantics Freeze（G2）
必须显式冻结（写进命令/快照）：
- `solver_backend` / `runtime_mode` / `pose_source`
- `comm_range_gating`（禁止 `auto`）
- `noise schedule`（noise_list/rot_list、noise_target）
- `stage1 cache` 路径与样本数（OPV2V=2170；V2V4Real 以实际 test 为准）
- `model_dir`（权重）+ `fusion_method` + eval range/NMS（来自 model config）

### 2.4 Inputs Contract（G3）
OPV2V：
- dataset：`dataset/OPV2V/test`（len=2170）
- model/stage1 默认由 `tools/run_opv2v_fullbench_fast.py` 的 DEFAULT_* 给出，并在 preflight 校验 sample count。

V2V4Real（固定使用现有 sweep 的同一套输入）：
- model：`HEAL/opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25`
- stage1（per-CAV, canonical）：`HEAL/opencood/logs/v2v4real_stage1_pointpillar_from_pastat_bestval17_percav/test/stage1_boxes.json`

### 2.5 Outputs / Artifacts（G1/G7）
OPV2V canonical core run（source-of-truth）：
- `outputs/full_bench_<run_id>/config_snapshot.json`
- `outputs/full_bench_<run_id>/run_state.jsonl`
- `outputs/full_bench_<run_id>/logs/*.log`
- `outputs/full_bench_<run_id>/task_summary.json`（启动时 scope/pending 统计）
- `outputs/full_bench_<run_id>/task_summary_final.json`（结束时 final 成功/失败/缺失统计；用于流水线依赖判定）
- 模型目录 `HEAL/opencood/logs/**/AP030507_*.yaml`
- 汇总：`tools/summarize_opv2v_fullbench_from_yaml.py` 生成 `results_ap50_from_yaml.json`

V2V4Real core sweep：
- 模型目录 `HEAL/opencood/logs/<v2v4real_model_dir>/AP030507_*.yaml`
- 额外建议（强烈）：提交时用 `sbatch -o outputs/slurm_logs/%x-%j.out ...` 覆盖脚本内默认输出路径，并确保 slurm 日志里包含完整 cmd（`sbatch_pose_sweep.sh` 会打印 `cmd:` 行）。
- 额外建议（可选但更“可引用”）：在 `outputs/v2v4real_core_<date>/manifest.json` 里记录每条曲线的 `{method, note, slurm_job_id, model_dir, stage1, comm_range, noise_list, solver_backend, runtime_mode, comm_range_gating}`，把“source-of-truth”闭环到一个目录。

统一聚合（跨数据集对比用）：
- `tools/build_fullmatrix_benchmark_report.py` → `outputs/benchmark_fullmatrix_<date>/combined_noise_curve_long.csv` + `plots/`
- `tools/build_unified_benchmark_report.py` → `outputs/benchmark_unified_<date>/*.csv`

### 2.6 Acceptance / DoD（G1）
本计划的“完成”以不可变证据定义：
- 每个 run_id：`run_state.jsonl` 中 **所有 start 都有 end(code=0)**；
- `config_snapshot.json` 里 `git_dirty=false`（canonical 要求）、且 `comm_range_gating!=auto`；
- OPV2V（online_box）：必须通过严格 applied/no-op gate（不接受“抽查”）：
  - `tools/summarize_opv2v_fullbench_from_yaml.py --strict-applied-gate` 退出码为 0
  - `tools/audit_opv2v_fullbench_run.py` 报告无关键语义告警（pose_override/comm_range_gating 等）
- V2V4Real：每条方法线 YAML 必须包含 `timing_stats[*].pose_timing.pose_provider_applied_count`（意味着 `--pose-timing` 生效且在线 applied 信号可追溯）；并且非 `none` 方法不允许全 0（否则视为 no-op/退化，直接标 invalid）。
- 统一报告脚本能在新 run 上生成 `combined_noise_curve_long.csv` 且 coverage=100%（无缺噪声点）。

### 2.7 Stop-loss（G10）
任何一条满足立即停机/止损排查：
- AP 曲线与 baseline **逐点完全相同**，且 YAML 显示 applied 计数为 0（典型 no-op）；
- `comm_range_gating=auto` 被误用（直接判定不可引用，重跑）；
- Slurm/多进程导致 OOM 或频繁 crash（先降 `--max-per-gpu`，再做 smoke，确认稳定后继续）。
- 成本上限（建议写进 sbatch）：例如 `--time=12:00:00`；并设置“早停审计点”：OPV2V smoke 完成后先跑 `summarize --strict-applied-gate` + `audit`，通过才允许提交 full。

---

## 3) VIPS / CBM：现有结果“是否公平”的核验结论（你要我先确认的点）

### 3.1 DAIR（canonical core，公平性 OK）
证据：`outputs/pose_sweep_1to10_full_gpuvoxel20260218_results.jsonl`
- camera：`v2xregpp/freealign/vips/cbm/baseline/oracle` 使用同一 `model_dir` 与同一 `stage1_result`；
- lidar：同理（同一 `model_dir` 与同一 `stage1_result`）。

并且：
- VIPS/CBM 的 best 线启用了 `--pose-compare-current`（防止劣质解强行 apply）；
- 使用了明确的对比阈值（DAIR camera vips=5m / lidar vips=3m；cbm=1m），不是“默认值混跑”。

### 3.2 OPV2V legacy（不再可引用；且阈值/语义冻结不足）
证据：`outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/config_snapshot.json`
- `comm_range_gating=auto`（存在 cross-method confound 风险）；
- vips/cbm best 使用默认 compare threshold=3.0（未显式冻结/未做 dataset-specific 校验）；
- mixed-env 与覆盖不全问题使得该 run_id 不能作为最终 numbers。

### 3.3 V2V4Real（VIPS/CBM 未跑；需要按同一合同补齐）
本计划将补齐，并统一 `--num-workers 0`，避免 “stable/stateful + 多 workers” 的时序漂移风险。

> 重要约束（公平性）：本计划 **不做基于 test-set AP 的阈值调参**。任何 `pose-compare-*` 阈值若要调整，必须：
> 1) 作为 audit/附录单独记录（明确标注 tuned，不进入 core canonical）；或  
> 2) 基于独立的校准集/验证集确定，并在 full run 前冻结到命令/快照里（变更阈值=新 run_id）。

---

## 4) 执行计划（Slurm 优先，10×3090 吃满）

### 4.1 OPV2V：core fullbench（canonical）

推荐 run_id：
- `opv2v_core_full_20260224_r1`

推荐一次性占满 10 GPU（一个 Slurm job 内部再用调度器分发）：
- Slurm 必须保证 **单节点 10 卡**（否则本地调度器无法跨节点用满 GPU）：
  - `--nodes=1` + `--gres=gpu:10`（或 `--gpus-per-node=10`，按集群实际字段）
- 启动脚本：`tools/run_opv2v_fullbench_fast.py`
- 并发建议：先 smoke（小规模 + `--max-per-gpu 1`）确认不 OOM/不 no-op，再升到 2。
- `--gpus` 的含义：**GPU slot index**（0..N-1）。在 Slurm 下应让 `CUDA_VISIBLE_DEVICES` 由调度器提供（可能是数字也可能是 UUID），然后用 index 选择；不要把物理 GPU id/UUID 直接塞进 `--gpus`（调度器当前只接受 int）。
- 可靠性保证（用于 Slurm afterok 依赖链）：调度器会在结束时写 `task_summary_final.json`，并在存在失败/缺失 task 时 **退出码非 0**（避免“跑挂了但下游继续汇总”的假绿）。

#### 4.1.1 OPV2V Smoke（必跑，fail-fast）
示例（camera-only / noise=1 / 200 samples）：

```bash
set -euo pipefail
export PYTHONUNBUFFERED=1
export OPENCOOD_VOXEL_GPU=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1

.micromamba/envs/py39/bin/python tools/run_opv2v_fullbench_fast.py \
  --run-id opv2v_core_smoke_20260224_r0 \
  --gpus 0,1 \
  --max-per-gpu 1 \
  --num-workers 0 \
  --modalities camera \
  --sweeps noise10 \
  --noise-list 1 \
  --rot-list 1 \
  --solver-backend online_box \
  --runtime-mode register_and_fuse \
  --pose-source noisy_input \
  --comm-range-gating noisy \
  --require-clean-git \
  --methods v2xregpp,freealign,vips,cbm \
  --skip-oracle \
  --max-eval-samples 200 \
  |& tee outputs/opv2v_core_smoke_20260224_r0.launch.log

.micromamba/envs/v2x/bin/python tools/summarize_opv2v_fullbench_from_yaml.py \
  --run-dir outputs/full_bench_opv2v_core_smoke_20260224_r0 \
  --strict-applied-gate

.micromamba/envs/v2x/bin/python tools/audit_opv2v_fullbench_run.py \
  --run-dir outputs/full_bench_opv2v_core_smoke_20260224_r0
```

#### 4.1.2 OPV2V Full（canonical core）
核心命令（建议放进一个 `sbatch` 脚本里；并确保 `set -o pipefail`）：

```bash
set -euo pipefail
export PYTHONUNBUFFERED=1
export OPENCOOD_VOXEL_GPU=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1

.micromamba/envs/py39/bin/python tools/run_opv2v_fullbench_fast.py \
  --run-id opv2v_core_full_20260224_r1 \
  --gpus 0,1,2,3,4,5,6,7,8,9 \
  --max-per-gpu 2 \
  --num-workers 0 \
  --modalities camera,lidar \
  --sweeps noise10,drop20 \
  --noise-list 1,2,3,4,5,6,7,8,9,10 \
  --rot-list 1,2,3,4,5,6,7,8,9,10 \
  --solver-backend online_box \
  --runtime-mode register_and_fuse \
  --pose-source noisy_input \
  --comm-range-gating noisy \
  --require-clean-git \
  --methods v2xregpp,freealign,vips,cbm \
  --max-eval-samples 0 \
  |& tee outputs/opv2v_core_full_20260224_r1.launch.log
```

验收（跑完立刻做；不接受“抽查”）：
```bash
.micromamba/envs/v2x/bin/python tools/summarize_opv2v_fullbench_from_yaml.py \
  --run-dir outputs/full_bench_opv2v_core_full_20260224_r1 \
  --strict-applied-gate

.micromamba/envs/v2x/bin/python tools/audit_opv2v_fullbench_run.py \
  --run-dir outputs/full_bench_opv2v_core_full_20260224_r1
```

#### 4.1.3 Resume / Retry SOP（很重要）
- **续跑**：同一个 `run-id`、同一组语义参数（backend/runtime/pose_source/noise list/methods 等不变）时，重复执行同一条命令即可；调度器会跳过 `run_state.jsonl` 中已成功完成的 task。
- **补跑失败**：先看 `outputs/full_bench_<run_id>/run_state.jsonl` 与 `tools/audit_opv2v_fullbench_run.py`，修复原因（OOM/数据/语义）后原地重跑同命令；若你要强制重跑全部 task，用 `--force-rerun`（更推荐新 run_id 保留证据链）。
- **任何语义参数变更**（例如 comm_range_gating/noise schedule/method 定义/阈值）：必须 bump 新 run_id，禁止混写。

#### 4.1.4 Slurm 流水线（依赖链示例）
你可以用 `afterok` 把 “smoke → full → CPU 汇总/出图” 串起来，做到自动化且不假绿：

```bash
SMOKE_JOBID=$(sbatch opv2v_core_smoke.sbatch | awk "{print \$4}")
FULL_JOBID=$(sbatch --dependency=afterok:${SMOKE_JOBID} opv2v_core_full.sbatch | awk "{print \$4}")
sbatch --dependency=afterok:${FULL_JOBID} opv2v_core_report_cpu.sbatch
```

要点：
- GPU job 里用 `set -euo pipefail`，并在末尾跑 `summarize --strict-applied-gate` + `audit`，失败即退出非 0；
- CPU job 只做 `tools/build_fullmatrix_benchmark_report.py` / `tools/build_unified_benchmark_report.py` 之类汇总出图，避免占用 GPU walltime。

### 4.2 V2V4Real：core sweep（补齐 VIPS/CBM）

建议用 Slurm 多 job（或 array）：一个 task=一条 method 曲线（每条曲线内部 sweep 0..4）。

方法集合（core no-init）：
- `none`
- `v2xregpp_initfree`
- `freealign_paper`
- `vips_initfree`
- `cbm_initfree`

统一设置（冻结口径）：
- `--comm-range-override 200`
- `--noise-target non-ego`
- paired sweep：`--pos-std-list 0,1,2,3,4 --rot-std-list 0,1,2,3,4`
- `--num-workers 0`
- 环境：`OPENCOOD_VOXEL_GPU=1`

提交示例（最稳版本：显式冻结 online 语义 + 强制 pose-timing；用 `-o` 覆盖默认 slurm 输出路径，避免日志散落）：

```bash
STAMP=$(date +%Y%m%d_%H%M%S)
METHODS=(none v2xregpp_initfree freealign_paper vips_initfree cbm_initfree)
for M in "${METHODS[@]}"; do
  sbatch -o "outputs/slurm_logs/%x-%j.out" -J "v2v4real_core_${M}" \
    --gres=gpu:1 \
    --export=ALL,OPENCOOD_VOXEL_GPU=1,OMP_NUM_THREADS=1,MKL_NUM_THREADS=1,OPENBLAS_NUM_THREADS=1,NUMEXPR_NUM_THREADS=1 \
    HEAL/opencood/tools/sbatch_pose_sweep.sh \
      --model-dir "opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25" \
      --pose-correction "${M}" \
      --stage1-result "opencood/logs/v2v4real_stage1_pointpillar_from_pastat_bestval17_percav/test/stage1_boxes.json" \
      --note "_comm200_core_${M}_20260224_${STAMP}" \
      --comm-range 200 \
      --noise-target non-ego \
      --pos-std-list 0,1,2,3,4 \
      --rot-std-list 0,1,2,3,4 \
      --num-workers 0 \
      -- --comm-range-gating noisy \
         --solver-backend online_box \
         --runtime-mode register_and_fuse \
         --pose-source noisy_input \
         --pose-device cuda \
         --pose-timing
done
```

验收：
- 每条方法生成对应的 `AP030507_<pose_correction>_*comm200_core_*yaml`；
- YAML 的 `rel_error_stats` 与 AP 曲线长度均为 5 点（0..4）。

---

## 5) 汇总与出图（跑完后统一收口）

OPV2V：
```bash
.micromamba/envs/v2x/bin/python tools/summarize_opv2v_fullbench_from_yaml.py \
  --run-dir outputs/full_bench_opv2v_core_full_20260224_r1
```

统一全矩阵长表 + 同风格图：
```bash
.micromamba/envs/v2x/bin/python tools/build_fullmatrix_benchmark_report.py
```

DAIR+OPV2V 统一表（可扩展到 V2V4Real，若你希望统一入口）：
```bash
.micromamba/envs/v2x/bin/python tools/build_unified_benchmark_report.py
```

---

## 6) 后续（可选附录，不阻塞 core-first）

当 core numbers 跑成 canonical 后，再单独开一份 audit 合同（建议复制本文件结构）：
- with-init（VIPS/CBM prior）只在你明确要“init误差小/部分丢失”的附录对比时再跑；
- HKUST/lidar_reg/imagematch 需要 cache/payload 保障，且必须更严格 applied gate（避免 no-op）。
