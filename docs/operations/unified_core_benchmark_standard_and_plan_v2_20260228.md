# Unified Core Benchmark Standard + Execution Plan v2（DAIR / OPV2V / V2V4Real）

更新：2026-02-28

## 0) 目标（你跑完能做什么决策）

- 在 **每个数据集内部**（DAIR / OPV2V / V2V4Real 各自独立），用**统一口径**公平比较 core(no-init/no-prior) pose-correction 方法：`v2xregpp / freealign / vips / cbm`。
- 产出**可复核/可引用**的 artifacts（manifest/config_snapshot + YAML + JSON + plots），避免“跑完但语义漂移/no-op/表面可比”。
- 10×3090 尽可能跑满：用 `max-per-gpu` 过订阅 + `split-noise` 提升并发；失败不阻塞后续任务；可 resume。

> 跨数据集 AP 绝对值不做硬横比；重点看“每个数据集内的排序/增益”。如果你要进一步降低解释成本，见第 7 节（V2XViT-unified）。

---

## 1) 关键定义（你需要先把“题目”统一）

### 1.1 clean vs noisy（位姿语义）

- clean pose：`params.lidar_pose_clean`
- noisy pose：`params.lidar_pose`（由噪声注入后得到）
- 噪声注入位置：`HEAL/opencood/utils/pose_utils.py` 的 `add_noise_data_dict`
  - 会把原 `lidar_pose` 备份到 `lidar_pose_clean`
  - 再按 `noise_setting.args.target`（`ego/non-ego/all`）给 `lidar_pose` 加高斯噪声

### 1.2 comm-range gating（通信范围裁剪语义）

`HEAL/opencood/data_utils/datasets/intermediate_fusion_dataset.py` 在裁剪邻居时用：
- `comm_range_use_clean_pose=True` → 用 clean pose 算距离（**agent set 固定**）
- `comm_range_use_clean_pose=False` → 用 noisy pose 算距离（**agent set 可能随噪声变化**）

历史坑：`HEAL/opencood/tools/inference_w_noise.py` 在某些路径会**隐式切换** `comm_range_use_clean_pose`，导致 baseline 与 pose-correction 处于不同 gating 语义。  
统一标准：必须显式传 `--comm-range-gating noisy|clean`，禁止 `auto`。

### 1.3 stage1 cache 语义（决定 box-based solver 是否“换题”）

`v2xregpp/freealign/vips/cbm` 的 box-based pose solver 假设：
- `pred_corner3d_np_list[i]` 必须在第 i 个 agent 的 **local frame**。

Fail-fast gate：
- 结构：`tools/validate_stage1_cache.py --stage1 <path>`
- 语义：`tools/validate_stage1_semantics.py --stage1 <path> --prefer-head200 --num-samples 50`

---

## 2) 你看到的异常现象：根因 + 证据链（可复现）

### 2.1 为什么会出现 “single 比 oracle 好 / single 数值虚高”？

根因：把 single 定义成 `comm_range=0` 会改变 dataset pruning → GT set 变小，任务更容易。  
典型证据：旧版 OPV2V fullbench 的 single 任务用了 `--comm-range-override 0`。

统一修复（公平 single 定义）：
- **保持同 comm_range 与 GT 难度**，但 forward 只看 ego 输入（不通信）
- 实现：`HEAL/opencood/tools/inference_w_noise.py` 的 `--force-ego-input-only`
- 已在脚本中修复：
  - `tools/run_opv2v_fullbench_fast.py`：single 不再 override comm_range=0，改为 `--force-ego-input-only`

### 2.2 为什么 oracle 可能不是平线？（以及该不该要求平）

两种情况（你必须先选“想衡量什么”）：

1) **comm-range-gating=noisy（系统级更真实）**  
   baseline/方法线的 agent set 可能随噪声略变 → AP 曲线形态会更“系统真实”。  
   但要注意：当前 `oracle_gt` 在 `online_box` 下会显式关闭 pose noise 注入（因此 oracle_gt 曲线按定义应当平线）。  
   只有“保留注噪的 oracle”（例如 `v2vloc_oracle_*`）在 `comm-range-gating=noisy` 下才可能出现轻微漂移。  
   证据（gating 敏感性差异）用：`tools/analyze_comm_range_gating_effect.py`；oracle_gt 的禁噪逻辑见 `HEAL/opencood/tools/inference_w_noise.py`。

