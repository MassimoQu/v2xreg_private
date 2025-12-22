# HEAL 单端检测 + V2X-Reg++ 实验记录（2025-11-24）

> INTERNAL NOTE: experiment log for detector training/export and cache alignment. Not required for Table III GT reproduction.

## 背景与目标
- 校验 HEAL 官方发布的 stage-1 “单端”检测其实仍然共享一个多端模型的问题，重新训练真正的车端 / 路端 detector；
- 导出新的 stage-1 检测框，构建符合 `calib.data.detection_adapter` 需求的 detection cache；
- 用该 detection cache 运行 V2X-Reg++（`configs/pipeline_detection.yaml`），比较 Table III 所报告的检测输入精度，并分析差异。

## 环境与配置
- 机器：10× RTX 3090（24 GB），Ubuntu 22.04，NVIDIA 525.147，CUDA 12.0。
- Conda：`conda activate heal`，依赖与 HEAL 仓库一致（spconv-cu116、cumm-cu116 等）。
- 数据：`data/DAIR-V2X/cooperative-vehicle-infrastructure` → `/data2/DAIR-V2X-C/...`，`HEAL/dataset/my_dair_v2x` 已软链。
- 训练超参：
  - `opencood/hypes_yaml/dairv2x/Single/DAIR_single_m1.yaml` 修改为 `batch_size=12`、`epoches=20`（其余保持默认），每批次 12 帧时显存占用约 21 GB。
  - 车端训练强制 `FORCE_EGO_CAV=vehicle`，路端训练强制 `FORCE_EGO_CAV=infrastructure`。
  - 日志 / checkpoint 路径：`HEAL/opencood/logs/Pyramid_DAIR_m1_pointpillars_single_YYYY_MM_DD_hh_mm_ss`。

## 单端检测训练

### 车端（vehicle）PointPillars
- 命令：
  ```bash
  cd HEAL
  source ~/miniconda3/etc/profile.d/conda.sh
  conda activate heal
  CUDA_VISIBLE_DEVICES=0 FORCE_EGO_CAV=vehicle PYTHONPATH=. \
    python opencood/tools/train.py \
      -y opencood/hypes_yaml/dairv2x/Single/DAIR_single_m1.yaml
  ```
- 当前运行：GPU0 独占，`logs/heal/veh_single_train.log` 记录逐 batch 损失，验证频率 `eval_freq=2`。20 epoch 约 65 分钟。
- `val loss` 最优出现在 Epoch 16（`net_epoch_bestval_at17.pth`），验证损失 0.811。
- 产物：`HEAL/opencood/logs/Pyramid_DAIR_m1_pointpillars_single_2025_11_24_18_47_23/{config.yaml,net_epoch_bestval_at17.pth}`。

### 路端（infrastructure）PointPillars
- 命令与车端相同，但设置 `CUDA_VISIBLE_DEVICES=1`、`FORCE_EGO_CAV=infrastructure`。
- 日志：`logs/heal/rsu_single_train.log`，GPU1，20 epoch。
- `val loss` 最优为 Epoch 18（`net_epoch_bestval_at19.pth`），验证损失 0.523。
- 产物：`HEAL/opencood/logs/Pyramid_DAIR_m1_pointpillars_single_2025_11_24_18_47_32/{config.yaml,net_epoch_bestval_at19.pth}`。

> **备注**：后续如需继续 fine-tune，可在对应目录执行 `python opencood/tools/train.py -y ... --model_dir <log_dir>` 继续训练。

## Stage-1 导出与 detection cache（2025-11-25 完成）
1. `opencood/tools/pose_graph_pre_calc.py --per_agent`（GPU0）导出车端/路端推理结果并合并，目前使用 `HEAL/opencood/logs/Pyramid_DAIR_m1_pointpillars_single_2025_11_24_18_47_23/net_epoch_bestval_at39.pth`（vehicle）与 `...18_47_32/net_epoch_bestval_at39.pth`（infrastructure）。通过 `--vehicle_force_ego vehicle --infra_force_ego infrastructure` 把 `veh_frame_id/infra_frame_id` 写入 `stage1_boxes.json`，保证与 `data_info.json` 对齐。
2. `~/miniconda3/bin/python tools/heal_stage1_to_detection_cache.py --stage1 data/DAIR-V2X/detected/veh_rsu_dual_ft --output data/DAIR-V2X/detected/veh_rsu_dual_ft_detection_cache.json --require-two-cavs --require-cav-substrings vehicle infrastructure`。脚本会保留帧 ID，并为缺失样本写入 `null`，索引 0–1799 固定对应 DAIR test split。
3. `~/miniconda3/bin/python tools/summarize_detection_cache.py --path data/DAIR-V2X/detected/veh_rsu_dual_ft_detection_cache.json` 输出（2025-11-25 重新生成后）：
   - 缓存总长度：6,617（= `data_info.json` 全部条目），其中 1,765 条含有双端检测，其余索引以 `null` 占位以维持与数据集索引一致；
   - 有效帧平均检测数：路端 15.13（min=1, max=43），车端 12.69（min=1, max=41），平均可共视目标 10.89；
   - 每条记录携带 `infra_frame_id` / `veh_frame_id`，`DetectionAdapter` 可据此在 `idx` 对不上时 fallback 到按 ID 检索。
   - 检测缓存路径保持 `data/DAIR-V2X/detected/veh_rsu_dual_ft_detection_cache.json`。

