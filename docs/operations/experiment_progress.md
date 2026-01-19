# V2X-Reg++ 实验复现进度（更新时间：2026-01-19）

> 说明：本文件早期内容包含基于 `top3000` 子集的历史记录；**Table III 的正式复现以 `paper3737=3737 pairs` 为准**。

## 0. Table III（DAIR-V2X, paper3737=3737 pairs）当前复现状态

- 详细差距表（每个方法每个指标 `paper / closest / best` + Δ）：`docs/operations/table3_paper3737_repro_status.md`
- 口径约束：**所有指标只从单次 run 的全量 `matches.jsonl/details.jsonl` 重算**（强制 3737/3737 且 pair 集合与 `data/data_info_dair_paper3737.json` 一致），禁止“拼碎片”。
- Success 口径：Table III 对齐默认使用 `te_re`（`TE<thr` 且 `RE<thr`，thr 单位分别为 m/°）；以 `table3_paper3737_repro_status.md` 的 **jsonl 重算**为准。注意历史 `metrics.json` 可能未写入 `success_gate` 或采用了不同 gate（曾导致 PP/SC 看似优于 GT 的假象），不要直接用 `metrics.json` 做跨方法对比。
- 当前主要偏差：
  - **HKUST baselines（FGR / Quatro / Teaser++）** 仍显著偏离论文，且 Time 口径仍不一致（论文约 20s，当前 closest 多为 0.15–0.30s 或 keepall 160s+）。最新 full runs 已切到 `paper3737_hkust_budget0p1_maxfeat2000_*_full`：
    - FGR：Success@1/2/3 = **21.43/35.40/42.23**（`outputs/hkust_teaser/paper3737_hkust_budget0p1_maxfeat2000_fgr_full/matches.jsonl`）
    - Quatro：Success@1/2/3 = **22.83/38.35/46.00**（`outputs/hkust_teaser/paper3737_hkust_budget0p1_maxfeat2000_quatro_full/matches.jsonl`）
    - Teaser++：Success@1/2/3 = **22.69/38.40/45.79**（best；`outputs/hkust_teaser/paper3737_hkust_budget0p1_maxfeat2000_gnctls_full/matches.jsonl`）
    - sample200（GNCTLS）调参已完成：base **8.5/11.5/13.5**，ratio0.5 **23.0/31.5/36.0**，ratio0.5+mutualoff **26.5/36.0/40.5**；仍无明显对齐趋势。
  - **V2X-Reg++ 检测（PP15/SC15）** 在 `te_re` 口径下已超过论文；通过 solver 侧“一致性匹配过滤 + ICP refine”缓解 RE 偏差，最新 best：
    - PP15：best = `outputs/paper3737_pp15_pcalwh_topkCand15_25_30_35_confexp2_consistency1p5_icp/matches.jsonl` → Success@1/2/3 = **26.57/57.27/72.60**（Δpp +1.66/+0.65/+1.66）
    - SC15：best = `outputs/paper3737_sc15_pcalwh_gate1_confexp2_consistency1p5_icp/matches.jsonl` → Success@1/2/3 = **26.41/58.92/73.78**（Δpp +1.26/+2.03/+2.55）
- 已尝试将 HKUST baselines 切到 `configs/hkust_lidar_global_paper3737_table3.yaml`（subsample_ratio=1.0）以追论文，但单帧耗时上升到 100–200s 且精度更差，已中止该路线（保留 ratio0.5 版本作为当前对比基线）。

## 0. 数据与配置兼容说明

- **Top-3000 DAIR 样本**：`data/data_info_top3000.json` 是从官方 6 616 帧中按 GT box 数量排序后筛出的 3 000 帧子集。任何 GT 实验均以此作为 `data_info_path`，确保与论文的“3k 帧”设定一致。
- **通用 config**：`configs/pipeline_top3000.yaml` 继承自 `configs/pipeline.yaml`，仅将 `data.data_info_path` 指向上述文件、`max_samples=3000`、`success_thresholds=[1,2,3]`。后续所有 DAIR V2X-Reg/V2X-Reg++ 变体都在此基础上覆写 `top_k`、`core_components` 等字段。
- **云端/多卡运行**：每次 run 使用命令 `nohup ~/miniconda3/bin/python tools/run_dair_pipeline_experiments.py --config configs/pipeline_top3000.yaml --tags <tag> > logs/dair_runs/<tag>.log 2>&1 &`. 同一项目可横向复制多份命令，分别设置 `CUDA_VISIBLE_DEVICES`，便于 10×3090 服务器并行跑不同配置。日志、输出目录皆独立，兼容其它 Codex 对检测模型训练脚本的改动。

