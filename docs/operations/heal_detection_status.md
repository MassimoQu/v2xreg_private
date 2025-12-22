# HEAL 检测与 V2I-Calib++ 集成状态（2025-11-22）

> INTERNAL NOTE: integration/debug log. Metrics and training recipes here are not part of the minimal public reproduction path.

## 为什么要做
- **目标**：让 `v2i-calib++` 能利用 HEAL 的检测结果（车端 vs 路端）获得稳定的外参估计。  
- **痛点**：HEAL 官方提供的 `stage1` 导出把所有 CAV 感知堆在一个 ego 坐标系下，无法满足 V2I-Calib++ 对“双方各自在本地坐标下的检测框”的要求；并且路端（RSU）缺少可直接部署的 checkpoint。

## 目前已完成
1. **工具链改造**  
   - `HEAL/opencood/tools/pose_graph_pre_calc.py` 新增 `--per_agent` 模式，可分别指定车端/路端 hypes & checkpoint、强制 ego、限制通讯距离、自动合并双端 JSON。  
   - `tools/heal_stage1_to_detection_cache.py` 可把 Stage1 导出转换为 V2I-Calib++ 的 detection cache；`configs/pipeline_detection.yaml` 指向该缓存，并设置 `use_detection=true`。
2. **实验设置**  
   - **检测导出**：暂用 HEAL stage1 点云模型在车端/路端点云上分别推理（路端缺少专用模型，因此仍是同一模型复用），`single_agent_comm_range=0`，强制不同 ego。  
   - **检测缓存**：`data/DAIR-V2X/detected/heal_stage1_dual_detection_cache.json`，共 1,789 帧双端检测，平均车端 17.4 个框、路端 11.5 个框。  
   - **标定**：`python tools/run_calibration.py --config configs/pipeline_detection.yaml`，`max_samples=1800`，输出目录 `outputs/heal_detection/`。
3. **结果与分析**  
   - `outputs/heal_detection/metrics.json`：`success@{1,2,3,4,5}m=[0.191, 0.192, 0.192, 0.193, 0.194]`，`mRE@{1…5}m=[0.0041, 0.0088, 0.0109, 0.0244, 0.0355]`，`mTE@{1…5}m=[0.0025, 0.0081, 0.0155, 0.0342, 0.0483]`，`avg_time=0.155s`。  
   - `matches.jsonl`：每帧有效匹配均值 1.62，343/1800 帧无任何匹配；TE/RE 中位数依旧在 60–80 m/deg，说明：  
     1. 虽然双方都有检测框，但匹配质量低，常被几何过滤淘汰。  
     2. 路端检测模型仍是“车端模型的替身”，缺乏真正的 RSU 学习能力。

## 接下来要做什么
1. **训练独立的车端/路端单端检测模型**  
   - 车端：基于 `opencood/hypes_yaml/dairv2x/Single/DAIR_single_m1.yaml` 或现有 stage1 YAML，训练 PointPillars 模型。  
   - 路端：基于 `checkpoints/stage2_and_final_infer/m3_alignto_m1/config.yaml` 或新建 YAML，专门针对 RSU 点云（spconv 2.x 需注意通道数）。  
   - 输出：`logs/veh_single_m1/net_epoch_bestval_atXX.pth`、`logs/rsu_single_m3/net_epoch_bestval_atYY.pth`。
2. **重新导出检测与统计共有框**  
   ```bash
   cd HEAL
   PYTHONPATH=. python opencood/tools/pose_graph_pre_calc.py \
     --per_agent \
     --vehicle_hypes logs/veh_single_m1/config.yaml \
     --vehicle_checkpoint logs/veh_single_m1/net_epoch_bestval_atXX.pth \
     --vehicle_output ../data/DAIR-V2X/detected/veh_single \
     --infra_hypes logs/rsu_single_m3/config.yaml \
     --infra_checkpoint logs/rsu_single_m3/net_epoch_bestval_atYY.pth \
     --infra_output ../data/DAIR-V2X/detected/rsu_single \
     --splits test \
     --merged_output ../data/DAIR-V2X/detected/veh_rsu_dual \
     --single_agent_comm_range 0 \
     --vehicle_force_ego vehicle \
     --infra_force_ego infrastructure
 python tools/heal_stage1_to_detection_cache.py \
  --stage1 data/DAIR-V2X/detected/veh_rsu_dual \
  --output data/DAIR-V2X/detected/veh_rsu_dual_detection_cache.json \
  --require-two-cavs \
  --require-cav-substrings vehicle infrastructure
```
   - `--require-cav-substrings` 会强制 `cav_id_list` 同时包含 `vehicle` 与 `infrastructure`，可过滤仍然沿用单端检测模型的“伪双端”样本。
   - 统计共有框（可快速检查是否 ≥3/帧）：见 `docs/operations/heal_detection_status.md` 的 Python 片段或直接调用 `matches.jsonl`。