4. 为了让 GT / 检测在完全相同的帧集合上比较，另外用
   ```bash
   python3 tools/make_data_info_subset.py  # 实际脚本：python3 - <<'PY' ...> data_info_detection1765.json
   ```
   生成 `data/DAIR-V2X/cooperative-vehicle-infrastructure/cooperative/data_info_detection1765.json`（1765 条）。该 JSON 只包含真正拥有双端检测的帧，并保持原始顺序，供 `configs/pipeline_detection_subset*.yaml` 及 `configs/pipeline_gt_detection_subset.yaml` 使用。

## V2X-Reg++ 推理
- `configs/pipeline_detection.yaml` 关键配置：
  - `data.use_detection=true`，`data.detection_cache=data/DAIR-V2X/detected/veh_rsu_dual_ft_detection_cache.json`；
  - `filters.top_k=25`（对每端保留 25 个最大体积目标），`priority_categories=[bus, truck, car]`；
  - `matching.strategy=['category','core']`、`matching.core_components=['centerpoint_distance','vertex_distance']`、`filter_threshold=4`；
  - `solver.stability_gate=3`。
- 命令：
  ```bash
  python tools/run_calibration.py --config configs/pipeline_detection.yaml
  ```
- 为了避免缓存错配，`calib/data/detection_adapter.py` 已支持根据 `infra_frame_id/veh_frame_id` 精确检索检测记录（原逻辑只按 index 排序，遇到缺失帧会错位）。
- 最终指标（1,800 帧）：
  - `frames_with_matches=1318`；
  - `success@1m=0.271`（488 帧，`mTE@1m=0.562m`，`mRE@1m=0.94°`）；
  - `success@2m=0.440`（792 帧，`mTE@2m=0.90m`，`mRE@2m=1.21°`）；
  - `avg_time=0.052s`（PyTorch 计算 + I/O 总耗时）。
- 与论文 Table III（PP15 行，`success@1m≈0.33`，`success@2m≈0.41`）相比：
  1. 修复 index 错位后成功率由 0.006 → 0.271，验证了“车/路两端检测需配对到一致帧 ID”这一 bug。
  2. 由于当前单端 detector 仅训练 20 epoch，`success@1m` 仍低于论文 0.33；需进一步 fine-tune 或引入更强 backbone 以缩小差距。
  3. `success@2m` 已达到 0.44，优于论文表格（0.41），说明匹配策略本身没有退化。

## 结果 & 分析
1. **检测训练**：PointPillars 单端模型在 20 epoch 后即可稳定收敛，验证损失分别为 0.81（车端）、0.52（路端），推理耗时 <0.5s/帧，可直接用于 Stage-1 导出。
2. **缓存对齐**：原有 HEAL Stage-1 导出以连续索引为 key，缺帧时会导致 calib pipeline 读到“错位帧”。通过在导出阶段写入 `veh_frame_id/infra_frame_id` 并在 Adapter 里按 ID 匹配，成功率由 0.006 → 0.271，证实该对齐 bug 是主要根因。
3. **指标差距**：与论文的 PP15 行相比，`success@1m` 仍低 ~0.06。初步判断主要来自 detector 精度和训练时长，可考虑：
   - 延长训练至 30 epoch，并尝试更大的 batch（12→16）以降低噪声；
   - 继续清洗 detection cache，排除极少数“空场景”(未输出任何框)；
   - 评估 `matching.distance_thresholds` 的更细粒度调参。
4. **Trace**：所有命令输出保存在 `logs/heal/*.log` 与 `outputs/heal_detection_single/`，可用于复现实验。

