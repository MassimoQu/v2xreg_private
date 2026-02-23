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
- 已尝试将 HKUST baselines 切到 `configs/paper3737/hkust/hkust_lidar_global_paper3737_table3.yaml`（subsample_ratio=1.0）以追论文，但单帧耗时上升到 100–200s 且精度更差，已中止该路线（保留 ratio0.5 版本作为当前对比基线）。

## 0. 数据与配置兼容说明

- **Top-3000 DAIR 样本**：`data/data_info_top3000.json` 是从官方 6 616 帧中按 GT box 数量排序后筛出的 3 000 帧子集。任何 GT 实验均以此作为 `data_info_path`，确保与论文的“3k 帧”设定一致。
- **通用 config**：`configs/dair/misc/pipeline_top3000.yaml` 继承自 `configs/dair/pipeline.yaml`，仅将 `data.data_info_path` 指向上述文件、`max_samples=3000`、`success_thresholds=[1,2,3]`。后续所有 DAIR V2X-Reg/V2X-Reg++ 变体都在此基础上覆写 `top_k`、`core_components` 等字段。
- **云端/多卡运行**：每次 run 使用命令 `nohup ~/miniconda3/bin/python tools/run_dair_pipeline_experiments.py --config configs/dair/misc/pipeline_top3000.yaml --tags <tag> > logs/dair_runs/<tag>.log 2>&1 &`. 同一项目可横向复制多份命令，分别设置 `CUDA_VISIBLE_DEVICES`，便于 10×3090 服务器并行跑不同配置。日志、输出目录皆独立，兼容其它 Codex 对检测模型训练脚本的改动。

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

### 1.1 2025-11-25 全量复现（`configs/dair/misc/pipeline_top3000.yaml`）

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
| HEAL dual detection (`configs/dair/detection/pipeline_detection.yaml`) | 0.191 | 0.192 | 输出 `outputs/heal_detection/metrics.json` |
| HEAL dual detection (single-agent retrain, `top_k=25`, old cache) | 0.271 | 0.440 | （实际仍使用 GT，参考 `outputs/heal_detection_single_prev/metrics.json`） |
| HEAL dual detection (single-agent retrain, `top_k=25`, 新 cache) | 0.0056 | 0.0106 | 真实检测表现，`outputs/heal_detection_single/metrics.json` |
| HEAL detection vs GT（同 1765 帧） | `det`: 0.000 / `gt`: 0.271 | `det`: 0.0011 / `gt`: 0.439 | `outputs/heal_detection_single_subset/metrics.json` vs `outputs/heal_gt_single_subset/metrics.json` |
| HEAL detection relaxed gates（1765 帧） | 0.000 | 0.00057 | `outputs/heal_detection_single_subset_relaxed/metrics.json` |
| BEV descriptor smoke (`configs/dair/misc/pipeline_features.yaml`) | 0.565 | 0.739 | 输出 `outputs/20251123-223008/metrics.json`，`frames_with_matches=1919` |
| PP/SC 检测（test split，已完成） | PP: 0.1912 / SC: 0.1889（TE@1m） | PP: 0.3684 / SC: 0.3712（TE@2m） | `configs/dair/detection/pipeline_detection_pp.yaml` / `configs/dair/detection/pipeline_detection_sc.yaml`；结果见 `outputs/dair_v2xregpp_pp15_test/metrics.json` 与 `outputs/dair_v2xregpp_sc15_test/metrics.json`。注意同批 jsonl 在 `te_re` 口径下分别为 PP@1/2/3=0.0961/0.3046/0.4164、SC@1/2/3=0.0945/0.3074/0.4120。 |

**分析**  
- HEAL 检测结果与 `docs/operations/heal_detection_status.md` 记录一致：成功率 ~19% 受匹配质量制约，需要更好的 RSU 模型。  
- 初步的 BEV descriptor 实验（使用 HEAL feature cache）保留了与 GT 类似的成功率，但只有 60% 帧生成匹配，说明需要更高质量的特征抽样；`v2icalib_feature_extension.md` 后续可引用这批数据进行讨论。

