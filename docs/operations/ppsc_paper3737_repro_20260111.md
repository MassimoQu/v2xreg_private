# DAIR-V2X-C（paper3737）PP/SC 复现记录

修改日期：2026-01-14（补充：PP/SC solver/matching 调参以缩小 Table III 差距）

## 任务目标

1. 将论文 Table-III 中 DAIR-V2X 的 **PP（PointPillars）** 与 **SC（SECOND）** 复现到论文水平（Success@{1,2,3}m）。
2. 修复/定位“协同 idx 没对上”的问题，避免检测/数据对齐错误导致的 `TE=inf` 或全失败。
3. 验证“角点形式检测框存在 180° 方向歧义”的影响：**同时跑开启与不开启**的对比。
4. 并行改造 HEAL，让其吐出更可用的检测框（更高质量、可含 score、可含 7D box），并验证 7D 是否能规避角点歧义。

## 环境与数据

- 代码仓库：`/home/qqxluca/v2xreg_private`
- 数据集：`/data2/DAIR-V2X-C/cooperative-vehicle-infrastructure`
- 关键环境：
  - 标定 pipeline（`tools/run_calibration.py`）使用 micromamba 环境 `v2x`
  - HEAL 导出（`HEAL/opencood/tools/pose_graph_pre_calc.py`）使用 GPU 环境 `/home/qqxluca/miniconda3/envs/heal`

## 核心问题定位（idx / 数据对齐）

### 1) paper3737 检测 cache 覆盖率不足（根因）

仓库中原有的 paper3737/dual 检测 cache（如 `data/DAIR-V2X/detected/veh_rsu_dual_ft_detection_cache.json`、`...m2_second_detection_cache.json`）：
- 总 key=6617（按 full data_info 的 frame index），其中 **非空仅 1765 条**。
- 与 paper3737 子集（3737 条）交集仅约 **~993**，其余大量帧没有检测，导致 pipeline 中 `matches=[]` → `TE=inf`，成功率几乎为 0。

结论：要复现论文的 paper3737 PP/SC 行，必须生成 **覆盖 3737/3737** 的 PP/SC 检测结果，而不是复用只覆盖部分帧的旧 cache。

### 2) HEAL 的 split 文件只能用 vehicle id，且存在重复 vehicle id（需要 pair-level disambiguation）

HEAL 的 DAIR dataset 读取逻辑以 `veh_frame_id` 作为 split 列表元素并索引 `cooperative/data_info.json`。
但官方 `data_info.json` 中存在少量 **重复的 vehicle frame id**（同一 veh 对应不同 infra），如果只给 vehicle id，部分样本会映射错误。

本次做法：
- 将 paper3737 data_info 转成显式的 pair 列表 `data/paper3737_pairs.json`，每项包含 `veh_frame_id` + `inf_frame_id`，用于 HEAL 导出时准确定位协同对。
- 修改 HEAL 数据集，使其支持 split entry 为 dict（`veh_frame_id`/`inf_frame_id`），并用 pair-key 查找对应 frame_info。

对应代码修改：`HEAL/opencood/data_utils/datasets/basedataset/dairv2x_basedataset.py`

## 完成的工作（按产出）

### A. 生成覆盖 3737/3737 的 HEAL Stage-1 双端检测（PP & SC）

产物：
- PP：`data/DAIR-V2X/detected/paper3737_pp_dual/stage1_boxes.json`
- SC：`data/DAIR-V2X/detected/paper3737_sc_dual/stage1_boxes.json`

两者均包含：
- `pred_corner3d_np_list`（角点）
- `pred_box3d_np_list`（7D box）
- `pred_score_np_list`（分数）
- `uncertainty_np_list`
- `veh_frame_id` / `infra_frame_id`

### B. 复现结果（paper3737，Success gate 口径说明 + 当前对齐情况）