3. **再跑 V2I-Calib++ 并分析**  
   - `python tools/run_calibration.py --config configs/pipeline_detection.yaml`。  
   - 关注成功率是否显著提升；若仍不足，需要从 `configs/pipeline_detection.yaml` 中调整 `filters.top_k`、`matching.distance_thresholds`、`solver.stability_gate` 等参数，并结合 `matches.jsonl` 定位匹配失败原因。

## 单端检测训练与导出流程

1. **环境确认**  
   - 数据：`data/DAIR-V2X/cooperative-vehicle-infrastructure` → `/data2/DAIR-V2X-C/cooperative-vehicle-infrastructure`，`HEAL/dataset/my_dair_v2x` 软链已修复，可直接通过 `dataset/my_dair_v2x/v2x_c/...` 访问。  
   - Conda：`source ~/miniconda3/etc/profile.d/conda.sh && conda activate heal`；`spconv-cu116==2.3.6`、`cumm-cu116` 以及 `opencood/pcdet_utils` 自定义 CUDA 扩展均已安装/编译。  
   - `FORCE_EGO_CAV`：在运行任意 `train.py` / 自定义脚本时设置（`vehicle` 或 `infrastructure`），即可强制数据集把指定 CAV 作为 ego，跳过默认的随机交换；该值也会写入日志中的 `config.yaml`。

2. **训练命令（PointPillars 单端 Detector）**
   ```bash
   cd HEAL
   source ~/miniconda3/etc/profile.d/conda.sh
   conda activate heal

   # 车端
   FORCE_EGO_CAV=vehicle python opencood/tools/train.py \
     -y opencood/hypes_yaml/dairv2x/Single/DAIR_single_m1.yaml

   # 路端
   FORCE_EGO_CAV=infrastructure python opencood/tools/train.py \
     -y opencood/hypes_yaml/dairv2x/Single/DAIR_single_m1.yaml
   ```
   - 训练完成后会在 `HEAL/opencood/logs/Pyramid_DAIR_m1_pointpillars_single_*` 下生成 `net_epoch_bestval_atXX.pth`；日志中的 `force_ego_cav` 用于区分车辆/路侧 run。  
   - 若需 resume：`FORCE_EGO_CAV=<target> python opencood/tools/train.py -y ... --model_dir <log_dir>`。

3. **Stage1 导出与缓存**  
   - `pose_graph_pre_calc.py` 的 `--vehicle_force_ego / --infra_force_ego` 会自动写入与训练相同的 `force_ego_cav`，无需额外设置 env：  
     ```bash
     cd HEAL
     PYTHONPATH=. python opencood/tools/pose_graph_pre_calc.py \
       --per_agent \
       --vehicle_hypes opencood/hypes_yaml/dairv2x/Single/DAIR_single_m1.yaml \
       --vehicle_checkpoint opencood/logs/veh_single_m1/net_epoch_bestval_atXX.pth \
       --vehicle_output ../data/DAIR-V2X/detected/veh_single \
       --infra_hypes opencood/hypes_yaml/dairv2x/Single/DAIR_single_m1.yaml \
       --infra_checkpoint opencood/logs/rsu_single_m1/net_epoch_bestval_atYY.pth \
       --infra_output ../data/DAIR-V2X/detected/rsu_single \
       --merged_output ../data/DAIR-V2X/detected/veh_rsu_dual \
       --single_agent_comm_range 0 \
       --vehicle_force_ego vehicle \
       --infra_force_ego infrastructure \
       --splits test
     python tools/heal_stage1_to_detection_cache.py \
       --stage1 data/DAIR-V2X/detected/veh_rsu_dual \
       --output data/DAIR-V2X/detected/veh_rsu_dual_detection_cache.json \
       --require-two-cavs \
       --require-cav-substrings vehicle infrastructure
     ```
   - 记录每次导出的统计（帧数、平均框数、过滤掉的样本数），并保存在本文件中，便于与 calib 结果对比。