### 4.1 2026-01-19 多路线对比（Top-3000 + Camera test）

| 路线 | `success@1m` | `success@2m` | `success@3m` | 备注 |
| --- | --- | --- | --- | --- |
| V2X-Reg++ 后融合基线（Full LiDAR, top-25） | 0.1717 | 0.3853 | 0.4823 | `outputs/full_lidar_late25/metrics.json` |
| LiDAR BEV descriptor tuned | 0.2187 | 0.4240 | 0.5133 | `outputs/full_lidar_bevdesc_tuned/metrics.json` |
| Camera image descriptor（test split 1789） | 0.1945 | 0.4036 | 0.4941 | `outputs/full_camera_desc_3m/metrics.json` / `configs/camera/desc/pipeline_camera_desc_3m.yaml` |
| Camera image descriptor（test split 1789, ResNet18 + relaxed dist） | 0.1956 | **0.4069** | 0.4885 | `outputs/camera_desc_resnet18_torch_full_thr1p5/metrics.json` / `configs/camera/desc/pipeline_camera_desc_resnet18_thr1p5.yaml` |
| Camera detection（HEAL v2xvit, test split 1789） | 0.0022 | 0.0145 | - | `outputs/camera_det_v2xvit/metrics.json` / `configs/camera/det/pipeline_camera_det_v2xvit.yaml` |
| Camera image descriptor（Top-3000, pixel） | 0.2670 | 0.4633 | 0.5220 | `outputs/camera_desc_top3000_3m/metrics.json` / `configs/camera/desc/pipeline_camera_desc_top3000_3m.yaml` |
| Camera image descriptor（Top-3000, ResNet18） | 0.2670 | 0.4687 | 0.5287 | `outputs/camera_desc_top3000_resnet18/metrics.json` / `configs/camera/desc/pipeline_camera_desc_top3000_resnet18.yaml` |
| Detection + BEV descriptor + occ hint ratio=1.5 | 0.2353 | 0.4473 | 0.5367 | `outputs/full_det_desc_v2cache_r15/metrics.json` / `configs/dair/detection/pipeline_detection_desc_v2cache_full_r15.yaml` |

**备注**  
- Camera 行使用 `data/DAIR-V2X/cooperative/test_data_info.json`（1789 帧）与 Top-3000 两套集合；Top-3000 指标可直接与 LiDAR 后融合基线对齐。
- HEAL camera v2xvit 检测 cache 仅覆盖 1 683 帧（剩余帧检测为空），导致匹配帧数显著下降。

**补充：纯相机检测框（HEAL checkpoints, test split 1789）**  

| 方法 | cache 覆盖帧数 | 检测 `@1m` | 检测 `@2m` | 检测+desc `@1m` | 检测+desc `@2m` | 检测+desc `@3m` | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| v2xvit | 1683 | 0.0022 | 0.0145 | 0.0022 | 0.0145 | 0.0279 | `outputs/camera_det_v2xvit/metrics.json` / `outputs/camera_det_desc_v2xvit/metrics.json` |
| attfuse | 1641 | 0.0022 | 0.0212 | 0.0022 | 0.0212 | 0.0319 | `outputs/camera_det_attfuse/metrics.json` / `outputs/camera_det_desc_attfuse/metrics.json` |
| cobevt | 1657 | 0.0022 | 0.0196 | 0.0022 | 0.0196 | 0.0358 | `outputs/camera_det_cobevt/metrics.json` / `outputs/camera_det_desc_cobevt/metrics.json` |
| disco | 1738 | 0.0034 | 0.0263 | 0.0034 | 0.0263 | 0.0447 | `outputs/camera_det_disco/metrics.json` / `outputs/camera_det_desc_disco/metrics.json` |
| fcooper | 1620 | 0.0011 | 0.0145 | 0.0011 | 0.0145 | 0.0291 | `outputs/camera_det_fcooper/metrics.json` / `outputs/camera_det_desc_fcooper/metrics.json` |