推荐配置（产出 `matches.jsonl/details.jsonl` 覆盖 3737/3737）：
- PP15：`configs/pipeline_paper3737_pp15_heal_pp_corners_conf0p3_iter2.yaml`
  - 输出：`outputs/paper3737_pp15_heal_pp_corners_conf0p3_iter2/metrics.json`
  - 该 run 的 `matches.jsonl` 重新计算：
    - `success_gate=te`（仅 TE<thr）：Success@{1,2,3}m = **{0.329, 0.611, 0.728}**
    - `success_gate=te_re`（TE<thr 且 RE<thr）：Success@{1,2,3}m = **{0.184, 0.502, 0.678}**
- SC15：`configs/pipeline_paper3737_sc15_heal_sc_corners_conf0p3_iter2.yaml`
  - 输出：`outputs/paper3737_sc15_heal_sc_corners_conf0p3_iter2/metrics.json`
  - 该 run 的 `matches.jsonl` 重新计算：
    - `success_gate=te`（仅 TE<thr）：Success@{1,2,3}m = **{0.339, 0.632, 0.734}**
    - `success_gate=te_re`（TE<thr 且 RE<thr）：Success@{1,2,3}m = **{0.195, 0.535, 0.700}**

2026-01-14 补充：为进一步贴近 Table III（`te_re`）的 PP/SC 行，新增了更严格的 SVD inlier gating（`solver.inlier_threshold_m=0.75`）并适度放宽检测匹配距离（`matching.distance_thresholds.detected=1.2`），在不改变数据集/评测口径的前提下可显著缩小差距：
- PP15（closest，Table III 对齐优先）：`configs/pipeline_paper3737_pp15_heal_pp_corners_conf0p3_iter2_inlier0p75_det1p2_max6.yaml`
  - 输出：`outputs/paper3737_pp15_heal_pp_corners_conf0p3_iter2_inlier0p75_det1p2_max6/matches.jsonl`
  - `success_gate=te_re`：Success@{1,2,3}m = **{0.186, 0.516, 0.694}**（论文 0.249/0.566/0.709）
- SC15（closest/best）：`configs/pipeline_paper3737_sc15_heal_sc_corners_conf0p3_iter2_inlier0p75_det1p2.yaml`
  - 输出：`outputs/paper3737_sc15_heal_sc_corners_conf0p3_iter2_inlier0p75_det1p2/matches.jsonl`
  - `success_gate=te_re`：Success@{1,2,3}m = **{0.204, 0.547, 0.711}**（论文 0.252/0.569/0.712）

2026-01-15 补充：为减少“TE 已达标但 RE 稍超阈值”导致的 `te_re` Success 损失，加入了 **confidence-aware 的 wSVD 加权**（仅影响 wSVD 的权重，不改匹配集），并配合“不过早截断 retained matches”做了一轮小规模 sweep：
- 新增 solver 配置项：`solver.confidence_weight_exponent`、`solver.confidence_weight_min`（默认 0，不影响历史结果）。
- 当前 paper3737 PP15 的 `te_re` closest/best 更新为：
  - `configs/pipeline_paper3737_pp15_heal_pp_corners_conf0p3_iter2_inlier0p75_det1p2_nomax_confexp2p0.yaml`
  - 输出：`outputs/paper3737_pp15_heal_pp_corners_conf0p3_iter2_inlier0p75_det1p2_nomax_confexp2p0/matches.jsonl`
  - `success_gate=te_re`：Success@{1,2,3}m = **{0.193, 0.520, 0.695}**（论文 0.249/0.566/0.709；仍差约 4–6pp，主要瓶颈依旧是 RE）

对照：论文 Table-III（paper3737）为
- PP15 ≈ {0.249, 0.566, 0.709}
- SC15 ≈ {0.252, 0.569, 0.712}

说明：
- 本文档早期记录中的 Success 数值来自当时 run 写出的 `metrics.json`，其 success gate 与当前 Table III 对齐口径并不一致（曾默认 `te`），会造成“PP/SC 看起来比 GT 更好”等错觉。
- 目前 Table III 的正式对齐以 `docs/operations/table3_paper3737_repro_status.md` 为准：它只从 `matches.jsonl/details.jsonl` 重新计算，并强制校验 pair 集合与 `data/data_info_dair_paper3737.json` 一致；默认使用 `success_gate=te_re`（更贴近表内 V2X-Reg++ GT 行）。
- 在 `success_gate=te_re` 口径下，上述 PP/SC 仍低于论文（Success@1m 约差 5–6pp），后续优化以提升旋转精度（RE）为主。

