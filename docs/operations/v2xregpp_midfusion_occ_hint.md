# V2X-Reg++ Mid-Fusion (Occ-Map Hint) 实验记录

**Owner:** Codex CLI Agent  
**Last updated:** 2026-01-11  

## 1. 任务目标（用户需求）

1) **探索并实现**：将 V2X-Reg++ 从“后融合范式（仅用检测框匹配求外参）”改成“**中融合阶段先用特征给外参 seed / hint，再进行匹配与求解**”。  
2) **约束**：HEAL 第一阶段必须是**真正单端**（vehicle/infra 各自单独前向导出），避免“先多端融合再拆分单端”的作弊方法。  
3) **验收**：迭代直到指标**超过后融合基线**（以同一数据/同一 top-k 设置为准）。

## 2. 核心思路（当前有效的中融合特征）

在现有 HEAL stage-1 cache 中，我们已经能拿到每一帧每一端的 BEV occupancy map（`occ_map_level0`）。  
本次中融合有效路线是：

- **Step-A（Feature → Hint）**：用 `occ_infra` 与 `occ_vehicle` 做 **相位相关 + 旋转搜索**，得到平面外参种子 `T_hint ≈ (tx, ty, yaw)`。  
- **Step-B（Hint → Aligned Matching）**：用 `T_hint` 把 infra 侧的框先对齐到 vehicle 坐标系，再跑一次常规 BoxesMatch 得到更稳定的匹配对。  
- **Step-C（Select best）**：同一帧同时跑 “late（无 hint）” 与 “aligned（有 hint）” 两条分支，用**内部一致性指标**（CorrespondingDetector precision + matched num）选更优候选，再进入 SVD 求解。

> 说明：目前 “BEV embedding descriptor 直接做跨端匹配 seed” 的路线在数据上不稳定（cosine 分离度不足），所以并未成为最终提升来源。

## 3. 关键贡献（做成了什么）

### 3.1 修正与增强 occ-hint 估计（Feature seed）

文件：`calib/pipelines/object_level.py`

- 修正相位相关估计的 **方向/符号**（得到的是 vehicle 相对 infra 的 shift，需要转换成 i→v hint）。
- 支持 **旋转搜索**（`occ_hint_rotation_max_deg / occ_hint_rotation_step_deg`），并加入 coarse→refine 的角度细化，以降低全角搜索开销。
- 增加 **downsample**（最大边约 128）使旋转搜索成本可控。
- 增加 **峰值置信 gating**：
  - `occ_hint_min_peak`：绝对峰值阈值（可选）
  - `occ_hint_min_peak_ratio`：best/second-best 的比例阈值，用于丢弃“角度歧义很强”的帧

对应新增配置字段：
- `calib/config.py`：`MatchingConfig.occ_hint_min_peak / occ_hint_min_peak_ratio`

### 3.2 让 GT 框也能读 occ hint（不中断 GT pipeline）

问题：以前 `occ_maps` 只能在 `use_detection=true` 时从 detection cache 读到，导致无法在 GT 框实验里验证“特征 hint 的纯收益”。  

解决：
- `calib/config.py`：新增 `DataConfig.load_detection_hints`
- `calib/data/dataset_manager.py`：允许 `use_detection=false` 但 `load_detection_hints=true` 时仍读取 `occ_map_level0/bev_range`。

### 3.3 Matching 逻辑改为“对齐后再跑 BoxesMatch + 选优”

文件：`calib/pipelines/object_level.py`

- 每帧都先跑 “late（T_hint=None）” 的 baseline 匹配。
- 若存在 `T_hint`，先对齐 infra 框，再跑一次 BoxesMatch 得到 “aligned” 匹配。
- 对两个候选分别求外参（SVD），用内部质量函数选优，记录 `matching_source`（`late/aligned/prior`）。

## 4. 复现实验与结果（Top3000, top-k=15）

### 4.1 对齐后的中融合（GT 框 + occ hint）超过 late baseline

- **Late baseline (GT, top-15)**  
  - config：`configs/pipeline_gt_top3000_15.yaml`  
  - output：`outputs/gt_top3000_15_full3000/metrics.json`  
  - `success_at_1m = 0.3383`, `success_at_2m = 0.4937`

- **Mid-fusion (GT, top-15) + occ hint + aligned matching + ratio gating**  
  - config：`configs/pipeline_midfusion_gt_occ_r14.yaml`（`occ_hint_min_peak_ratio: 1.4`）  
  - output：`outputs/gt_occ_aligned_r14/metrics.json`  
  - `success_at_1m = 0.3470`, `success_at_2m = 0.5017`