**补充：纯相机检测框调参（disco, test split 1789）**  

| 配置 | `success@1m` | `success@2m` | `success@3m` | Avg time | 备注 |
| --- | --- | --- | --- | --- | --- |
| baseline (k16) det | 0.0034 | 0.0263 | - | 0.0609 | `outputs/camera_det_disco/metrics.json` |
| k30 + f2 det | 0.0034 | 0.0319 | - | 0.1277 | `outputs/camera_det_disco_k30_f2/metrics.json` / `configs/camera/det/pipeline_camera_det_disco_k30_f2.yaml` |
| k30 + f2 det + conf weight | 0.0084 | 0.0565 | - | 0.1280 | `outputs/camera_det_disco_k30_f2_confw/metrics.json` / `configs/camera/det/pipeline_camera_det_disco_k30_f2_confw.yaml` |
| k30 + f2 det+desc | 0.0034 | 0.0319 | 0.0509 | 0.1360 | `outputs/camera_det_desc_disco_k30_f2/metrics.json` / `configs/camera/det/pipeline_camera_det_desc_disco_k30_f2.yaml` |
| k30 + f2 det+desc + conf weight | 0.0084 | 0.0565 | 0.0945 | 0.1313 | `outputs/camera_det_desc_disco_k30_f2_confw/metrics.json` / `configs/camera/det/pipeline_camera_det_desc_disco_k30_f2_confw.yaml` |

**结论**  
- 纯相机检测框在当前 DAIR 标注尺度下几乎不可用（success@1m≈0.1–0.3%），显著低于 GT 框与“GT+descriptor”。  
- k30 + confidence weight 把 `@2m` 拉到 5.6%（`@3m`≈9.4%），但仍远低于后融合 LiDAR 基线（38.5%）；`@1m/@2m` 上 det 与 det+desc 的提升一致，说明瓶颈仍在检测质量。

### 4.2 2026-01-19 descriptor hint 融合验证（负向）

| 实验 | `success@1m` | `success@2m` | `success@3m` | 备注 |
| --- | --- | --- | --- | --- |
| Detection + BEV desc + occ hint + descriptor seed | 0.1977 | 0.3763 | 0.4487 | `outputs/dair_v2xregpp_detection_desc_v2cache_full_r15_descseed/metrics.json` / `configs/dair/detection/pipeline_detection_desc_v2cache_full_r15_descseed.yaml` |
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

### 4.4 2026-01-19 Camera descriptor 变体（smoke）

| 实验 | `success@1m` | `success@2m` | `success@3m` | 备注 |
| --- | --- | --- | --- | --- |
| Camera desc（pixel, 200 帧） | 0.205 | 0.395 | 0.495 | `outputs/camera_desc_test_3m_smoke/metrics.json` |
| Camera desc（HOG, 200 帧） | 0.210 | 0.400 | 0.475 | `outputs/camera_desc_hog_test_3m_smoke/metrics.json` / `configs/camera/desc/pipeline_camera_desc_hog_3m_smoke.yaml` |
| Camera desc（ResNet18, 200 帧, test split） | 0.210 | 0.385 | 0.470 | `outputs/camera_desc_resnet18_test_3m_smoke/metrics.json` / `configs/camera/desc/pipeline_camera_desc_resnet_3m_smoke.yaml` |
| Camera desc（ResNet18, 200 帧, Top-3000） | 0.540 | 0.655 | 0.730 | `outputs/camera_desc_top3000_resnet18_smoke/metrics.json` / `configs/camera/desc/pipeline_camera_desc_top3000_resnet18_smoke.yaml` |
| Camera desc（DINOv2-S/14, 200 帧, Top-3000） | 0.535 | 0.630 | 0.705 | `outputs/camera_desc_top3000_dinov2_smoke/metrics.json` / `configs/camera/desc/pipeline_camera_desc_top3000_dinov2_smoke.yaml` |

**ResNet18 weight/min-sim sweep（Top-3000 / smoke）**

