# Non-invasive Dataset Adaptation (V2V4Real / OPV2V / DAIR-V2X-C)

目标：不改动 `/data2/...` 数据内容，通过 **代码 + 配置 + 额外 split 文件**，让三套数据在 HEAL(OpenCOOD) 下更适合做：
- 训练/评测协同检测（PASTAT / baseline / freealign / v2xreg++ …）
- 训练/评测 PGC 这类 “LiDAR 回归式定位” 组件时，尽量避免 split 泄漏

## 1) 已做的代码改造（对数据集零侵入）

### 1.1 OPV2V / V2V4Real：支持按 scenario 白/黑名单过滤

文件：`HEAL/opencood/data_utils/datasets/basedataset/opv2v_basedataset.py`

新增可选配置：
```yaml
scenario_list:            # list | path | {train/val/test: ...}
scenario_blacklist:       # list | path | {train/val/test: ...}
```

用于：
- V2V4Real 去除 train/test 重复 scenario（防止数据泄漏）
- OPV2V 固定使用某一组 scenario（复现实验或做子集）

### 1.2 三数据集 split 生成脚本（输出到 repo 内）

文件：`HEAL/opencood/tools/make_dataset_splits.py`

功能：
- `v2v4real`：导出 `train/val/test` 的 scenario 列表，并可做 train/test overlap 去重
- `opv2v`：导出 `train/val/test` 的 scenario 列表
- `dair`：基于 `intersection_loc + batch_id` 生成 traversal-safe 的 `train.json/val.json(/test.json)`

## 2) 已生成的 split 文件（当前机器）

### 2.1 V2V4Real（dedup_keep_test）

目录：`HEAL/opencood/splits/v2v4real/dedup_keep_test/`
- `train_scenarios.json`（已移除 train/test overlap）
- `val_scenarios.json`
- `test_scenarios.json`
- `report.json`

注意：本机这份 V2V4Real 数据存在 1 个 scenario 同时出现在 train 和 test（内容一致）。dedup 方案默认 **保留 test，train 删除**。

### 2.2 OPV2V（default）

目录：`HEAL/opencood/splits/opv2v/default/`
- `train_scenarios.json`
- `val_scenarios.json`
- `test_scenarios.json`
- `report.json`

### 2.3 DAIR-V2X-C（traversal_safe_seed303_val0.2_test0.0）

目录：`HEAL/opencood/splits/dairv2x/traversal_safe_seed303_val0.2_test0.0/`
- `train.json`（list of dict: `veh_frame_id/inf_frame_id/...`）
- `val.json`
- `report.json`

性质：同一 `intersection_loc` 内 **train/val 不共享任何 batch_id**（避免 “同一趟 clip” 同时进 train/val 的泄漏）。

## 3) 对应配置文件（直接可用）

### 3.1 V2V4Real（dedup + noise1）

`HEAL/opencood/hypes_yaml/v2v4real/LiDAROnly/lidar_pastat_noise1_dedup.yaml`

### 3.2 OPV2V（PASTAT）

- `HEAL/opencood/hypes_yaml/opv2v/LiDAROnly/lidar_pastat.yaml`
- `HEAL/opencood/hypes_yaml/opv2v/LiDAROnly/lidar_pastat_noise1.yaml`

### 3.3 DAIR（traversal-safe + noise1 + non-ego）

`HEAL/opencood/hypes_yaml/dairv2x/LiDAROnly/lidar_pastat_noise1_nonego_traversal_safe.yaml`

## 4) 重新生成 split 的命令（可复现/可换 seed）

在 `HEAL/` 下：

```bash
MAMBA_ROOT_PREFIX=$HOME/.micromamba ~/.local/micromamba/bin/micromamba run -n heal \
python opencood/tools/make_dataset_splits.py v2v4real \
  --data_dir /data2/v2v4real \
  --out_dir opencood/splits/v2v4real/dedup_keep_test

MAMBA_ROOT_PREFIX=$HOME/.micromamba ~/.local/micromamba/bin/micromamba run -n heal \
python opencood/tools/make_dataset_splits.py opv2v \
  --data_dir /data2/OPV2V \
  --out_dir opencood/splits/opv2v/default

MAMBA_ROOT_PREFIX=$HOME/.micromamba ~/.local/micromamba/bin/micromamba run -n heal \
python opencood/tools/make_dataset_splits.py dair \
  --data_dir /data2/DAIR-V2X-C/cooperative-vehicle-infrastructure \
  --out_dir opencood/splits/dairv2x/traversal_safe_seed303_val0.2_test0.0 \
  --seed 303 --val_ratio 0.2 --test_ratio 0.0 --group_by intersection_batch
```