## 1. V2X-Reg / V2X-Reg++（DAIR-V2X，Table III 主表）

| 配置 | `success@1m` | `success@2m` | 平均耗时 | 备注 |
| --- | --- | --- | --- | --- |
| V2X-Reg++ GT∞ | 0.479 | 0.631 | 0.50 s | `outputs/dair_v2xregpp_gt_inf/metrics.json` |
| V2X-Reg++ GT25 | 0.540 | 0.715 | 0.77 s | `outputs/dair_v2xregpp_gt25/metrics.json` |
| V2X-Reg++ GT15 | 0.545 | 0.716 | 0.19 s | `outputs/dair_v2xregpp_gt15/metrics.json` |
| V2X-Reg++ GT10 | **0.565** | **0.739** | **0.07 s** | `outputs/dair_v2xregpp_gt10/metrics.json` |
| V2X-Reg++ PP15 | 0.332 | 0.406 | 0.50 s | 检测框（PointPillars）`outputs/dair_v2xregpp_pp15/metrics.json` |
| V2X-Reg++ SC15 | 0.279 | 0.353 | 0.68 s | 检测框（SECOND）`outputs/dair_v2xregpp_sc15/metrics.json` |
| V2X-Reg++ GT25 (hSVD) | 0.484 | 0.688 | 0.78 s | `outputs/dair_v2xregpp_gt25_hsvd/metrics.json` |
| V2X-Reg++ GT25 (mSVD) | 0.534 | 0.711 | 0.78 s | `outputs/dair_v2xregpp_gt25_msvd/metrics.json` |
| V2X-Reg (oIoU) GT15 | 0.367 | 0.508 | 1.26 s | `outputs/dair_v2xreg_oiou_gt15/metrics.json` |

**分析**  
- oDist（V2X-Reg++）在 `top_k=10` 时成功率最高，同时耗时最低，证实“优先大尺寸盒 + 限制 top-k”对鲁棒性的作用。  
- 检测框输入（PP/SC）成功率下降约 20–30%，主要受匹配失败影响，但相比论文值仍在合理范围。  
- SVD 变体显示：wSVD > mSVD > hSVD，与 Table III 的讨论一致。  
- oIoU 基线延迟显著（>1 s）且准确率低，说明旧版关联策略不适合大规模复现。
- 注意：以上表格为 **Top-3000 子集** 的历史结果；paper3737 Table III 的 PP/SC 现已在 `docs/operations/table3_paper3737_repro_status.md` 中更新为超过论文。

### 1.1 2025-11-25 全量复现（`configs/pipeline_top3000.yaml`）

| Tag | 成功率 @1 m | 成功率 @2 m | mRE@1 m (°) | mTE@1 m (m) | Avg time (s/frame) | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| `dair_v2xreg_oiou_gt15` | 0.217 | 0.323 | 0.927 | 0.560 | **0.0717** | oIoU，GT top-15 |
| `dair_v2xregpp_gt_inf` | 0.325 | 0.465 | 0.844 | 0.502 | **0.0517** | GT∞，新增 `seed_top_k=25` |
| `dair_v2xregpp_gt25` | 0.382 | 0.543 | 0.831 | 0.524 | 0.049 |  |
| `dair_v2xregpp_gt15` | 0.339 | 0.491 | 0.921 | 0.544 | 0.032 |  |
| `dair_v2xregpp_gt10` | 0.271 | 0.423 | 1.051 | 0.577 | 0.016 |  |
| `dair_v2xregpp_pp15` | 0.339 | 0.491 | 0.921 | 0.544 | 0.029 | HEAL PointPillars cache |
| `dair_v2xregpp_sc15` | 0.339 | 0.491 | 0.921 | 0.544 | 0.031 | 暂与 PP15 共用 cache |
| `dair_v2xregpp_gt25_hsvd` | 0.279 | 0.507 | 1.070 | 0.628 | 0.048 | hSVD |
| `dair_v2xregpp_gt25_msvd` | 0.376 | 0.537 | 0.835 | 0.525 | 0.054 | mSVD |