2) **comm-range-gating=clean（更像诊断：只看对齐误差对融合的影响）**  
   agent set 固定 → oracle 应该接近平线。

注意：不管你选 noisy 还是 clean，都必须 **所有方法一致**，否则就是 confound。

### 2.3 为什么 V2V4Real 的趋势/曲线特征和 OPV2V/DAIR 不一样？

你之前踩到的是“stage1 语义不一致”而不是“数据集天生不一样”：

- V2V4Real 旧 stage1（80boxes）语义 FAIL（common frame）：
  - `inverted_rate≈0.700, ratio_rel_over_id≈0.807`
- V2V4Real per-CAV stage1 语义 PASS（local frame）：
  - `inverted_rate≈0.000, ratio_rel_over_id≈24.000`

复现命令：
```bash
./.micromamba/envs/py39/bin/python tools/validate_stage1_semantics.py \
  --stage1 HEAL/opencood/logs/v2v4real_stage1_pointpillar_from_pastat_bestval17_80boxes/test/stage1_boxes.json \
  --prefer-head200 --num-samples 20 --min-valid-samples 5

./.micromamba/envs/py39/bin/python tools/validate_stage1_semantics.py \
  --stage1 HEAL/opencood/logs/v2v4real_stage1_pointpillar_from_pastat_bestval17_percav/test/stage1_boxes.json \
  --prefer-head200 --num-samples 20 --min-valid-samples 5
```

另一个你明确指出的合理怀疑点：**backbone 不一致**会让跨数据集解释更难（见第 7 节解决）。

---

## 3) 统一合同（Semantics Freeze）—— 所有 benchmark 必须显式冻结

推荐默认（Track G：更快，允许轻微数值差异但必须 gate）：

- eval driver：`HEAL/opencood/tools/inference_w_noise.py`
- `--fusion_method intermediate`
- `--sweep-mode paired`
- `--noise-target non-ego`
- noise axis（统一）：`--pos-std-list 0,1,2,3,4,5,6,7,8,9,10`  
  `--rot-std-list 0,1,2,3,4,5,6,7,8,9,10`
- online runtime（统一 core 对比必须）：
  - `--solver-backend online_box`
  - `--runtime-mode register_and_fuse`
  - `--pose-source noisy_input`
  - `--comm-range-gating noisy`（或 clean；但禁止 auto）
- solver：
  - `--pose-device cuda`
  - `--pose-timing`
- DataLoader：`--num-workers 0`（GPU voxelization + 稳定）
- env：
  - `OPENCOOD_VOXEL_GPU=1`
  - `OMP_NUM_THREADS=1` `MKL_NUM_THREADS=1` `OPENBLAS_NUM_THREADS=1` `NUMEXPR_NUM_THREADS=1`

single 定义（统一）：
- `--pose-correction none`
- `--force-ego-input-only`
- 只跑噪声点 0（图里画 flat line）

oracle 定义（统一）：
- `--pose-correction oracle_gt`

---

## 4) 方法集合（Core vs Audit）

### 4.1 Core（no-init / no-prior）—— 主表必须包含

- bounds：
  - baseline：`none`
  - oracle：`oracle_gt`
  - single：`none + --force-ego-input-only`
- core(initfree)（统一加 `--pose-compare-current`）：
  - `v2xregpp_initfree`
  - `freealign_paper`
  - `vips_initfree`（不补 prior）
  - `cbm_initfree`（不补 prior）

> `vips/cbm` 的 prior 不需要补；你要的是“无初值”公平对比。

### 4.2 Audit（不进入 core 主表；单独报告 + 更严格 gate）

- with-init：`vips_prior / cbm_prior`
- camera-only：`imagematch_noinit / imagematch_current`
- lidar-only：`lidar_reg_*` + HKUST variants
- registration-only（Table3/paper3737）：ICP/PICP/TEASER 等

