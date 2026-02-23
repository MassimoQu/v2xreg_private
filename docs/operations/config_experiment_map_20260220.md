# Config & Experiment Map (2026-02-20)

更新: 2026-02-20 23:20

这份文档把“配置文件很多、实验目的分散”的问题压缩成一个统一索引：
- 每条实验线回答 4 件事：为什么做、用哪些 config、最新结果在哪、当前结论是什么。
- 统一以最新可追溯产物为准；历史/partial 结果仅用于辅助，不进入主对比。

---

## 1. 主实验线总览

| Track | 入口 config / 脚本 | 主要目标 | 最新可信结果 | 当前结论 |
| --- | --- | --- | --- | --- |
| DAIR pose+AP 全量噪声 | `outputs/run_noise_sweep_1to10.py` | 在 DAIR 上统一比较注册方法对 AP 与配准的联动影响（camera/lidar） | `outputs/pose_sweep_1to10_full_gpuvoxel20260218_results.jsonl` | lidar 线显著收益；camera 线收益很弱 |
| OPV2V online fullbench | `tools/run_opv2v_fullbench_fast.py` + autopilot | 在 online/register_and_fuse 条件下评估双模态双 sweep 的方法稳定性 | `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/` | lidar 上 v2xregpp/freealign 有效，camera 提升有限 |
| Table III (paper3737) 注册复现 | `configs/paper3737/dair/*`, `tools/sweep_*_table3.py` | 在 3737 对样本上对齐论文注册主表（含时间/成功率/误差） | `docs/operations/table3_paper3737_repro_status.md` | PP/SC 在 `te_re` 下可用；HKUST 三基线仍偏离论文 |
| DAIR PP/SC test split 检测线 | `configs/dair/detection/pipeline_detection_pp.yaml`, `configs/dair/detection/pipeline_detection_sc.yaml` | 验证检测缓存对 V2X-Reg++ 注册成功率的影响 | `outputs/dair_v2xregpp_{pp,sc}15_test*/metrics.json` | 已完成；TE 与 TE_RE 口径差异需显式标注 |
| Camera descriptor 系列 | `configs/camera/desc/*` | 尝试纯视觉描述子提升 camera 注册稳定性 | `outputs/camera_desc_*` 系列 | smoke 常有局部收益，但全量收益不稳定 |
| Camera detection 系列 | `configs/camera/det/*` | 评估纯相机检测框可否支撑稳定注册 | `outputs/camera_det_*` 系列 | 当前仍远弱于 lidar 线 |
| Midfusion + occ-hint | `configs/dair/midfusion/*`, `docs/operations/v2xregpp_midfusion_occ_hint.md` | 验证 occ-hint 是否改善配准/融合 | `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1` (camera occhint append) | camera 有小幅正增益，但尚不足以改变主结论 |
| HKUST/V2I-CALIB 对照 | `configs/hkust/*`, `configs/paper3737/hkust/*` | 对齐第三方基线与本仓路线的公平比较 | `outputs/hkust_teaser/*` | 时间/精度口径仍未完全对齐，需继续收敛 |
| 全矩阵有/无初值 + HKUST 下游拼跑 | `tools/run_opv2v_fullbench_fast.py`, `tools/build_fullmatrix_benchmark_report.py` | 在统一条件下把 with-init/no-init/HKUST 方法与协同感知 AP+配准打通 | `outputs/benchmark_fullmatrix_20260220/*`, `docs/operations/fullmatrix_init_noinit_hkust_benchmark_status_20260220.md`, `docs/operations/lidarreg_noop_root_cause_and_rerun_20260224.md` | 已落地统一长表与出图；full-condition 补跑进行中 |

---

## 2. 关键配置簇与用途

### 2.1 `configs/dair/`
- 用途：DAIR 主线（GT / detection / midfusion / late / variants）。
- 典型入口：
  - `configs/dair/pipeline.yaml`
  - `configs/dair/detection/pipeline_detection_pp.yaml`
  - `configs/dair/detection/pipeline_detection_sc.yaml`
  - `configs/dair/midfusion/pipeline_midfusion_detection_bevpeaks_occscore_v2.yaml`
- 结论：是“DAIR 主实验线”默认入口；跨 config 对比必须先锁 split/cache/noise 口径。

### 2.2 `configs/paper3737/dair/`
- 用途：Table III 对齐的 DAIR-3737 复现专用配置。
- 典型入口：
  - `configs/paper3737/dair/pipeline_paper3737_gt15.yaml`
  - `configs/paper3737/dair/pipeline_paper3737_pp15.yaml`
  - `configs/paper3737/dair/pipeline_paper3737_sc15.yaml`
- 结论：所有 PP/SC/GT 的论文对齐比较都应回到这条线，且用 `te_re` 主口径。

### 2.3 `configs/paper3737/hkust/`
- 用途：FGR/Quatro/Teaser++ 等全局法基线（paper3737）。
- 典型入口：
  - `configs/paper3737/hkust/hkust_lidar_global_paper3737_table3_ratio0p5.yaml`
- 结论：当前仍是主要 mismatch 来源（尤其时间列）。

### 2.4 `configs/hkust/`
- 用途：HKUST 数据集 pipeline 与 object-level 对照。
- 结论：更多用于横向 sanity/迁移，不直接替代 Table III 主线。

### 2.5 `configs/camera/`
- 用途：camera-only 描述子、检测器、LoFTR/GT baseline 等分支。
- 子簇：
  - `configs/camera/desc/`
  - `configs/camera/det/`
  - `configs/camera/loftr/`
  - `configs/camera/gt/`
- 结论：用于 camera 弱项诊断与 ablation，不应与 lidar 主线混合下结论。

### 2.6 `configs/exp/`
- 用途：一次性实验、局部假设验证。
- 结论：保留记录价值，但不作为 canonical 入口。

---

## 3. 这些实验串起来到底在做什么

统一目标链路是：

1. 先在 DAIR/OPV2V 两个数据集上确认“注册是否真的能改善协同 AP”。
2. 再用 Table III 的注册主表把“方法本体能力”拆出来，区分有初值/无初值路线。
3. 最后把 AP 与配准质量重新对齐，筛掉“数值看起来高但机制无效/口径不一致”的结果。

当前阶段结论：
- lidar 路线已经形成稳定主结论（v2xregpp/freealign 有效，vips/cbm 在当前 online 条件下弱）。
- camera 路线仍是主瓶颈（增益小且稳定性差），需要作为下一阶段主攻对象。
- HKUST baseline 对齐问题仍未闭环，是论文级对齐的主要剩余工作。

---

## 4. 与统一对比文档的关系

本索引是“配置与目标地图”；统一结果与证据链在：
- `docs/operations/unified_benchmark_contract_and_comparison_20260220.md`

如果只需要看最终对比，用上面的统一文档。
如果要追溯“这个结果对应哪些 config 与目的”，回到本索引。
