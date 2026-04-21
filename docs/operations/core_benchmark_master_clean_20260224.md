# Core Benchmark Master (Clean) — Status, Numbers, and Execution Plan (2026-02-24)

目标：把你现在“到底哪些 benchmark 有效、结果怎么看、接下来怎么把 core 方法在 DAIR/OPV2V/V2V4Real 跑齐”一次性捋清楚，且**只写和这次任务直接相关的东西**。

---

## 1) 现在到底哪些 benchmark 是“有效/可引用”的？

> 这里的“有效/可引用”= 同一口径可复核 + 产物齐全 + 不混用旧 schema/no-op。

### A. DAIR-V2X（有效 / canonical）
- **AP + 配准（noise10, 1..10）**：`outputs/benchmark_unified_20260220/dair_noise10_ap_reg.csv`
  - source-of-truth sweep：`outputs/pose_sweep_1to10_full_gpuvoxel20260218_results.jsonl`
- **Table III 配准主表（paper3737=3737 pairs, te_re）**：`outputs/benchmark_unified_20260220/dair_table3_best_te_re.csv`
  - source report（从 jsonl 重算）：`docs/operations/table3_paper3737_repro_status.md`

### B. OPV2V（现有结果：仅历史参考；需要新 run_id 重跑才可引用）
- 旧 run：`outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/`
- 旧聚合：`outputs/benchmark_unified_20260220/opv2v_dual_suite_ap_reg.csv`
- **为什么不再 canonical（2026-02-24 更新）：**
  - online runtime 下存在 `comm_range_gating=auto` 的语义漂移风险；
  - mixed-version/mixed-env + 旧 YAML schema 缺少 `pose_provider_applied_count`，无法严格 gate no-op。
  - 证据汇总：`docs/operations/unified_benchmark_contract_and_comparison_20260220.md`（Update 段）

### C. V2V4Real（现有曲线：不完整；需要补齐 VIPS/CBM 并统一口径）
- 现有（缺 VIPS/CBM + 历史 num_workers/RNG 问题说明）：`docs/operations/v2v4real_noise_sweep_methods.md`
- 本轮要做：在**同一环境**下把 core methods 全部跑一遍（见第 5 节执行计划）。

---

## 2) “benchmark 落脚点”有哪些？（别把不同口径混在一起）

1) **下游协同感知 AP（同时统计配准指标）**
   - DAIR：来自 `outputs/pose_sweep_1to10_full_gpuvoxel20260218_results.jsonl` 聚合。
   - OPV2V：来自 `outputs/full_bench_<run_id>/`（`run_state.jsonl` + `config_snapshot.json` + YAML 汇总）。
   - V2V4Real：同样跑 `HEAL/opencood/tools/inference_w_noise.py`，用 YAML 产物对比曲线。

2) **只做配准评估（Table III / paper3737）**
   - 输出 Success/mRTE/mRRE/Time，不接下游 AP。

3) **配准评估 → AP 的经验映射（用于预估/止损，不等于真实 AP）**
   - mapping 报告：`docs/operations/pose_error_to_ap_mapping_report_20260224.md`
   - Table3→AP 预估产物（本机已生成）：
     - LiDAR：`outputs/table3_ap_estimate_from_mapping_20260224_lidar.csv`
     - Camera：`outputs/table3_ap_estimate_from_mapping_20260224_camera.csv`

---

## 3) 方法集合：Core vs Audit（只保留与你这次诉求相关的）

### 3.1 Core methods（本轮必须跑齐 / no-init）
- `v2xregpp`
- `freealign`
- `vips`（initfree，**不补 prior**）
- `cbm`（initfree，**不补 prior**）
- bounds：`baseline`（none）+ `oracle`（GT pose / upper bound）
- OPV2V 额外 bounds：`single`（comm=0，上界/参照）