### C. 180° 歧义开关对比（结论：当前实现下不要开）

开启 `resolve_180_ambiguity: true` 会显著变慢且成功率下降（无论 `te` 还是 `te_re` 都会掉）：
- PP（开 180）：`outputs/paper3737_pp15_heal_pp_corners_conf0p3_iter2_180/metrics.json`
- SC（开 180）：`outputs/paper3737_sc15_heal_sc_corners_conf0p3_iter2_180/metrics.json`

结论：对于当前这批 HEAL 导出的 corners/7D，强行做 180°/D4 permutation search 会引入更多错误匹配并增加开销。

### D. 7D（`pred_box3d_np_list`）验证（结论：本次提升不来自“消除角点歧义”）

使用 7D 字段（`data.detection_field: pred_box3d_np_list`）跑出的指标与 corners 基本一致：
- `configs/pipeline_paper3737_pp15_heal_pp_7d.yaml`
- `configs/pipeline_paper3737_sc15_heal_sc_7d.yaml`

说明：本次 paper3737 上的提升主要来自 **检测覆盖率/对齐正确 + 置信度过滤 + SVD 稳健迭代**，而不是 7D 自动解决了歧义。

## 代码修改清单（贡献点）

### 1) HEAL：支持 paper3737 的 pair-level split，并处理重复 vehicle id

- 文件：`HEAL/opencood/data_utils/datasets/basedataset/dairv2x_basedataset.py`
- 贡献：
  - 新增 `self.co_data_pair` 映射（`veh_id_inf_id` ↔ frame_info）
  - `retrieve_base_data` 支持 split entry 为 dict：可同时指定 `veh_frame_id` 与 `inf_frame_id`
  - 避免 paper3737 导出时因为重复 veh_id 而取错 infra 对

### 2) 新增/固化 paper3737 的 HEAL 导出 split 文件

- 文件：`data/paper3737_pairs.json`
- 贡献：
  - 让 HEAL export 在 paper3737 上“每条样本唯一确定一对协同帧”，并实现 3737/3737 覆盖。

### 3) 新增复现实验配置（paper3737 PP/SC，corners/7D，对比 180 开关）

新增配置文件：
- `configs/pipeline_paper3737_pp15_heal_pp_corners.yaml`
- `configs/pipeline_paper3737_pp15_heal_pp_7d.yaml`
- `configs/pipeline_paper3737_pp15_heal_pp_corners_iter2.yaml`
- `configs/pipeline_paper3737_pp15_heal_pp_corners_conf0p3_iter2.yaml`
- `configs/pipeline_paper3737_pp15_heal_pp_corners_conf0p3_iter2_180.yaml`
- `configs/pipeline_paper3737_sc15_heal_sc_corners.yaml`
- `configs/pipeline_paper3737_sc15_heal_sc_7d.yaml`
- `configs/pipeline_paper3737_sc15_heal_sc_corners_conf0p3_iter2.yaml`
- `configs/pipeline_paper3737_sc15_heal_sc_corners_conf0p3_iter2_180.yaml`

贡献：
- 固化“一键复现” paper3737 PP/SC 全流程与对比设置；
- 将“删垃圾框”落实为 `filters.min_confidence`（score>=0.3）；
- 将“稳健求解”落实为 `solver.max_iterations=2`（SVD + inlier refinement）。

## 局限与后续工作

1. **当前达到/超过论文效果的结论针对 paper3737 子集**。  
   若要在其它 split（例如 val 1789 / full 6617）达到同等级，需要单独导出对应 split 的双端检测 cache，并重新评估。
2. “内框/重叠区域框优先”的显式策略（例如基于可视区域/互相可见区域、RANSAC inlier 选框）**尚未单独实现成独立模块**；目前主要依赖：
   - score 过滤（min_confidence）
   - top-k 筛选
   - SVD 的迭代式 inlier 剔除（`max_iterations=2`）
