# Unified Benchmark Contract & Comparison (2026-02-20)

更新: 2026-02-20 23:20

## Update（2026-02-24）：OPV2V 部分不再可作为 canonical numbers（仅保留历史参考）

从 2026-02-23~02-24 的审计与修复进展来看，本文件里的 OPV2V 结果源
`outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/` 存在以下问题：

- **合同未冻结**：`comm_range_gating=auto`（online runtime 下存在语义漂移风险），不满足“最新统一 benchmark 条件”。
- **mixed-version / mixed-env**：同一 run_id 发生过 mid-run 修复混写、python env 混用，导致跨方法可比性不足。
- **扩展矩阵不完整**：init/no-init/HKUST 的追加任务并未全部完成（run_state/task_summary 可证）。
- **旧 YAML schema 缺少有效性信号**：许多 `AP030507_*.yaml` 的 `pose_timing` 不含 `pose_provider_applied_count`，
  无法对“方法是否真正 apply（是否 no-op）”做严格 gate（这也是 imagematch/hkust 排查里最关键的证据链之一）。

因此：
- **DAIR 部分仍可作为历史统一聚合的参考**（它对应的是另一条已完成的 sweep 结果源）。
- **OPV2V canonical fullmatrix** 需要用全新 unified run_id 重新跑（git clean + 显式 `--comm-range-gating noisy` + applied gate）。

下一步执行合同见：
- `docs/operations/opv2v_unified_fullbench_plan_20260223.md`
- `docs/operations/benchmark_pending_runs_and_plan_20260224.md`

## 0. 这份文档解决什么问题

目标是把当前仓库里“分散且口径不一”的 benchmark，压成一个可复核、可复跑、可追溯的统一口径：

1. 固化统一条件（dataset/split/noise/gate/source-of-truth）。
2. 在“有效方法集合”内做全量对比（AP + 配准）。
3. 明确有初值/无初值方法在 DAIR/OPV2V 上的结论。
4. 给出缺口检查与补跑结论（本轮是否还需要补跑）。

本轮统一聚合产物（机器可复算）在：
- `outputs/benchmark_unified_20260220/dair_noise10_ap_reg.csv`
- `outputs/benchmark_unified_20260220/opv2v_dual_suite_ap_reg.csv`
- `outputs/benchmark_unified_20260220/dair_table3_best_te_re.csv`
- `outputs/benchmark_unified_20260220/coverage_checks.json`

对应聚合脚本：
- `tools/build_unified_benchmark_report.py`

补充（全矩阵长表 + 无初值风格统一出图）：
- `tools/build_fullmatrix_benchmark_report.py`
- `outputs/benchmark_fullmatrix_20260220/combined_noise_curve_long.csv`
- `outputs/benchmark_fullmatrix_20260220/method_registry.csv`
- `outputs/benchmark_fullmatrix_20260220/plots/`

---

## 1. Preflight 合同（Plan-Preflight）

### 1.1 结论
- ALLOW（核心统一对比可直接使用，且核心方法覆盖无缺口）。

### 1.2 Gate 检查（精简版）
- G0 Goal/Decision: PASS
  - 本文明确用于“统一条件下的跨方法对比与结论收敛”。
- G1 DoD: PASS
  - 以 4 个固定聚合产物作为 DoD（CSV/JSON），并记录脚本入口。
- G2 Semantics Freeze: PASS
  - DAIR 使用 `pose_sweep_1to10_full_gpuvoxel20260218_results.jsonl`；OPV2V 使用 `full_bench_opv2v_autopilot_full_20260216_auto3_a1`。
- G3 Input Contract: PASS
  - OPV2V stage1/run completion 由 `run_state.jsonl` + `config_snapshot.json` + `results_ap50_from_yaml.json` 共同约束。
- G4 Smoke/Toolchain: PASS
  - 相关 smoke/fullbench 与证据链已存在并完成。
- G5 Confound/Cancellation: PASS
  - 统一排除“无效对比”：camera-only `v2xregpp_occhint` 不混入跨模态主表。
- G6 Effectiveness: PASS
  - LiDAR 上方法显著分化（尤其 v2xregpp/freealign 与 baseline 对比）。
- G7 Source of Truth: PASS
  - 完成判定统一看 `run_state.jsonl`；指标统一看 CSV 聚合产物。
- G8 Resume Safety: PASS
  - 以不可变 run_dir + 聚合脚本重复执行实现幂等。
- G9 Smoke First: PASS
  - 历史流程已执行 smoke->full。