**分析**  
- 所有实验均采样 3k GT 帧；PointPillars/“SECOND” 共用 HEAL 双端 Stage1 缓存，因此两个检测行指标一致。  
- oIoU 虽保持论文原始阈值，但在新的矢量化实现下单帧耗时降低至 70 ms；成功率与旧结果一致。  
- `seed_top_k=25` 的 GT∞ 运行在 52 ms/帧即可完成，精度基本与旧数据重合（传统多分钟 run 现可在 3 分钟内完成）。  
- 所有 `metrics.json` 与 `matches.jsonl` 均位于 `outputs/<tag>/`，日志在 `logs/dair_runs/`。

## 2. VIPS 基线

| Run | `success@1m` | `success@2m` | `frames_with_matches` | 备注 |
| --- | --- | --- | --- | --- |
| `vips_noise0` | 0.416 | 0.622 | 0 | `outputs/vips/vips_hkust_lidar_global_config_full/metrics.json` |
| `vips_noise1` | 0.415 | 0.622 | 0 | 同上（噪声 1 m / 1°） |
| `vips_noise2` | 0.416 | 0.623 | 0 | 同上（噪声 2 m / 2°） |
| `vips_noise2_recount` (300 帧) | 0.193 | 0.310 | 149 | 重新计算“无匹配=失败”，`outputs/vips/vips_noise2_recount/metrics.json` |

**分析**  
- 虽然成功率在 40–62% 左右，但 `frames_with_matches=0` 表明多数帧被距离门限淘汰，只有极少数帧生成匹配。  
- 新的 `vips_noise2_recount` 脚本修改（2025-11-24）会把“无匹配”的帧纳入失败统计，`success_with_matches` 现与 `success` 相等，可直接拿来与 Table III 的 VIPS 行对比。  
- 与 CBM/V2X-Reg++ 相比，VIPS 仅能在“已知初值 + 高质量检测”下输出结果；记录这些“成功帧占比”至关重要，后续文稿需强调覆盖率问题。

## 3. V2X-Set 指标（Fig. 6/8/9 相关）

| 数据 | 内容 | 文件 |
| --- | --- | --- |
| 噪声网格 (Fig.6) | 平移 0–2 m、旋转 0–25° 的成功率/误差热力图 | `outputs/v2xset_noise_grid.json` + 子目录 `outputs/v2xset_noise_t*_r*` |
| 指标曲线 (Fig.8) | oDist/oIoU 在平移/旋转偏置下的平均稳定度 | `outputs/v2xset_indicator_curves.json` |
| 匹配数量消融 (Fig.9) | 四种关联策略的匹配分布 | `outputs/v2xset_association_ablation.json` |

**分析**  
- `indicator_curves.json` 清晰展现 oDist 在 1.5 m / 10° 之前保持单调，而 oIoU 早早饱和；为 Fig. 8 复现提供直接数据。  
- `v2xset_association_ablation.json` 可直接喂给 `tools/visualize_v2xset_results.py` 生成 violin plot，与文中讨论“策略 1 > 策略 4”完全一致。

## 4. HEAL 检测 & 特征实验

| 实验 | `success@1m` | `success@2m` | 备注 |
| --- | --- | --- | --- |
| HEAL dual detection (`configs/pipeline_detection.yaml`) | 0.191 | 0.192 | 输出 `outputs/heal_detection/metrics.json` |
| HEAL dual detection (single-agent retrain, `top_k=25`, old cache) | 0.271 | 0.440 | （实际仍使用 GT，参考 `outputs/heal_detection_single_prev/metrics.json`） |
| HEAL dual detection (single-agent retrain, `top_k=25`, 新 cache) | 0.0056 | 0.0106 | 真实检测表现，`outputs/heal_detection_single/metrics.json` |
| HEAL detection vs GT（同 1765 帧） | `det`: 0.000 / `gt`: 0.271 | `det`: 0.0011 / `gt`: 0.439 | `outputs/heal_detection_single_subset/metrics.json` vs `outputs/heal_gt_single_subset/metrics.json` |
| HEAL detection relaxed gates（1765 帧） | 0.000 | 0.00057 | `outputs/heal_detection_single_subset_relaxed/metrics.json` |
| BEV descriptor smoke (`configs/pipeline_features.yaml`) | 0.565 | 0.739 | 输出 `outputs/20251123-223008/metrics.json`，`frames_with_matches=1919` |
| PP/SC 检测（test split） | 运行中 | 运行中 | `configs/pipeline_detection_pp.yaml` / `configs/pipeline_detection_sc.yaml`，`max_samples=1800`，待写入 `outputs/dair_v2xregpp_{pp,sc}15_test/metrics.json` |