### 3.2 Audit methods（本轮不作为交付主线，只在后续 append）
- with-init：`vips_prior`、`cbm_prior`
- camera-only：`imagematch_*`
- lidar-only：`lidarreg_ransac`、`hkust_*`

> 完整方法-实现映射表见：`docs/operations/benchmark_method_catalog.md`（code-level source-of-truth 也在 `tools/run_opv2v_fullbench_fast.py:METHODS`）。

---

## 4) 现有“有效 benchmark”跑出来的效果对比（你最关心的 numbers）

### 4.1 DAIR-V2X / noise10 / AP50（canonical）
source：`outputs/benchmark_unified_20260220/dair_noise10_ap_reg.csv`

Camera（mean over noise=1..10）：
| method | AP50 | success@2m | rel_trans(m) | rel_yaw(deg) |
|---|---:|---:|---:|---:|
| baseline | 0.0290 | 0.1818 | 6.8567 | 4.3847 |
| v2xregpp(best) | 0.0289 | 0.1856 | 6.8478 | 4.3265 |
| freealign(best) | 0.0264 | 0.1708 | 11.4437 | 10.7070 |
| vips(best) | 0.0257 | 0.1535 | 19.0249 | 19.8071 |
| cbm(best) | 0.0220 | 0.0380 | 55.7637 | 69.4322 |
| oracle | 0.0511 | 1.0000 | 0.0000 | 0.0000 |

LiDAR（mean over noise=1..10）：
| method | AP50 | success@2m | rel_trans(m) | rel_yaw(deg) |
|---|---:|---:|---:|---:|
| baseline | 0.2532 | 0.1818 | 6.8567 | 0.0000 |
| v2xregpp(best) | 0.3394 | 0.4772 | 5.1699 | 1.7611 |
| freealign(best) | 0.3267 | 0.4131 | 5.3349 | 1.1053 |
| vips(best) | 0.2537 | 0.1558 | 18.8581 | 15.3985 |
| cbm(best) | 0.2641 | 0.0274 | 64.2744 | 74.7101 |
| oracle | 0.3800 | 1.0000 | 0.0000 | 0.0000 |

解读（只说结论，不加额外故事）：
- DAIR：**LiDAR 上 v2xregpp/freealign 明显提升 AP**；camera 上 core 方法对 AP 提升很弱。

### 4.2 OPV2V / noise10（历史参考；非 canonical）
source：`outputs/benchmark_unified_20260220/opv2v_dual_suite_ap_reg.csv`

Camera（mean over noise=1..10）：
| method | AP50 | success@2m | rel_trans(m) | rel_yaw(deg) |
|---|---:|---:|---:|---:|
| baseline | 0.1061 | 0.1835 | 6.8689 | 4.4019 |
| single(n0) | 0.1489 | - | - | - |
| v2xregpp(best) | 0.1110 | 0.2113 | 10.9389 | 11.6241 |
| freealign(best) | 0.0987 | 0.1770 | 9.6817 | 16.0312 |
| vips(best) | 0.0701 | 0.1125 | 17.7818 | 27.7257 |
| cbm(best) | 0.0525 | 0.0040 | 34.9275 | 57.7976 |
| oracle | 0.3020 | 1.0000 | 0.0000 | 0.0000 |

LiDAR（mean over noise=1..10）：
| method | AP50 | success@2m | rel_trans(m) | rel_yaw(deg) |
|---|---:|---:|---:|---:|
| baseline | 0.4315 | 0.1835 | 6.8689 | 4.4019 |
| single(n0) | 0.9067 | - | - | - |
| v2xregpp(best) | 0.9348 | 0.9108 | 0.9658 | 0.7403 |
| freealign(best) | 0.8416 | 0.6925 | 4.6161 | 8.2795 |
| vips(best) | 0.4319 | 0.1632 | 13.0633 | 18.4031 |
| cbm(best) | 0.4298 | 0.0090 | 37.8374 | 61.1202 |
| oracle | 0.9594 | 1.0000 | 0.0000 | 0.0000 |