- G10 Cost/Stop-loss: PARTIAL
  - 文档层面仍缺统一预算阈值字段，但不影响本轮结果可信性。

---

## 2. 统一条件冻结（Semantics Freeze）

### 2.1 DAIR（AP + 配准）
- 数据与条件：`noise10`（1..10），full sweep。
- 结果源：`outputs/pose_sweep_1to10_full_gpuvoxel20260218_results.jsonl`
- 聚合表：`outputs/benchmark_unified_20260220/dair_noise10_ap_reg.csv`
- 方法集合：`baseline/oracle + {v2xregpp,freealign,vips,cbm} x {best,stable}`。

### 2.2 OPV2V（AP + 配准）
- 数据与条件：`noise10` 与 `drop20`（均取噪声 1..10），single 仅 n=0。
- 结果源：`outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/`
  - completion: `run_state.jsonl`
  - AP: `results_ap50_from_yaml.json`
  - semantics: `config_snapshot.json`
- 聚合表：`outputs/benchmark_unified_20260220/opv2v_dual_suite_ap_reg.csv`

更新（2026-02-23）：
- `inference_w_noise.py` 在 online runtime 下会隐式切换 `comm_range_use_clean_pose`，导致 baseline 与 pose-correction 方法可能处于不同 gating 语义。
  为避免 cross-method confound，后续 fullbench 应显式传入 `--comm-range-gating {clean|noisy}` 并写入 `config_snapshot.json`。
  对应调度器已补齐参数与 git provenance：`tools/run_opv2v_fullbench_fast.py`。

### 2.3 DAIR Table III（注册主表）
- 统一 gate: `te_re`。
- 报告源：`docs/operations/table3_paper3737_repro_status.md`
- 聚合表：`outputs/benchmark_unified_20260220/dair_table3_best_te_re.csv`

---

## 3. 有效方法筛选与覆盖检查

核心统一范围（跨 DAIR/OPV2V 主对比）定义为：
- `baseline`, `oracle`, `single`（仅 OPV2V）、`v2xregpp`, `freealign`, `vips`, `cbm`

筛选说明：
- `v2xregpp_occhint` 当前是 camera-only append，不具备 lidar 对应线；因此不纳入“跨模态统一主表”，仅作为 camera 扩展结果单列保留。

覆盖检查结果：
- `outputs/benchmark_unified_20260220/coverage_checks.json`
  - `missing_core_count = 0`
  - `total_entries = 444`
  - `occhint_counts`: camera/noise10=20, camera/drop20=20, lidar/noise10=0, lidar/drop20=0

结论：
- 核心方法在统一条件下已全量覆盖，不需要额外补跑。

---

## 4. 统一对比结果（AP + 配准）

注：下面均为聚合后的均值；完整明细见 CSV。

### 4.1 DAIR `noise10`（1..10）

#### Camera
| method | AP50 | success@2m | rel_trans(m) | rel_yaw(deg) |
| --- | ---: | ---: | ---: | ---: |
| baseline | 0.0290 | 0.1818 | 6.8567 | 4.3847 |
| v2xregpp(best) | 0.0289 | 0.1856 | 6.8478 | 4.3265 |
| freealign(best) | 0.0264 | 0.1708 | 11.4437 | 10.7070 |
| vips(best) | 0.0257 | 0.1535 | 19.0249 | 19.8071 |
| cbm(best) | 0.0220 | 0.0380 | 55.7637 | 69.4322 |
| oracle | 0.0511 | 1.0000 | 0.0000 | 0.0000 |

#### LiDAR
| method | AP50 | success@2m | rel_trans(m) | rel_yaw(deg) |
| --- | ---: | ---: | ---: | ---: |
| baseline | 0.2532 | 0.1818 | 6.8567 | 0.0000 |
| v2xregpp(best) | 0.3394 | 0.4772 | 5.1699 | 1.7611 |
| freealign(best) | 0.3267 | 0.4131 | 5.3349 | 1.1053 |
| vips(best) | 0.2537 | 0.1558 | 18.8581 | 15.3985 |
| cbm(best) | 0.2641 | 0.0274 | 64.2744 | 74.7101 |
| oracle | 0.3800 | 1.0000 | 0.0000 | 0.0000 |

要点：
- DAIR camera 基本无显著 AP 提升（v2xregpp-best 与 baseline 接近）。
- DAIR lidar 有明确收益：v2xregpp/freealign 均显著高于 baseline。

### 4.2 OPV2V `noise10`（1..10，single=n0）