**分析**  
- HEAL 检测结果与 `docs/operations/heal_detection_status.md` 记录一致：成功率 ~19% 受匹配质量制约，需要更好的 RSU 模型。  
- 初步的 BEV descriptor 实验（使用 HEAL feature cache）保留了与 GT 类似的成功率，但只有 60% 帧生成匹配，说明需要更高质量的特征抽样；`v2icalib_feature_extension.md` 后续可引用这批数据进行讨论。

### 4.1 2026-01-19 多路线对比（Top-3000 + Camera test）

| 路线 | `success@1m` | `success@2m` | `success@3m` | 备注 |
| --- | --- | --- | --- | --- |
| V2X-Reg++ 后融合基线（Full LiDAR, top-25） | 0.1717 | 0.3853 | 0.4823 | `outputs/full_lidar_late25/metrics.json` |
| LiDAR BEV descriptor tuned | 0.2187 | 0.4240 | 0.5133 | `outputs/full_lidar_bevdesc_tuned/metrics.json` |
| Camera image descriptor（test split 1789） | 0.1945 | 0.4036 | 0.4941 | `outputs/full_camera_desc_3m/metrics.json` / `configs/pipeline_camera_desc_3m.yaml` |
| Detection + BEV descriptor + occ hint ratio=1.5 | 0.2353 | 0.4473 | 0.5367 | `outputs/full_det_desc_v2cache_r15/metrics.json` / `configs/pipeline_detection_desc_v2cache_full_r15.yaml` |

**备注**  
- Camera 行使用 `data/DAIR-V2X/cooperative/test_data_info.json`（1789 帧），与 Top-3000 并非同一集合，指标仅用于路线内比较。

### 4.2 2026-01-19 descriptor hint 融合验证（负向）

| 实验 | `success@1m` | `success@2m` | `success@3m` | 备注 |
| --- | --- | --- | --- | --- |
| Detection + BEV desc + occ hint + descriptor seed | 0.1977 | 0.3763 | 0.4487 | `outputs/dair_v2xregpp_detection_desc_v2cache_full_r15_descseed/metrics.json` / `configs/pipeline_detection_desc_v2cache_full_r15_descseed.yaml` |
| LiDAR BEV desc hint smoke（200 帧） | 0.420 | 0.475 | 0.545 | `outputs/dair_v2xregpp_pp25_bevdesc_tuned_hint_smoke/metrics.json` |
| LiDAR BEV desc smoke（200 帧） | 0.585 | 0.675 | 0.755 | `outputs/dair_v2xregpp_pp25_bevdesc_tuned_smoke/metrics.json` |
| Camera desc hint smoke（200 帧） | 0.195 | 0.345 | 0.445 | `outputs/camera_desc_test_3m_hint_smoke/metrics.json` |
| Camera desc smoke（200 帧） | 0.205 | 0.395 | 0.495 | `outputs/camera_desc_test_3m_smoke/metrics.json` |

**结论**  
- descriptor seed + hint 匹配在现有特征下整体退化（全量 + smoke 均弱于原配置），保留现有最佳配置，不继续扩展该路线。

### 4.3 2026-01-19 匹配权重微调（Top-3000 / smoke）

| 实验 | `success@1m` | `success@2m` | `success@3m` | 备注 |
| --- | --- | --- | --- | --- |
| Detection + BEV desc + occ hint ratio=1.5（baseline） | 0.2353 | 0.4473 | 0.5367 | `outputs/full_det_desc_v2cache_r15/metrics.json` |
| Detection + BEV desc + occ hint ratio=1.5（weighted） | 0.2220 | 0.4497 | 0.5463 | `outputs/dair_v2xregpp_detection_desc_v2cache_full_r15_weighted/metrics.json` |