4. **进度追踪**  
   - 训练 / 推理 / 标定的关键中间产物统一放在 `HEAL/opencood/logs/`、`data/DAIR-V2X/detected/`、`outputs/heal_detection/`。  
   - 如迁移其它架构（如 `stage2/m3_single_pyramid.yaml`）同样适用 `FORCE_EGO_CAV` 机制，记得在此文档更新新的命令与结果。

## 交接要点
- 所有脚本/配置已更新到仓库；只要提供新的车端/路端 checkpoint，即可直接复用现有流程。  
- `pose_graph_pre_calc.py --per_agent` 默认会生成 `stage1_boxes.json` 并可自动合并；不再需要手工拆/合。  
- 需要确保新模型在 spconv 2.x 环境可加载（若用旧 checkpoint 需转换权重）。  
- 新实验的重要结果统一放在 `outputs/heal_detection/` 下并更新此文档，便于跟踪进度。  
- 若在训练或导出过程中遇到问题，优先检查：路径是否添加 `PYTHONPATH=.`、数据软链是否存在、`single_agent_comm_range` 是否已置 0。

## 2025-11-24 单端重新训练 + V2X-Reg++ 结果

| 项目 | 细节 |
| --- | --- |
| 训练配置 | `opencood/hypes_yaml/dairv2x/Single/DAIR_single_m1.yaml`，`batch_size=12`、`epoches=20`，GPU0/1 分别设置 `FORCE_EGO_CAV=vehicle/infrastructure`。 |
| 最优 checkpoint | 车端：`HEAL/opencood/logs/Pyramid_DAIR_m1_pointpillars_single_2025_11_24_18_47_23/net_epoch_bestval_at17.pth` (`val loss=0.811`)；路端：`...18_47_32/net_epoch_bestval_at19.pth` (`val loss=0.523`)。 |
| Stage-1 导出 | `CUDA_VISIBLE_DEVICES=0 PYTHONPATH=. python opencood/tools/pose_graph_pre_calc.py --per_agent --vehicle_hypes opencood/hypes_yaml/dairv2x/Single/DAIR_single_m1.yaml --vehicle_checkpoint ...17.pth --vehicle_output ../data/DAIR-V2X/detected/veh_single --vehicle_force_ego vehicle --infra_hypes opencood/hypes_yaml/dairv2x/Single/DAIR_single_m1.yaml --infra_checkpoint ...19.pth --infra_output ../data/DAIR-V2X/detected/rsu_single --infra_force_ego infrastructure --merged_output ../data/DAIR-V2X/detected/veh_rsu_dual --single_agent_comm_range 0 --splits test`。脚本同时写入 `veh_frame_id/infra_frame_id` 以对齐 `data_info.json`。 |
| 检测缓存 | `python tools/heal_stage1_to_detection_cache.py --stage1 data/DAIR-V2X/detected/veh_rsu_dual --output data/DAIR-V2X/detected/veh_rsu_dual_detection_cache.json --require-two-cavs --require-cav-substrings vehicle infrastructure`；随后用 `tools/summarize_detection_cache.py --path data/DAIR-V2X/detected/veh_rsu_dual_detection_cache.json` 补齐 1,800 个索引。统计：1763 帧具备双端检测，路端平均 17.92 个框（2–41），车端 11.58 个框（1–38），共享最少框均值 11.01。 |
| V2X-Reg++ 设置 | `configs/pipeline_detection.yaml`：`data.detection_cache=data/DAIR-V2X/detected/veh_rsu_dual_detection_cache.json`，`filters.top_k=25`，`matching.filter_threshold=4`，`solver.stability_gate=3`。 |
| V2X-Reg++ 结果 | `python tools/run_calibration.py --config configs/pipeline_detection.yaml` ⇒ `outputs/heal_detection_single/metrics.json`：`success@1m=0.271`、`success@2m=0.440`、`frames_with_matches=1318`、`avg_time=0.035s`；`matches.jsonl` 供后续分析。 |

**主要发现**