运行命令示例（统一用 conda 环境）：

```bash
~/miniconda3/envs/v2icalib/bin/python tools/run_pipeline.py \
  --config configs/pipeline_midfusion_gt_occ_r14.yaml \
  --tag gt_occ_aligned_r14
```

## 5. 修改清单（代码与配置）

### 5.1 主要改动文件

- `calib/pipelines/object_level.py`：occ-hint 估计（旋转/符号/下采样/置信 gating），aligned matching 分支，late vs aligned 选优，输出 `matching_source`。
- `calib/config.py`：新增 `DataConfig.load_detection_hints`；新增 `MatchingConfig.occ_hint_min_peak/occ_hint_min_peak_ratio`。
- `calib/data/dataset_manager.py`：允许在 `use_detection=false` 时读取 occ hints。
- `calib/matching/engine.py`：补充 `hint_matches()` 入口（目前主线已改为 aligned matching）。

### 5.2 新增/用于复现的配置文件

- `configs/pipeline_gt_top3000_15.yaml`
- `configs/pipeline_midfusion_gt_occ_r14.yaml`（推荐复现配置）
- 以及若干对照/中间实验配置（`configs/pipeline_midfusion_detection_occ.yaml`、`configs/pipeline_late_detection_bevdesc*.yaml` 等）

### 5.3 HEAL 单端导出/描述子相关改动（支撑中融合特征来源）

> 这部分来自本任务早期迭代：尝试用 BEV descriptor 直接做跨端匹配 seed（效果不稳定），同时也为 occ-hint 提供了可读取的 `occ_map_level0`。

- `HEAL/opencood/models/heter_model_late.py`
  - 支持导出单端 runtime BEV 特征与 `occ_map_list`（避免依赖“先融合再拆分”的作弊流程）。
- `HEAL/opencood/tools/pose_graph_pre_calc.py`
  - 支持在导出的 detection 上挂 `descriptor`（如 `--bev_descriptor_on_detections`）。
  - 支持导出 BEV peaks 伪框（`feature_corner3d_np_list`）与其 descriptor（`--dump_bev_features`）。
  - 支持控制是否写入 `occ_map_level0`（`--dump_occ_map`），避免导出 JSON 过大。
- `calib/matching/engine.py`
  - 增强 descriptor-only 匹配与 hint-based 匹配（当前主线已转向 occ-hint + aligned matching，但这些代码仍保留以便后续继续迭代 descriptor 路线）。

相关产物（示例）：
- `data/DAIR-V2X/detected/veh_rsu_dual_bevdesc/stage1_boxes.json`（包含 `occ_map_level0` 时体积很大；建议后续用 `--dump_occ_map` 重导）。

## 6. 局限与风险

1) **当前“超过基线”的结果是在 GT 框上完成**；检测框版本还需要继续迭代（受检测框跨端重叠稀疏/缓存体积等影响）。  
2) occ-hint 当前只估计 **平面 (tx, ty, yaw)**，对 `z/roll/pitch` 不敏感；若数据存在明显 6DOF 偏差，需要额外扩展。  
3) 旋转搜索依赖 `scipy.ndimage.rotate`，尽管已下采样 + coarse→refine，仍会带来额外耗时；长序列/更大分辨率需要进一步优化（例如 FFT 旋转频域策略或学习型角度估计）。  
4) `occ_hint_min_peak_ratio` 属于经验阈值，可能对不同数据分布敏感；需要在更大范围/不同 split 上验证泛化。  
5) “descriptor seed” 路线（BEV embedding descriptor 跨端匹配）目前未证明有效；后续若要用深度描述子，需要重新设计 descriptor（如 box 内 ROI pooling、多尺度聚合等）。

## 7. 下一步建议（如果继续推进到 detection 超越）

1) 重新导出一个 **不带 `occ_map_level0` 的轻量 detection cache**（`pose_graph_pre_calc.py` 已加入 `--dump_occ_map` 开关），避免 7GB JSON 造成迭代成本过高。  
2) 在 detection 框上引入 “occ aligned matching” 的同款选优逻辑（目前已具备，关键在于检测框质量/过滤策略）。  
3) 将 occ-hint 作为先验，把匹配/求解改成多假设（例如多角度候选）并用一致性打分选最优，提高在 yaw 多峰场景的稳健性。