#### Camera
| method | AP50 | success@2m | rel_trans(m) | rel_yaw(deg) |
| --- | ---: | ---: | ---: | ---: |
| baseline | 0.1061 | 0.1835 | 6.8689 | 4.4019 |
| single(n0) | 0.1489 | - | - | - |
| v2xregpp(best) | 0.1110 | 0.2113 | 10.9389 | 11.6241 |
| freealign(best) | 0.0987 | 0.1770 | 9.6817 | 16.0312 |
| vips(best) | 0.0701 | 0.1125 | 17.7818 | 27.7257 |
| cbm(best) | 0.0525 | 0.0040 | 34.9275 | 57.7976 |
| oracle | 0.3020 | 1.0000 | 0.0000 | 0.0000 |

#### LiDAR
| method | AP50 | success@2m | rel_trans(m) | rel_yaw(deg) |
| --- | ---: | ---: | ---: | ---: |
| baseline | 0.4315 | 0.1835 | 6.8689 | 4.4019 |
| single(n0) | 0.9067 | - | - | - |
| v2xregpp(best) | 0.9348 | 0.9108 | 0.9658 | 0.7403 |
| freealign(best) | 0.8416 | 0.6925 | 4.6161 | 8.2795 |
| vips(best) | 0.4319 | 0.1632 | 13.0633 | 18.4031 |
| cbm(best) | 0.4298 | 0.0090 | 37.8374 | 61.1202 |
| oracle | 0.9594 | 1.0000 | 0.0000 | 0.0000 |

### 4.3 OPV2V `drop20`（1..10，single=n0）

结果与 noise10 基本一致（主排序不变）：
- camera: `v2xregpp(best) > baseline` 的增益很小；freealign/vips/cbm 仍明显落后。
- lidar: `v2xregpp(best)` 继续接近 oracle，freealign 次之，vips/cbm 基本回到 baseline 附近。

（完整数值见 `outputs/benchmark_unified_20260220/opv2v_dual_suite_ap_reg.csv`）

---

## 5. 有初值 / 无初值（Table III, `te_re`）

完整 22 行见：
- `outputs/benchmark_unified_20260220/dair_table3_best_te_re.csv`

分组观察（best success@2m 的粗聚合）：
- `needs_init`（ICP/PICP）平均约 `81.52%`
- `no_init_global`（FGR/Quatro/Teaser++）平均约 `37.59%`
- `no_init_object_matching`（V2X-Reg/V2X-Reg++）平均约 `58.95%`
- `has_init_gt` / `mixed_or_unknown`（VIPS/CBM 系）在不同 noise 和设置下波动较大

关键行（best success@2m）：
- ICP-noise0: `100.00%`
- PICP-noise0: `100.00%`
- V2X-Reg++ GT25: `67.84%`
- V2X-Reg++ PP15: `57.27%`
- V2X-Reg++ SC15: `58.92%`

说明：
- HKUST 三条无初值全局法（FGR/Quatro/Teaser++）仍是当前主差距点。
- V2X-Reg++ PP/SC 在 `te_re` 口径下可稳定进入可用区间，但与 GT 线仍有 gap。

---

## 6. 串起来看：实验目标链路与当前状态

1. 目标 A：先证明“注册是否能真正改善协同感知 AP”。
- 结论：在 LiDAR（DAIR+OPV2V）成立，在 camera 上成立很弱。

2. 目标 B：再比较“有初值 vs 无初值”注册路线。
- 结论：有初值的传统 ICP/PICP 在 Table III 下更强；无初值全局法（HKUST）仍偏弱；无初值对象级（V2X-Reg/V2X-Reg++）处于中间。

3. 目标 C：把注册质量与 AP 关联起来。
- 结论：LiDAR 上 AP 与配准指标一致性强；camera 上出现“AP增益很小且配准误差不稳定”的现象，是后续主攻点。

4. 目标 D：确保所有对比在统一条件且可追溯。
- 结论：本轮统一主范围已满足（核心方法缺口=0），并形成脚本化可复算产物。

---

## 7. 复现命令（统一口径）

重新生成本文所有聚合产物：

```bash
python3 tools/build_unified_benchmark_report.py
```

可选自定义输入路径：

```bash
python3 tools/build_unified_benchmark_report.py \
  --dair-sweep outputs/pose_sweep_1to10_full_gpuvoxel20260218_results.jsonl \
  --opv2v-run-dir outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1 \
  --table3-md docs/operations/table3_paper3737_repro_status.md \
  --out-dir outputs/benchmark_unified_20260220
```