1. 导出时必须记录帧 ID 并在 `DetectionAdapter` 内按 `infra_frame_id/veh_frame_id` 匹配，否则由于 test split 中存在缺帧，检测与 GT 会错位，导致成功率降至 0.6%。  
2. 修复对齐问题后，`success@2m` 达到 0.44，略优于论文 Table III (PP15) 的 0.41；`success@1m=0.271` 仍略低于 0.33，需进一步提升 detector（更多 epoch/改进 backbone）。  
3. 缓存统计显示双端平均有 11 个共享目标，远高于旧 Stage1 cache（11 vs 1.6），匹配质量显著改善。

### 进行中的 fine-tune / 新架构训练（2025-11-24 晚）

| GPU | 模型 | FORCE_EGO_CAV | config | 备注 |
| --- | --- | --- | --- | --- |
| 0 | PointPillars（resume） | vehicle | `opencood/logs/Pyramid_DAIR_m1_pointpillars_single_2025_11_24_18_47_23/config.yaml` | 已完成 30 epoch，`net_epoch_bestval_atXX.pth` 正在跑 inference。 |
| 1 | PointPillars（resume） | infrastructure | `...18_47_32/config.yaml` | 同上。 |
| 2 | SECOND (m2) | vehicle | `opencood/hypes_yaml/dairv2x/Single/DAIR_single_m2_second.yaml` | PID 10598，约 40 min，训练 30 epoch。 |
| 3 | SECOND (m2) | infrastructure | 同上 | PID 12371。 |
| 4 | LSS-EfficientNet | vehicle | `opencood/hypes_yaml/dairv2x/Single/DAIR_single_m2_lsseff.yaml` | PID 13137；需下载 EfficientNet 权重（已完成）。 |
| 5 | LSS-EfficientNet | infrastructure | 同上 | PID 14714。 |
| 6 | LSS-ResNet | vehicle | `opencood/hypes_yaml/dairv2x/Single/DAIR_single_m2_lssres.yaml` | PID 16005。 |
| 7 | LSS-ResNet | infrastructure | 同上 | PID 16733。 |

完成后的下一步：
1. 对每种 detector 运行 `pose_graph_pre_calc.py --per_agent` 导出 stage-1，保存到 `data/DAIR-V2X/detected/<model_name>/`；
2. 用 `heal_stage1_to_detection_cache.py` + `summarize_detection_cache.py` 生成 cache 并记录平均检测数；
3. 以相同的 `configs/pipeline_detection.yaml`（复制一份修改 `top_k/tag` 即可）跑 `python tools/run_calibration.py`，比较不同 detector 对 V2X-Reg++ 的影响；
4. 将指标追加到本文件和 `docs/operations/experiment_progress_internal.md` 便于交接。

### 进阶训练 / 模型并行（2025-11-24 晚）
- **PointPillars fine-tune**：在原 `m1` 模型目录中继续训练到 30 epoch（GPU0/1，batch=12），日志 `logs/heal/veh_single_finetune.log` / `rsu_single_finetune.log`，对外发布 checkpoint 仍位于 `...18_47_23/` 与 `...18_47_32/`。
- **多架构探索**：同时在 GPU2–7 启动三套单端 detector（SECOND、LSS-Eff、LSS-Res），每个架构分别训练车辆/路侧模型 30 epoch，命令示例：
  ```bash
  # SECOND
  CUDA_VISIBLE_DEVICES=2 FORCE_EGO_CAV=vehicle PYTHONPATH=. \
    python opencood/tools/train.py -y opencood/hypes_yaml/dairv2x/Single/DAIR_single_m2_second.yaml
  CUDA_VISIBLE_DEVICES=3 FORCE_EGO_CAV=infrastructure PYTHONPATH=. ...

  # LSS-EfficientNet
  CUDA_VISIBLE_DEVICES=4 FORCE_EGO_CAV=vehicle ... DAIR_single_m2_lsseff.yaml

  # LSS-ResNet
  CUDA_VISIBLE_DEVICES=6 FORCE_EGO_CAV=vehicle ... DAIR_single_m2_lssres.yaml
  ```
  训练日志位于 `logs/heal/veh_m2_{second,lsseff,lssres}.log` 与 `rsu_m2_{...}.log`；待这些模型收敛后，将重复 Stage-1 导出 → detection cache → V2X-Reg++ 的评估流程，并把不同 detector 的标定表现加入本文档。