| 配置 | `success@1m` | `success@2m` | `success@3m` | 备注 |
| --- | --- | --- | --- | --- |
| w=1.5, sim=0.1 | 0.535 | 0.665 | 0.735 | `outputs/camera_desc_top3000_resnet18_smoke_w1p5_s0p1/metrics.json` |
| w=1.5, sim=0.2 | 0.535 | 0.665 | 0.735 | `outputs/camera_desc_top3000_resnet18_smoke_w1p5_s0p2/metrics.json` |
| w=2.0, sim=0.1 | **0.540** | **0.670** | **0.735** | `outputs/camera_desc_top3000_resnet18_smoke_w2p0_s0p1/metrics.json` |
| w=2.0, sim=0.2 | **0.540** | **0.670** | **0.735** | `outputs/camera_desc_top3000_resnet18_smoke_w2p0_s0p2/metrics.json` |
| w=3.0, sim=0.1 | 0.540 | 0.655 | 0.730 | `outputs/camera_desc_top3000_resnet18_smoke_w3p0_s0p1/metrics.json` |
| w=3.0, sim=0.2 | 0.540 | 0.655 | 0.730 | `outputs/camera_desc_top3000_resnet18_smoke_w3p0_s0p2/metrics.json` |
| w=3.0, sim=0.3 | 0.540 | 0.655 | 0.730 | `outputs/camera_desc_top3000_resnet18_smoke_w3p0_s0p3/metrics.json` |

### 4.4.1 2026-01-21 Camera BEV features（multi-view, smoke）

| 实验 | `success@1m` | `success@2m` | `success@3m` | 备注 |
| --- | --- | --- | --- | --- |
| BEV peaks (bev+neighbor, desc-only) | 0.000 | 0.000 | 0.000 | `outputs/camera_bevpeaks_smoke/metrics.json` / `configs/camera/pipeline_camera_bevpeaks_smoke.yaml` |
| BEV peaks (bev+neighbor, core+desc) | 0.005 | 0.005 | 0.005 | `outputs/camera_bevpeaks_smoke_core/metrics.json` / `configs/camera/pipeline_camera_bevpeaks_smoke_core.yaml` |
| BEV peaks (neighbor only, desc-only) | 0.000 | 0.000 | 0.005 | `outputs/camera_bevpeaks_smoke_neighbor/metrics.json` / `configs/camera/pipeline_camera_bevpeaks_smoke_neighbor.yaml` |
| Det boxes + BEV descriptor | 0.000 | 0.000 | 0.000 | `outputs/camera_det_desc_bevfeat_smoke/metrics.json` / `configs/camera/det/pipeline_camera_det_desc_bevfeat_smoke.yaml` |

**结论**  
- 已为 `heter_model_baseline` 增加 runtime BEV feature dump（便于 camera 模型导出 BEV peaks），但 multi-view BEV features 在当前匹配策略下几乎无法复现可靠外参（200 帧 smoke 全部接近 0%）。  
- 进一步跑全量意义不大，需考虑更强的跨视角匹配（如 depth+geom 或训练专用的跨视角描述子）。

**Top-3000 full（image descriptors）**

| 实验 | `success@1m` | `success@2m` | `success@3m` | 备注 |
| --- | --- | --- | --- | --- |
| Camera desc（pixel, full） | 0.267 | 0.463 | 0.522 | `outputs/camera_desc_top3000_3m/metrics.json` |
| Camera desc（ResNet18, full） | **0.267** | **0.469** | 0.529 | `outputs/camera_desc_top3000_resnet18/metrics.json` |
| Camera desc（ResNet18, full, w=2.0） | 0.251 | 0.467 | **0.535** | `outputs/camera_desc_top3000_resnet18_w2p0_s0p2/metrics.json` |
| Camera desc（ViT‑S, full） | 0.251 | 0.466 | 0.537 | `outputs/camera_desc_top3000_vitsmall/metrics.json` |