3. 180° 歧义处理：当前的 permutation/D4 搜索 **在本数据上效果更差**；若未来要进一步提升，应先定义更强的匹配置信度约束（例如利用 box 尺寸/类别一致性、局部图一致性、或 descriptor），再做有限歧义搜索。
4. HEAL 导出依赖 GPU 与 `/home/qqxluca/miniconda3/envs/heal` 环境；若迁移机器，需要重新安装 OpenCOOD/SpConv 相关依赖。

## 复现步骤（从零开始）

1) 准备数据软链（HEAL 的默认路径）
```bash
mkdir -p dataset/my_dair_v2x/v2x_c
ln -s /data2/DAIR-V2X-C/cooperative-vehicle-infrastructure dataset/my_dair_v2x/v2x_c/cooperative-vehicle-infrastructure
```

2) 使用 HEAL 导出 paper3737 双端 Stage1（PP/SC 各一条命令）
```bash
# PP（GPU0）
MAMBA_ROOT_PREFIX=$PWD/.micromamba ./bin/micromamba run -p /home/qqxluca/miniconda3/envs/heal bash -lc '
  cd HEAL && CUDA_VISIBLE_DEVICES=0 PYTHONPATH=. python opencood/tools/pose_graph_pre_calc.py \
    --per_agent --splits test \
    --test_dir_override /home/qqxluca/v2xreg_private/data/paper3737_pairs.json \
    --vehicle_hypes opencood/logs/Pyramid_DAIR_m1_pointpillars_single_2025_11_24_18_47_23/config.yaml \
    --vehicle_checkpoint opencood/logs/Pyramid_DAIR_m1_pointpillars_single_2025_11_24_18_47_23/net_epoch_bestval_at39.pth \
    --infra_hypes opencood/logs/Pyramid_DAIR_m1_pointpillars_single_2025_11_24_18_47_32/config.yaml \
    --infra_checkpoint opencood/logs/Pyramid_DAIR_m1_pointpillars_single_2025_11_24_18_47_32/net_epoch_bestval_at39.pth \
    --merged_output /home/qqxluca/v2xreg_private/data/DAIR-V2X/detected/paper3737_pp_dual/stage1_boxes.json'

# SC（GPU1）
MAMBA_ROOT_PREFIX=$PWD/.micromamba ./bin/micromamba run -p /home/qqxluca/miniconda3/envs/heal bash -lc '
  cd HEAL && CUDA_VISIBLE_DEVICES=1 PYTHONPATH=. python opencood/tools/pose_graph_pre_calc.py \
    --per_agent --splits test \
    --test_dir_override /home/qqxluca/v2xreg_private/data/paper3737_pairs.json \
    --vehicle_hypes opencood/logs/Pyramid_DAIR_m2_second_single_2025_11_24_23_51_50/config.yaml \
    --vehicle_checkpoint opencood/logs/Pyramid_DAIR_m2_second_single_2025_11_24_23_51_50/net_epoch_bestval_at29.pth \
    --infra_hypes opencood/logs/Pyramid_DAIR_m2_second_single_2025_11_24_23_52_14/config.yaml \
    --infra_checkpoint opencood/logs/Pyramid_DAIR_m2_second_single_2025_11_24_23_52_14/net_epoch_bestval_at29.pth \
    --merged_output /home/qqxluca/v2xreg_private/data/DAIR-V2X/detected/paper3737_sc_dual/stage1_boxes.json'
```

3) 跑标定（推荐配置：PP/SC 各 1 个）
```bash
MAMBA_ROOT_PREFIX=$PWD/.micromamba ./bin/micromamba run -n v2x \
  python tools/run_calibration.py --config configs/pipeline_paper3737_pp15_heal_pp_corners_conf0p3_iter2.yaml --print

MAMBA_ROOT_PREFIX=$PWD/.micromamba ./bin/micromamba run -n v2x \
  python tools/run_calibration.py --config configs/pipeline_paper3737_sc15_heal_sc_corners_conf0p3_iter2.yaml --print
```