这些线必须满足更严格的 applied/no-op gate 才能引用。

---

## 5) Fail-fast Gates（P0 阻塞项：不过就别跑 full）

- G1 stage1 cache 结构：`tools/validate_stage1_cache.py --stage1 <path>`
- G2 stage1 cache 语义（local frame）：`tools/validate_stage1_semantics.py ...`
- G3 no-op gate：非 `none` 方法的 YAML 中  
  `timing_stats[*].pose_timing.pose_provider_applied_count` **不得全 0**
- G4 single 公平：禁止 `comm_range_override=0` 作为 single（必须 force-ego-input-only）
- G5 plot 合同：每个 run_dir 必须产出
  - `results_ap50_from_yaml.json`
  - `plots_yaml/noise10_<modality>_ap30|ap50|ap70(.png + _core.png)`
  - y 轴固定 0..1；x ticks 明确 0..10

---

## 6) 执行入口（10×3090 高利用率 + 容错）

### 6.1 OPV2V（推荐 autopilot）

- 入口：`tools/opv2v_benchmark_autopilot.py`（smoke→full，自愈，run_state/config_snapshot 完整）
- 建议：`--max-per-gpu 3 --num-workers 0`
- 已修复：
  - full noise list 默认含 `0..10`
  - single 定义已修复（`tools/run_opv2v_fullbench_fast.py`）

### 6.2 V2V4Real（core runner）

- 入口：`tools/run_v2v4real_core_benchmark.py`
  - 推荐：`--split-noise --max-per-gpu 2`
  - stage1 必须用 per-CAV：  
    `HEAL/opencood/logs/v2v4real_stage1_pointpillar_from_pastat_bestval17_percav/test/stage1_boxes.json`
- 汇总出图：`tools/summarize_v2v4real_core_from_yaml.py --clean-plot-dir`

### 6.3 DAIR（新 core runner，统一 online 语义）

- 若 DAIR lidar 的 v2xvit per-CAV stage1 缺失，先导出：
```bash
PYTHONPATH=$PWD/HEAL ./.micromamba/envs/py39/bin/python -u \
  HEAL/opencood/tools/export_stage1_boxes_per_cav.py \
  --hypes_yaml HEAL/opencood/logs/HeterBaseline_DAIR_lidar_v2xvit_2023_09_09_11_19_26/config.yaml \
  --stage1_checkpoint HEAL/opencood/logs/HeterBaseline_DAIR_lidar_v2xvit_2023_09_09_11_19_26/net_epoch_bestval_at17.pth \
  --output_dir data/DAIR-V2X/detected/lidar_v2xvit_stage1_percav \
  --split test
```

- 然后跑（自动 preflight + 出图）：
```bash
./.micromamba/envs/py39/bin/python -u tools/run_dair_core_benchmark.py \
  --tag <TAG> --gpus 0,1,2,3,4,5,6,7,8,9 --max-per-gpu 2 --split-noise
```

### 6.4 一键（OPV2V + V2V4Real，自动出 v2v4real plot）

```bash
./.micromamba/envs/py39/bin/python -u tools/run_core_benchmark_pipeline.py --tag <TAG>
```

> 说明：本机当前 slurm controller 不可达（`squeue` connect failure），因此默认用这些本地 scheduler 跑满 10 卡；若你后续恢复 slurm，再在外层用 sbatch 包装这些脚本即可。

---

## 7) Fully-Fair（V2XViT-unified）扩展：把 V2V4Real 的 backbone 也统一成 V2XViT

你指出的“OPV2V/DAIR 用 V2XViT，但 V2V4Real 用了别的网络”是合理 confound。想彻底公平，需要补齐：

1) 训练 V2V4Real 的 V2XViT（LiDAR + Camera）
2) 用该 checkpoint 导出 per-CAV stage1 cache（sharded + merge + 语义 gate）
3) 用同一 checkpoint + stage1，按第 3 节合同重跑 core

这一步做完后，三数据集的“core 方法对比”在解释上会干净很多（虽然跨数据集 AP 绝对值仍不建议硬横比）。