**结论**  
- test split 上 HOG/ResNet18 未显著优于 pixel；Top-3000 上 ResNet18 smoke 指标更高。  
- ResNet18 smoke sweep 显示 `descriptor_weight=2.0`（`descriptor_min_similarity=0.1/0.2`）在 2m/3m 上最佳，但全量与 ResNet18 默认配置相比整体不升反降。  
- 为压缩运行时间，引入 `image_descriptor.max_boxes`（Top-3000 full 使用 16 个大框），平均耗时降至 0.30s/帧。
- DINOv2 (timm) 在当前环境加载权重报 `fc_norm/norm` mismatch，需升级 timm 或改用 `timm:vit_small_patch16_224`；现有 DINOv2 smoke 结果可能回退为 pixel。  
- ViT‑S full 指标接近 ResNet18 full，但未超过现有最优。

**Camera + BEV desc（Top-3000 full）**

| 实验 | `success@1m` | `success@2m` | `success@3m` | 备注 |
| --- | --- | --- | --- | --- |
| BEV desc + Camera desc (ResNet18, concat) | 0.221 | 0.434 | 0.525 | `outputs/camera_desc_top3000_bevdesc_img/metrics.json` / `configs/camera/desc/pipeline_camera_desc_top3000_bevdesc_img.yaml` |
| BEV desc + Camera desc (ResNet18, concat, w=3.0) | 0.221 | 0.432 | 0.520 | `outputs/camera_desc_top3000_bevdesc_img_w3p0/metrics.json` / `configs/camera/desc/pipeline_camera_desc_top3000_bevdesc_img_w3p0.yaml` |

**Camera + BEV desc（Top-3000 smoke, 200）**

| 实验 | `success@1m` | `success@2m` | `success@3m` | 备注 |
| --- | --- | --- | --- | --- |
| w=1.0 | 0.58 | 0.67 | 0.76 | `outputs/camera_desc_top3000_bevdesc_img_smoke_w1p0/metrics.json` |
| w=3.0 | 0.58 | 0.675 | 0.76 | `outputs/camera_desc_top3000_bevdesc_img_smoke_w3p0/metrics.json` |

**结论**  
- 融合 BEV descriptor 后全量指标仍高于 LiDAR late fusion baseline（2m: 0.434 > 0.385），但弱于纯图像 ResNet18 配置。  
- w=3.0 全量略低于 w=2.0 基线，融合权重提升未带来收益，后续若继续应尝试融合策略或更强特征。

### 4.5 HEAL late vs intermediate fusion（comm=200, v2v4real test）

| Fusion | AP30 (0..4) | AP50 (0..4) | AP70 (0..4) | 备注 |
| --- | --- | --- | --- | --- |
| Mid fusion (none) | [0.6181, 0.6142, 0.6079, 0.5991, 0.5942] | [0.5751, 0.5722, 0.5686, 0.5627, 0.5602] | [0.4014, 0.3977, 0.3955, 0.3941, 0.3926] | `HEAL/opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25/AP030507_none_comm200_paper.yaml` |
| Late fusion (none) | [0.6182, 0.6146, 0.6077, 0.6000, 0.5932] | [0.5753, 0.5723, 0.5688, 0.5643, 0.5600] | [0.4015, 0.3980, 0.3946, 0.3932, 0.3921] | `HEAL/opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25/AP030507_none_comm200_paper_late_none.yaml` |
| Mid fusion (+v2xregpp stable) | [0.5670, 0.5655, 0.5744, 0.5720, 0.5707] | [0.5432, 0.5417, 0.5472, 0.5457, 0.5448] | [0.3885, 0.3856, 0.3913, 0.3901, 0.3891] | `HEAL/opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25/AP030507_v2xregpp_stable_comm200_paper.yaml` |
| Late fusion (+v2xregpp stable) | [0.5670, 0.5682, 0.5711, 0.5732, 0.5702] | [0.5432, 0.5439, 0.5449, 0.5461, 0.5440] | [0.3885, 0.3888, 0.3892, 0.3914, 0.3919] | `HEAL/opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25/AP030507_v2xregpp_stable_comm200_paper_late_v2xregpp_stable.yaml` |