> drop20 同理（主排序不变），不在这里重复抄表；详见 CSV。

### 4.3 V2V4Real / comm=200 / noise 0..4（历史参考；缺 VIPS/CBM）
YAML 在：
`HEAL/opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25/AP030507_*_comm200_paper.yaml`

当前 AP50（0..4，括号内是 mean）：
- none: `[0.5751, 0.5722, 0.5686, 0.5627, 0.5602]` (0.5678)
- v2xregpp_initfree: `[0.5753, 0.5734, 0.5698, 0.5658, 0.5627]` (0.5694)
- freealign_paper: `[0.5529, 0.5527, 0.5522, 0.5519, 0.5516]` (0.5523)
- v2vloc_oracle_initfree: `[0.5753, 0.5752, 0.5753, 0.5750, 0.5751]` (0.5752)

说明：上述曲线本身能看趋势，但**不满足你要的“公平 + 补齐 VIPS/CBM”**；因此本轮会按统一合同重跑一次（见第 5 节）。

---

## 5) Table III → 协同感知 AP：怎么“估计”？

你要的是“用 Table III 的配准结果，大概推一下协同感知 AP 会怎样”。仓库里已经有一条**可复核**的经验映射链路：

1) 用 fullbench 长表拟合 `AP50 ≈ b0 + b1*success@2m + b2*mean_rel_yaw_deg`
   - 报告：`docs/operations/pose_error_to_ap_mapping_report_20260224.md`
2) 用 Table III 的 `success@2m` + `mRRE@2m`（近似 yaw）代入做 **AP50_pred**
   - LiDAR 预估：`outputs/table3_ap_estimate_from_mapping_20260224_lidar.csv`（RMSE≈0.036）
   - Camera 预估：`outputs/table3_ap_estimate_from_mapping_20260224_camera.csv`（RMSE≈0.004）

注意边界（必须写清楚，避免误用）：
- 这是 **triage/止损用的 rough 预估**，不能替代真实 fullbench AP；
- `mRRE@2m` 只是 yaw 的近似，且 Table III 的 pair 分布与 fullbench 不同，都会引入误差。

一个“你能直接用来对比”的例子（DAIR / LiDAR 映射；RMSE≈0.036，对应 `outputs/table3_ap_estimate_from_mapping_20260224_lidar.csv`）：

| Table3 row | success@2m(%) | mRRE@2m(deg) | time(s) | AP50_pred |
|---|---:|---:|---:|---:|
| ICP-noise0 | 100.00 | 0.154 | 0.065 | 0.3796 |
| PICP-noise0 | 100.00 | 0.225 | 0.170 | 0.3796 |
| V2X-Reg++ GT25 | 67.84 | 1.008 | 0.096 | 0.3399 |
| V2X-Reg++ GT15 | 67.43 | 0.988 | 0.440 | 0.3394 |
| V2X-Reg++ SC15 | 58.92 | 1.040 | 0.095 | 0.3289 |
| V2X-Reg++ PP15 | 57.27 | 1.021 | 0.660 | 0.3268 |
| Teaser++ | 38.40 | 0.863 | 0.191 | 0.3036 |

---

## 6) 你指出的 Table III 耗时“不合理”（例如 GT25 < GT15）到底怎么解释？

你看到的“GT25 比 GT15 更快/更慢”通常不是“理论上不可能”，而是这两点叠加造成的：

1) **Table III 报告里的 `best_time_sec` 来自 `best_source`**  
   `best_source` 是“指标最好”的那次 run，不保证配置完全同构；  
   所以 **best 的 time 不可拿来做严格的 GT15 vs GT25 复杂度对比**。

2) **不同 run 的 time 统计口径/实现路径可能不同**  
   - 有的 run 带 ICP refine / 一致性过滤 / 不同 top-k 候选等；
   - 有的 time 来自并行 shard（会被并发/CPU 抢占放大或缩小）。