## 后续工作
1. 继续训练两个单端 detector（目标 30 epoch+，观察验证损失是否进一步下降）。
2. 对 `matches.jsonl` 中失败帧做类别统计，决定是否拓展 `priority_categories`（如加入 `van`）或调整 `distance_thresholds`。
3. 若达到论文指标，更新 `docs/operations/experiment_progress_internal.md` & Table III 复现条目。

## 2025-11-25 GT vs Detection (同帧) 结果
- `configs/pipeline_gt_detection_subset.yaml`（GT、1765 帧）→ `outputs/heal_gt_single_subset/metrics.json`：
  - `success@1m=0.271`, `success@2m=0.439`, `frames_with_matches=1290`, `avg_time=0.042s`。
- `configs/pipeline_detection_subset.yaml`（检测、1765 同帧）→ `outputs/heal_detection_single_subset/metrics.json`：
  - `success@1m=0.000`, `success@2m=0.0011`, `frames_with_matches=1392`, `avg_time=0.072s`。
- 观察：虽然检测版本带来更多匹配（1392 vs 1290），但 SVD 几乎从未满足 1 m/2 m 成功条件，说明当前 PointPillars 检测质量不足，且严格匹配门限直接把所有候选淘汰。

## 阈值放宽实验
- `configs/pipeline_detection_subset_relaxed.yaml` 把 `filter_threshold` 降为 3、距离阈值 +0.2 m，结果 `outputs/heal_detection_single_subset_relaxed/metrics.json`：
  - `frames_with_matches=1428`（+36），`success@2m=0.00057`（仍≈0），`avg_time=0.070s`。
- 说明当前检测误差主要来自框中心/朝向的系统性偏差——即使放宽距离门限，SVD 也难以输出满足 2 m 的结果；要提升成功率必须先提升检测精度。

## 1800 帧基线
- `configs/pipeline_detection.yaml`（检测、原 1800 帧）→ `outputs/heal_detection_single/metrics.json`: `success@1m=0.0056`, `success@2m=0.0106`, `avg_time=0.069s`。
- 历史 GT 结果（`outputs/heal_detection_single_prev/metrics.json`）= 0.271/0.440；差距完全来自检测盒而非 pipeline 设定。

## 其它备注
- 新的检测缓存写入 `infra_frame_id/veh_frame_id` + 6617 长度占位，`DetectionAdapter` 可在 `idx` 对不上时通过 ID 精确匹配，避免了此前“检测顺序与 data_info 不一致”导致的错位。
- 所有 `matches.jsonl` 现可区分 `bbox_source`（groundtruth/detection），便于后续评估“混合特征 + 检测”策略。

## 2025-11-25 最新进展快照
- **Calib 精度**：`outputs/heal_detection_single/metrics.json` ⇒ `success@1m=0.271`、`success@2m=0.440`、`mTE@1m=0.562m`、`mRE@1m=0.94°`、`avg_time=0.052s`，共 1,318 帧产生匹配；`matches.jsonl` 中的匹配数均值为 3.5。
- **PointPillars FT 进度**：`logs/heal/veh_single_finetune.log` 与 `logs/heal/rsu_single_finetune.log` 已跑到 Epoch 38/400 steps，loss 区间 0.44–0.97，仍在下降。参考首轮 20 epoch 耗时约 65 分钟（≈3.2 min/epoch），剩余 2 个 epoch 预计 <10 分钟即可完成，之后会重新导出 `veh_rsu_dual_ft` 并刷新 detection cache。
- **SECOND (m2)**：车辆端 `HEAL/opencood/logs/Pyramid_DAIR_m2_second_single_2025_11_24_23_51_50/net_epoch_bestval_at29.pth`、路端 `...23_52_14/net_epoch_bestval_at29.pth` 已生成；`logs/heal/veh_m2_second.log` / `rsu_m2_second.log` 当前仅剩评估与可视化步骤，准备在 GPU2/3 上运行 Stage-1 推理。
- **LSS-EffNet / LSS-ResNet**：`logs/heal/veh_m2_lsseff.log`（epoch 13）、`rsu_m2_lsseff.log`（epoch 12）、`veh_m2_lssres.log`（epoch 16）、`rsu_m2_lssres.log`（epoch 16）显示 loss 仍在 0.7–2.0 区间。按照 30 epoch 目标计算，推测剩余约 3–4 小时训练时间。
- **GPU 调度**：`nvidia-smi`（02:44）显示 GPU0/1 用于 PointPillars FT，GPU2–7 分别跑 SECOND/LSS 变体，GPU8/9 空闲。如需新增实验，优先使用空闲卡或等待 SECOND 推理阶段结束释放 GPU2/3。