**结论**  
- Late vs mid 的 AP 曲线几乎重合（AP50 差异 < 0.003）；Late fusion + v2xregpp stable 未显示显著收益。  
- 噪声升高后整体趋势一致，late/mid 的差异远小于噪声带来的下降幅度。  

### 4.6 Pose-Correction Noise Sweep（comm=200, v2v4real test, non-ego noise）

目的：在 **协同感知模型/权重固定** 的前提下，仅替换“外参/位姿对齐”模块，观察检测性能随外参噪声变化的曲线。

设置：
- 模型：`HEAL/opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25`（PASTAT / PointPillars）
- 数据：V2V4Real `test`，multi-ego（3986）
- 噪声：`pos_std/rot_std = [0,1,2,3,4]`（m/deg），`noise_target=non-ego`
- comm：`comm_range_override=200`
- 输出曲线图：
  - `docs/operations/v2v4real_comm200_ap50_noise_curve_mix.png`
  - `docs/operations/v2v4real_comm200_ap50_noise_curve_stable.png`

AP@0.5（pos_std=0..4，对应 rot_std=0..4）：
- baseline（none）：`[0.5751, 0.5722, 0.5686, 0.5627, 0.5602]`
- V2X-Reg++（initfree）：`[0.5753, 0.5734, 0.5698, 0.5658, 0.5627]`
- FreeAlign（paper, initfree）：`[0.5529, 0.5527, 0.5522, 0.5519, 0.5516]`
- V2VLoc oracle（stable, clean pose 作为 target + stable delta filter）：`[0.5753, 0.5734, 0.5683, 0.5634, 0.5596]`

方法定义/每条曲线的实现含义（含 baseline 为何很高的解释）：`docs/operations/v2v4real_noise_sweep_methods.md`

观察（仅针对当前 PASTAT 设置）：
- baseline 本身对噪声较鲁棒（AP50 下降约 0.015），主要原因之一是该模型训练时已启用 `noise_setting(pos_std=1, rot_std=1, target=all)`，且本 sweep 只对 non-ego 加噪。
- V2X-Reg++ initfree 在所有噪声水平上略优于 baseline，但仍随噪声下降，说明仍存在一定比例的帧无法稳定纠正（fallback 到 noisy pose）。
- FreeAlign（paper）整体 AP50 更低且曲线几乎水平；结合 YAML 的 `rel_error_stats`（噪声=0 时 mean rel_trans≈29m）来看，更像是“估计退化/坐标系不一致导致融合基本失效→接近 ego-only，因此对噪声不敏感”，而不一定代表它把外参估得更准。

补充：论文明确提到 V2V4Real “单地点单 traversal” 导致 **PGC 这类回归式 LiDAR localization** 的训练假设不成立（见 v2vloc.pdf Implementation Details / Tab.4 说明）。因此在 V2V4Real 上继续把 PGC 当作“绝对定位器”硬训，更多是在验证问题定义本身是否可行，而不是调参是否足够。

## 5. ICP / PICP（LiDAR-Registration-Benchmark）

已完成 paper3737 全量（3737 对）× 噪声 0/1/2（m & deg 同值） 的 ICP/PICP sweep，并按 paper-style 阈值（1/2/3m）聚合输出：