如果你要一条“可引用”的时间对比线，建议做法是：
- 固定同一台机器 + 单进程测时 + 同一 thread cap，然后统一 patch 到 metrics。  
  工具入口：`tools/measure_table3_time.py`（当前覆盖 ICP/PICP/VIPS/CBM/HKUST；若要补 v2xregpp* 也可按同范式扩展）。

---

## 7) VIPS / CBM：我对“是否公平、是否发挥潜能”的确认

结论（针对你要的 **no-init core**）：
- **VIPS/CBM 在文献与实现里都是 init-based 方法**；本仓库的 initfree 版本本质是 `T_init = I`（不提供 prior），因此效果弱是预期现象。
- 现有 DAIR core sweep 中，VIPS/CBM 是 **initfree（无 prior）**，且跑在 **同一 stage1 cache**、同一 noise schedule 下；并且默认 `pose_device=auto` 在这台 3090 机器上会走 CUDA（不属于“故意跑慢/跑残”）。
- V2V4Real 上 VIPS/CBM 之前确实没跑过：因此本轮会用统一合同补齐（见下节执行）。

---

## 8) 执行计划（把 core 在 OPV2V + V2V4Real 跑齐；DAIR 直接引用 canonical）

你要的三个关键属性：
- 资源尽量跑满（10×3090）
- 少出错（smoke + gates + retries）
- 容错（某条线失败也继续后面的线，最后统一汇总失败）

补一句你之前问的 Track：
- Track R = reference（公平/可复现优先）
- Track G = acceleration（更快，允许轻微误差，但必须冻结语义并留证据）
- 本计划按你的诉求偏 Track G：全 GPU voxel + online runtime + 显式 `comm_range_gating=noisy` + applied gate（避免 no-op）。

对应“可执行合同”文件（已写好，直接照抄跑）：
- `docs/operations/core_benchmark_pipeline_execute_20260224.md`

一键启动（本机多 GPU + tmux 保活）：

```bash
cd /home/qqxluca/projects/v2xreg_private

TAG=$(date +%Y%m%d_%H%M%S)
tmux new -d -s corepipe_${TAG} "bash -lc '\
  set -euo pipefail; \
  export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1; \
  export PYTHONUNBUFFERED=1; \
  ./.micromamba/envs/py39/bin/python -u tools/run_core_benchmark_pipeline.py \
    --tag ${TAG} \
    --gpus 0,1,2,3,4,5,6,7,8,9 \
    --opv2v-max-per-gpu 2 \
  |& tee outputs/core_pipeline_${TAG}.log' "
```

跑完你只需要看：
- `outputs/core_pipeline_<TAG>/SUMMARY.md`
- OPV2V run dir：`outputs/full_bench_<opv2v_run_id>/`
- V2V4Real 结果：`outputs/v2v4real_core_<TAG>/summary.md`

### Slurm 说明（简短）
- 本机上 `sbatch/sinfo` 客户端存在，但当前 `sinfo` 显示无法连接 controller；因此推荐直接用 tmux 本机并发跑。
- 如果你在另一台“能连 slurm controller”的节点上提交作业，可以把上面的命令原样塞进单节点 10 卡作业：

```bash
#!/usr/bin/env bash
#SBATCH -J corebench
#SBATCH --nodes=1
#SBATCH --gres=gpu:10
#SBATCH --cpus-per-task=40
#SBATCH --time=3-00:00:00
#SBATCH --output=/path/to/slurm/%x-%j.out

set -euo pipefail
cd /home/qqxluca/projects/v2xreg_private
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export PYTHONUNBUFFERED=1
TAG=$(date +%Y%m%d_%H%M%S)
./.micromamba/envs/py39/bin/python -u tools/run_core_benchmark_pipeline.py --tag ${TAG} --gpus 0,1,2,3,4,5,6,7,8,9 --opv2v-max-per-gpu 2
```