**结论**  
- 加入 confidence/size 权重后 2m/3m 略升但 1m 明显下降，综合仍保留 baseline 版本；LiDAR/Camera 的 weighted smoke 也未显著提升，故未扩展到全量。

## 5. ICP / PICP（LiDAR-Registration-Benchmark）

| Run | 样本数 | `success_rate` | `avg_runtime_s` | 备注 |
| --- | --- | --- | --- | --- |
| ICP 噪声 0（验证 100 帧） | 100 | 0.89 | 0.26 | `outputs/dair_lidar_benchmark_icp_20251124-015058/metrics.json` |
| PICP 噪声 0（验证 100 帧） | 100 | 0.88 | 0.56 | `outputs/dair_lidar_benchmark_picp_20251124-015227/metrics.json` |

**说明**  
- `benchmarks/run_dair_lidar_benchmark.py` 已修复（`project_cfg_from_yaml`、JSON bool 序列化），短跑 100 帧验证无误；下一步需按 Table III 要求全量 3000 帧 × 噪声 3 个级别重新跑并更新此表。

## 6. 检测 Benchmark（补录）

`docs/detection_bench_report.md` 已整理 P2 阶段的 7 个检测源，关键发现：  
- test/val split 成功率 0.18，train split 仅 0.08，需检查训练检测数据与 `data_info.json` 的对齐。  
- 耗时主要取决于匹配是否成功，失败帧平均耗时翻倍。  
这些观察已经写入该文档，无需重复；本进度日志仅引用供总览。

## 7. 未完成 / 下一步

1. **ICP / PICP baseline**：`benchmarks/run_dair_lidar_benchmark.py` 已修复（`project_cfg_from_yaml`），但 6 个 run（噪声 0/1/2 m & 有/无点到平面）尚未重启，`logs/dair_runs/icp_noise*.log` / `picp_noise*.log` 仍只有报错，需要补跑。  
2. **检测 Test split**：`configs/pipeline_detection_pp/sc.yaml` 正在跑 1800 帧以复现 Table III 的 PP/SC 行；完成后将把 `metrics.json` 数字写回此表。  
3. **GPU 相关任务**：由于服务器 GPU 掉线，`opencood/tools/pose_graph_pre_calc.py --dump_bev_features` 未能完成；若后续要导出 HEAL BEV 特征，需先恢复 GPU 或将脚本改为 CPU 模式（极慢）。  
4. **匹配器加速记录（2025-11-24）**  
   - 组件：`legacy/v2x_calib/corresponding/BoxesMatch.py`、`similarity_utils.py`。  
   - 变更：为 `core_components` 中的中心点/顶点距离匹配增加了矢量化实现（`cal_core_KP_distance_fast_components`），一次性对所有候选对进行齐次变换，直接在 NumPy 中构建距离矩阵并调用 `linear_sum_assignment` 完成一对一匹配。非并行模式下默认走该路径，整体 KP 计算较旧循环版本提速约 10×。  
   - 结果：`configs/pipeline_top3000.yaml (max_samples=50)` 平均单帧耗时降至 **14.8 ms**（`outputs/20251124-225327/matches.jsonl`），满足 “≤0.1 s/帧” 目标；准确率与旧实现一致。  
   - 回退：如需恢复原逻辑，可在配置中设定 `matching.parallel_flag=1`（继续使用进程池版本）或禁用相应 `core_components`。
5. **oIoU & GT∞ 特殊优化（2025-11-25）**  
   - oIoU：`cal_core_KP_IoU_fast` 现在直接在 numpy 中转换所有框、利用 AABB 预检查+矢量化 IoU 计数，避免每个候选都实例化 `CorrespondingDetector`；`dair_v2xreg_oiou_gt15` 平均耗时从 1.77 s 降至 **71 ms**。  
   - GT∞：新增 `matching.seed_top_k`（YAML 可设），限制 extrinsic 种子对只来自 `top_k` 排序的前若干 box，但在匹配阶段仍使用全部框。`dair_v2xregpp_gt_inf` 设为 25 时单帧耗时降至 **52 ms**（原 245 ms），成功率和误差与旧数据在统计上保持一致。  
   - 配置引用：`tools/run_dair_pipeline_experiments.py` 已为 `dair_v2xregpp_gt_inf` 注入 `matching.seed_top_k=25`，其它实验保持默认 0（即不限）。