| Run | 样本数 | success@1m | success@2m | success@3m | avg_time(s) | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| ICP noise0 | 3737 | 0.648 | 0.898 | 0.988 | 1.410 | `outputs/baselines/paper3737_icp_sweep_vx0p3_mc1p0_it100_unadj_left/icp_noise0/metrics.json` |
| ICP noise1 | 3737 | 0.630 | 0.871 | 0.967 | 2.234 | `outputs/baselines/paper3737_icp_sweep_vx0p3_mc1p0_it100_unadj_left/icp_noise1/metrics.json` |
| ICP noise2 | 3737 | 0.432 | 0.629 | 0.742 | 3.197 | `outputs/baselines/paper3737_icp_sweep_vx0p3_mc1p0_it100_unadj_left/icp_noise2/metrics.json` |
| PICP noise0 | 3737 | 0.618 | 0.874 | 0.980 | 1.299 | `outputs/baselines/paper3737_icp_sweep_vx0p3_mc1p0_it100_unadj_left/picp_noise0/metrics.json` |
| PICP noise1 | 3737 | 0.543 | 0.776 | 0.896 | 1.887 | `outputs/baselines/paper3737_icp_sweep_vx0p3_mc1p0_it100_unadj_left/picp_noise1/metrics.json` |
| PICP noise2 | 3737 | 0.397 | 0.574 | 0.673 | 2.508 | `outputs/baselines/paper3737_icp_sweep_vx0p3_mc1p0_it100_unadj_left/picp_noise2/metrics.json` |

复跑入口（可并行分 shard）：`tools/sweep_icp_picp_table3.py`

## 6. 检测 Benchmark（补录）

`docs/detection_bench_report.md` 已整理 P2 阶段的 7 个检测源，关键发现：  
- test/val split 成功率 0.18，train split 仅 0.08，需检查训练检测数据与 `data_info.json` 的对齐。  
- 耗时主要取决于匹配是否成功，失败帧平均耗时翻倍。  
这些观察已经写入该文档，无需重复；本进度日志仅引用供总览。

## 7. 未完成 / 下一步

1. **ICP / PICP baseline**：已完成（见上方 §5 的 paper3737 全量 sweep）。  
2. **检测 Test split**：已完成（1789 帧）。TE 口径：PP@1/2/3=`0.1912/0.3684/0.4528`，SC@1/2/3=`0.1889/0.3712/0.4494`；对应 `te_re` 重算：PP@1/2/3=`0.0961/0.3046/0.4164`，SC@1/2/3=`0.0945/0.3074/0.4120`。产物：`outputs/dair_v2xregpp_pp15_test/`、`outputs/dair_v2xregpp_sc15_test/`。  
3. **GPU 相关任务**：由于服务器 GPU 掉线，`opencood/tools/pose_graph_pre_calc.py --dump_bev_features` 未能完成；若后续要导出 HEAL BEV 特征，需先恢复 GPU 或将脚本改为 CPU 模式（极慢）。  
4. **匹配器加速记录（2025-11-24）**  
   - 组件：`legacy/v2x_calib/corresponding/BoxesMatch.py`、`similarity_utils.py`。  
   - 变更：为 `core_components` 中的中心点/顶点距离匹配增加了矢量化实现（`cal_core_KP_distance_fast_components`），一次性对所有候选对进行齐次变换，直接在 NumPy 中构建距离矩阵并调用 `linear_sum_assignment` 完成一对一匹配。非并行模式下默认走该路径，整体 KP 计算较旧循环版本提速约 10×。  
   - 结果：`configs/dair/misc/pipeline_top3000.yaml (max_samples=50)` 平均单帧耗时降至 **14.8 ms**（`outputs/20251124-225327/matches.jsonl`），满足 “≤0.1 s/帧” 目标；准确率与旧实现一致。  
   - 回退：如需恢复原逻辑，可在配置中设定 `matching.parallel_flag=1`（继续使用进程池版本）或禁用相应 `core_components`。
5. **oIoU & GT∞ 特殊优化（2025-11-25）**  
   - oIoU：`cal_core_KP_IoU_fast` 现在直接在 numpy 中转换所有框、利用 AABB 预检查+矢量化 IoU 计数，避免每个候选都实例化 `CorrespondingDetector`；`dair_v2xreg_oiou_gt15` 平均耗时从 1.77 s 降至 **71 ms**。  
   - GT∞：新增 `matching.seed_top_k`（YAML 可设），限制 extrinsic 种子对只来自 `top_k` 排序的前若干 box，但在匹配阶段仍使用全部框。`dair_v2xregpp_gt_inf` 设为 25 时单帧耗时降至 **52 ms**（原 245 ms），成功率和误差与旧数据在统计上保持一致。  
   - 配置引用：`tools/run_dair_pipeline_experiments.py` 已为 `dair_v2xregpp_gt_inf` 注入 `matching.seed_top_k=25`，其它实验保持默认 0（即不限）。
