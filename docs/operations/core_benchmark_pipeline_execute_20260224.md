# Core Benchmark Pipeline (Execute Now) — DAIR / OPV2V / V2V4Real (2026-02-24)

本文件是“只针对你这次需求”的执行合同：**把 core(no-init) 方法在 DAIR/OPV2V/V2V4Real 上跑齐**，目标是：
- **资源尽量跑满**（10×3090 + 合理 CPU 线程限制）
- **尽可能少出错**（smoke + gate + 自动重试）
- **出错不阻塞后续**（OPV2V 失败也继续跑 V2V4Real；V2V4Real 某条线失败也不影响其他线）
- **V2V4Real 公平可比**（同模型/同 stage1/同噪声日程/同 online 语义冻结）

> 说明：当前机器上 Slurm client 存在，但控制器不可达（`sinfo` 连接失败）。因此本 pipeline 采用 **本机多 GPU 并发** + `tmux` 保活。
> 若后续你把同样命令放进 `sbatch --gres=gpu:10` 的单节点作业里，逻辑不变。

---

## 1) Scope（只跑这些）

### 1.1 DAIR（不重跑，直接引用 canonical core）
- source：`outputs/pose_sweep_1to10_full_gpuvoxel20260218_results.jsonl`
- 汇总：`outputs/benchmark_unified_20260220/dair_noise10_ap_reg.csv`

### 1.2 OPV2V（重跑 canonical core）
- methods：`v2xregpp, freealign, vips, cbm`（no-init）+ `baseline/oracle/single`
- modalities：camera + lidar
- sweeps：noise10 + drop20
- noise axis：1..10（paired）
- 语义冻结：`online_box + register_and_fuse + pose_source=noisy_input + comm_range_gating=noisy`
- 执行方式：`tools/opv2v_benchmark_autopilot.py`（带 smoke + strict-applied gate + 自动重试）

### 1.3 V2V4Real（补齐 core，并一次性占满 10 卡）
- comm=200，noise sweep：pos=rot=0..4（paired），noise_target=non-ego
- 10 条线（刚好 10 GPU 并发，公平对比）：
  - bounds：`none`、`v2vloc_oracle_initfree`
  - v2xregpp：`v2xregpp_initfree`、`v2xregpp_stable`
  - freealign：`freealign_paper`、`freealign_paper_stable`
  - vips：`vips_initfree`、`vips_stable`
  - cbm：`cbm_initfree`、`cbm_stable`
- 语义冻结：`online_box + register_and_fuse + pose_source=noisy_input + comm_range_gating=noisy + pose_timing`

---

## 2) 一键执行（推荐）

会自动依次跑：
1) OPV2V autopilot（smoke→full，失败会重试；最终失败也不阻塞下一步）
2) OPV2V 汇总出图（full 成功才做）
3) V2V4Real 10 条线并发

```bash
cd /home/qqxluca/projects/v2xreg_private

# 新开一个 tmux session 保活（跑很久）
TAG=$(date +%Y%m%d_%H%M%S)
tmux new -d -s corepipe_${TAG} "bash -lc '\
  set -euo pipefail; \
  export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1; \
  export PYTHONUNBUFFERED=1; \
  ./.micromamba/envs/py39/bin/python -u tools/run_core_benchmark_pipeline.py --tag ${TAG} --gpus 0,1,2,3,4,5,6,7,8,9 \
  |& tee outputs/core_pipeline_${TAG}.log'"

echo \"launched tmux session: corepipe_${TAG}\"
```

---

## 3) 监控（你只需要会这 3 条）

```bash
tmux attach -t corepipe_<TAG>
tail -f outputs/core_pipeline_<TAG>.log
nvidia-smi
```

---

## 4) 产物（跑完后看这些）

OPV2V（autopilot）：
- autopilot log：`outputs/opv2v_autopilot_<TAG>/autopilot.log`
- full run dir：`outputs/full_bench_opv2v_autopilot_full_<TAG>_a*/`
  - `config_snapshot.json` / `run_state.jsonl` / `task_summary_final.json`
  - `results_ap50_from_yaml.json` + `plots_yaml/`

OPV2V（统一汇总，full 成功才会生成）：
- `outputs/core_pipeline_<TAG>/benchmark_fullmatrix/combined_noise_curve_long.csv`
- `outputs/core_pipeline_<TAG>/benchmark_unified/dair_noise10_ap_reg.csv`

V2V4Real：
- run dir：`outputs/v2v4real_core_<TAG>/`
  - `logs/*.log`
  - `results.jsonl`（每条线的 mean AP / rel_error / applied 统计）
  - `summary.md`（对比表 + 失败列表）