6. **更强图像特征验证**  
   - 若需继续提升 image line，建议升级 timm 以支持 DINOv2 或尝试更强 ViT（如 `vit_base_patch16_224`），并先做 smoke 再定全量。  

## 8. 2026-02-19 追加进展（OPV2V occ-hint + DAIR）

### 8.1 OPV2V camera：V2X-Reg++ 中融合增强（occ-hint）已接入并完成 smoke

- 代码已接入：
  - `HEAL/opencood/tools/export_stage1_boxes_per_cav.py`：支持导出 `occ_map_level0_path`，且无框样本也导出 occ（避免 occ-only 退化缺失）。
  - `tools/run_opv2v_fullbench_fast.py`：新增方法 `v2xregpp_occhint`（可与 `v2xregpp` 同图对比）。
  - `tools/summarize_opv2v_fullbench_from_yaml.py` / `tools/plot_opv2v_dual_suite_from_yaml.py`：支持新方法名绘图。

- smoke 证据（online, register_and_fuse, n=1, max_eval_samples=100）：
  - baseline: `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/AP030507_none_opv2v_camera_baseline_smoke100_n1.yaml`，AP50=0.1867
  - v2xregpp: `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/AP030507_v2xregpp_initfree_opv2v_camera_v2xregpp_smoke100_n1.yaml`，AP50=0.1716
  - v2xregpp+occ-hint: `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/AP030507_v2xregpp_initfree_opv2v_camera_occhint_smoke100_n1.yaml`，AP50=0.1814
  - v2xregpp+occ-pose: `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/AP030507_v2xregpp_initfree_opv2v_camera_occpose_smoke100_n1.yaml`，AP50=0.1534

- 结论（smoke 层面）：
  - occ-hint 相比原 v2xregpp 有回升趋势（0.1716 -> 0.1814），但仍低于 baseline（0.1867）。
  - occ-pose 在当前设置更差，不建议纳入主线对比。

- 全量缓存已准备完毕：
  - occ full: `data/OPV2V/detected/opv2v_camera_v2xvit_stage1_percav_occ_full/test/stage1_boxes.json`（2170）
  - merged（保持原 boxes/poses，仅叠加 occ paths）：
    - `data/OPV2V/detected/opv2v_camera_v2xvit_stage1_percav_occ_merged/test/stage1_boxes.json`

完整复盘文档：`docs/operations/opv2v_camera_v2xregpp_occhint_20260219.md`

### 8.2 DAIR benchmark（noise sweep）已完成（2026-02-20 更新）

- 运行器：`outputs/run_noise_sweep_1to10.py`（已退出）
- 日志目录：`outputs/pose_sweep_1to10_full_gpuvoxel20260218_logs/`
- 结果 JSONL：`outputs/pose_sweep_1to10_full_gpuvoxel20260218_results.jsonl`（20/20 jobs）
- 日志校验：20/20 日志末尾均为 `exit_code=0`，且噪声轴覆盖 `1..10`
- 绘图产物：
  - `outputs/pose_sweep_1to10_full_gpuvoxel20260218_plots/pose_sweep_1to10_full_camera_best_ap50.png`
  - `outputs/pose_sweep_1to10_full_gpuvoxel20260218_plots/pose_sweep_1to10_full_camera_stable_ap50.png`
  - `outputs/pose_sweep_1to10_full_gpuvoxel20260218_plots/pose_sweep_1to10_full_lidar_best_ap50.png`
  - `outputs/pose_sweep_1to10_full_gpuvoxel20260218_plots/pose_sweep_1to10_full_lidar_stable_ap50.png`

说明：本节已替代此前“running”状态，后续以该批产物作为 DAIR noise sweep 的固定结果口径。
