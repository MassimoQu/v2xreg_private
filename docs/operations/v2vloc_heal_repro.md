# V2VLoc (AAAI'26) 在 HEAL(OpenCOOD) 复现笔记（DAIR-V2X）

这份笔记对应 `docs/v2vloc.pdf` 的两大组件：
- **PGC**：Pose Generator with Confidence（生成 pose + confidence）
- **PASTAT**：Pose-Aware Spatio-Temporal Alignment Transformer（CE+FSA+Transformer 融合）

本仓库的实现入口在 `HEAL/opencood/` 下。

## 0. 论文方法、数据集、指标（摘自 `docs/v2vloc.pdf`）

### 0.1 方法在做什么（PGC + PASTAT）

- **PGC (Pose Generator with Confidence)**：回归式 LiDAR localization，直接从 raw point cloud 预测 pose，并额外预测 pose error `epsilon`；pose confidence 由论文 Eq.(6) 给出：`sigma = 1 / (1 + epsilon^2)`；用 RANSAC 得到最终 poses/confidences；训练时用 RSD (Redundant Sample Downsampling) 加速。
- **PASTAT (Pose-Aware Spatio-Temporal Alignment Transformer)**：
  - **CE (Confidence Embedding)**：把 PGC 的 `sigma` 归一化后拼到特征上（论文 Eq.(7)）。
  - **FSA (Feature Spatial Alignment)**：预测 3-DoF 的 feature offset（`dx, dy, dtheta`）做更精细的对齐。
  - **TE + Transformer**：把多帧对齐特征 flatten 成 token，加入 temporal encoding（论文 Eq.(10)~(12)），再用 ViT encoder 做全局时空建模。

### 0.2 论文使用的数据集

- **V2VLoc（作者新建）**：包含 Town1Loc / Town4Loc / V2VDet，提供 multi-traversal scans + 3D box 标注；论文给的检测 split：train/val/test = 6697/2017/2884 帧。
- **V2V4Real（真实数据）**：论文给的 split：train/val/test = 14210/2000/3986 帧；并写明每个地点只有 single traversal，因此 **不在 V2V4Real 上训练 PGC**（否则会对场景几何过拟合）。

### 0.3 论文报告的检测指标（Table 2）

Table 2 是 vehicle class 的 `AP@0.3 / 0.5 / 0.7`：

**V2V4Real**
- No Fusion: 47.50 / 39.83 / 22.02
- Late Fusion: 40.18 / 34.60 / 15.64
- Where2comm: 61.30 / 57.61 / 37.75
- CoBEVT: 59.03 / 56.11 / 34.69
- V2X-ViT: 60.15 / 56.90 / 35.84
- CoAlign: 62.11 / 58.93 / 34.38
- ERMVP: 60.86 / 58.90 / 38.74
- TraF-Align: 62.11 / 56.11 / 31.54
- **PASTAT (Ours): 63.52 / 61.51 / 40.29**

**V2VDet**
- No Fusion: 40.16 / 37.28 / 22.31
- Late Fusion: 50.88 / 47.53 / 29.58
- Where2comm: 57.80 / 49.38 / 33.95
- CoBEVT: 63.68 / 59.50 / 39.11
- V2X-ViT: 67.52 / 62.70 / 43.46
- CoAlign: 66.75 / 62.98 / 37.50
- ERMVP: 67.86 / 64.24 / 47.13
- TraF-Align: 72.65 / 66.75 / 48.29
- **PASTAT (Ours): 76.97 / 71.15 / 52.55**

### 0.4 论文训练超参（Implementation Details）

- **PGC**：AdamW，lr=1e-3，weight_decay=1200，100 epochs，batch size=100，24 workers。
- **PASTAT**：基于 OpenCOOD，PointPillars backbone，60 epochs，batch size=2，Adam lr=0.001 wd=1e-4，MultiStep(15,50)；论文用 4x RTX3090。

### 0.5 论文鲁棒性表（Table 4，V2VDet + GNSS noise）

Table 4 在 V2VDet 上做 `pos/rot Gaussian noise σ=0..4 (m/deg)`：

- 随着 GNSS noise 增大，绝大多数 fusion 方法 AP 明显下降（见论文 Table 4）。
- **PASTAT(Ours)** 不使用 GNSS pose（而是用 PGC），因此不受 GNSS noise 影响，论文表里只给了常数：**76.97 / 71.15 / 52.55**（AP@0.3/0.5/0.7）。

## 1. 环境

本机使用 micromamba 环境 `heal`：

```bash
cd /home/qqxluca/v2xreg_private/HEAL
MAMBA_ROOT_PREFIX=$HOME/.micromamba ~/.local/micromamba/bin/micromamba run -n heal python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

## 2. 关于 DAIR/OPV2V 的 PGC 训练（为什么我们先不训 PGC）

论文在 V2V4Real 上明确说明：由于**每个地点只有单次 traversal**，不训练 PGC（否则会过拟合场景几何），而是用 **GT pose + 1.0/1.0 噪声**，并由 pose error 得到 confidence。

DAIR/OPV2V与 V2V4Real 更接近，因此这里推荐：
- **训练/评测 PASTAT：使用 GT pose + 合成噪声**（见下文 `noise_setting` 与 `inference_w_noise.py`）。本 repo 里按论文 Eq.(6) 做了 `pose_confidence` 注入（`HEAL/opencood/utils/pose_utils.py`）。
- 若你后续拿到多 traversal 的定位数据（或自建），再用 `HEAL/opencood/tools/train_v2vloc_pgc.py` 训练 PGC。

这里的 traversal 指的是“同一地点/路段的多次重复采集（多趟）”，而不是“闭环”。论文的核心点是：训练/测试 traversal 必须不同，否则回归式 LiDAR localization 很容易记住场景几何。

## 3. 训练 PASTAT（DAIR）

### 3.1 全量训练（论文式：带 pose 噪声）

配置：`HEAL/opencood/hypes_yaml/dairv2x/LiDAROnly/lidar_pastat_noise1.yaml`

```bash
cd /home/qqxluca/v2xreg_private/HEAL
CUDA_VISIBLE_DEVICES=9 \
MAMBA_ROOT_PREFIX=$HOME/.micromamba ~/.local/micromamba/bin/micromamba run -n heal \
python opencood/tools/train.py \
  -y opencood/hypes_yaml/dairv2x/LiDAROnly/lidar_pastat_noise1.yaml \
  --fusion_method intermediate
```

更贴近“只噪声化非 ego”的设定（避免把全局参考系也噪声化）建议用：
- `HEAL/opencood/hypes_yaml/dairv2x/LiDAROnly/lidar_pastat_noise1_nonego.yaml`

### 3.2 子集快速跑通（debug）

配置：`HEAL/opencood/hypes_yaml/dairv2x/LiDAROnly/lidar_pastat_subset_noise1.yaml`（train_400 / val_200）

```bash
cd /home/qqxluca/v2xreg_private/HEAL
CUDA_VISIBLE_DEVICES=9 \
MAMBA_ROOT_PREFIX=$HOME/.micromamba ~/.local/micromamba/bin/micromamba run -n heal \
python opencood/tools/train.py \
  -y opencood/hypes_yaml/dairv2x/LiDAROnly/lidar_pastat_subset_noise1.yaml \
  --fusion_method intermediate
```

### 3.3 用已有模型初始化（更快收敛）

`train.py` 新增了 `--init_model_dir`：加载权重但不继承 epoch/优化器（用于 fine-tune）。

```bash
cd /home/qqxluca/v2xreg_private/HEAL
CUDA_VISIBLE_DEVICES=9 \
MAMBA_ROOT_PREFIX=$HOME/.micromamba ~/.local/micromamba/bin/micromamba run -n heal \
python opencood/tools/train.py \
  -y opencood/hypes_yaml/dairv2x/LiDAROnly/lidar_pastat.yaml \
  --init_model_dir opencood/logs/HeterBaseline_DAIR_lidar_fcooper_2023_09_09_19_23_43 \
  --fusion_method intermediate
```

### 3.4 debug 用的加速参数

`train.py` 新增：
- `--max_epochs N`
- `--max_train_steps K`
- `--max_val_steps K`
- `--no_test`（跳过训练结束后的自动 inference）

例如仅跑通 1 个 epoch、每个 epoch 10 step：

```bash
python opencood/tools/train.py -y opencood/hypes_yaml/dairv2x/LiDAROnly/lidar_pastat_subset_noise1.yaml \
  --init_model_dir opencood/logs/HeterBaseline_DAIR_lidar_fcooper_2023_09_09_19_23_43 \
  --max_epochs 1 --max_train_steps 10 --max_val_steps 3 --no_test
```

## 4. 噪声鲁棒性评测（对应论文 Table 4 的“GNSS noise sweep”形式）

用 `HEAL/opencood/tools/inference_w_noise.py` 做 GNSS 噪声 sweep：

```bash
cd /home/qqxluca/v2xreg_private/HEAL
CUDA_VISIBLE_DEVICES=9 \
MAMBA_ROOT_PREFIX=$HOME/.micromamba ~/.local/micromamba/bin/micromamba run -n heal \
python opencood/tools/inference_w_noise.py \
  --model_dir opencood/logs/<YOUR_TRAINED_MODEL_DIR> \
  --fusion_method intermediate \
  --pos-std-list 0,1,2,3,4 \
  --rot-std-list 0,1,2,3,4 \
  --sweep-mode paired \
  --noise-target all
```

如果希望“请求的 std 就是相对误差 std”（更适合对齐实验设定），可用：
- `--noise-target non-ego`

### 4.1 自动等待训练结束并跑完整 sweep（推荐）

训练结束后再跑 sweep，避免抢 GPU。脚本会同时跑 `noise-target=all` 和 `noise-target=non-ego` 两条曲线（各占 1 张卡）：

```bash
cd /home/qqxluca/v2xreg_private/HEAL
MODEL_DIR=opencood/logs/<YOUR_TRAINED_MODEL_DIR>
nohup bash opencood/tools/watch_train_and_sweep.sh "$MODEL_DIR" > "$MODEL_DIR/watch_and_sweep.log" 2>&1 &
tail -f "$MODEL_DIR/watch_and_sweep.log"
```

## 5. （可选）PGC pose 注入到 PASTAT

如果你能训练出可用的 PGC（需要多 traversal 的定位数据），可先导出 JSON：

```bash
python opencood/tools/infer_v2vloc_pgc_pose.py ...
```

然后在检测训练 yaml 中加：

```yaml
pgc_pose:
  train_result: "/abs/or/rel/path/train.json"
  val_result: "/abs/or/rel/path/val.json"
```

示例配置：`HEAL/opencood/hypes_yaml/dairv2x/LiDAROnly/lidar_pastat_pgc.yaml`（注意 `pgc_pose` 必须是顶层 key）。

## 6. 本次复现（DAIR-V2X-C）代表性方案与结果

### 6.1 数据与协议

- 数据：DAIR-V2X-C（cooperative vehicle-infrastructure）。本机用 symlink：`dataset/my_dair_v2x/v2x_c/cooperative-vehicle-infrastructure -> /mnt/data2_proxy/DAIR-V2X-C/cooperative-vehicle-infrastructure`
- 评测：`inference_w_noise.py` 做 `pos_std, rot_std = 0..4 (m/deg)` sweep；输出在对应 `model_dir` 下的 `AP030507_*.yaml`（以及每个噪声点的 `eval_*.yaml`）
- 说明：`noise_target=non-ego` 更像“相对位姿有噪声”；`noise_target=all` 会把 ego 的全局参考系也噪声化，在 world-frame 评测下性能会极快崩掉（对任何 method 都基本如此），所以我们把两条曲线都记录下来。

### 6.2 Baseline：F-Cooper（已有日志目录）

- 模型目录：`HEAL/opencood/logs/HeterBaseline_DAIR_lidar_fcooper_2023_09_09_19_23_43`
- σ=0（clean）AP@0.3/0.5/0.7：0.5605 / 0.4307 / 0.2592
- non-ego 噪声鲁棒性（AP@0.5, σ=0..4）：0.4307, 0.3421, 0.3197, 0.3026, 0.2976
- all 噪声（AP@0.5, σ=0..4）：0.4308, 0.02384, 0.00298, 0.000893, 0.000493

### 6.3 PASTAT（clean）从 F-Cooper 初始化 fine-tune（clean 最强）

- 模型目录：`HEAL/opencood/logs/HeterBaseline_DAIR_lidar_pastat_ftfcooper_clean_2026_01_14_22_51_01`
- σ=0（clean）AP@0.3/0.5/0.7：0.6907 / 0.5766 / 0.3960
- non-ego 噪声鲁棒性（AP@0.5, σ=0..4）：0.5766, 0.4461, 0.3967, 0.3780, 0.3671
- all 噪声（AP@0.5, σ=0..4）：0.5766, 0.03335, 0.00518, 0.00190, 0.00100

### 6.4 PASTAT（non-ego σ=1/1）噪声鲁棒 fine-tune（更抗噪）

- 模型目录：`HEAL/opencood/logs/HeterBaseline_DAIR_lidar_pastat_noise1_nonego_ft_2026_01_15_01_03_58`
- σ=0（clean）AP@0.3/0.5/0.7：0.6572 / 0.5382 / 0.3883
- non-ego 噪声鲁棒性（AP@0.5, σ=0..4）：0.5382, 0.4712, 0.4214, 0.3968, 0.3873
- all 噪声（AP@0.5, σ=0..4）：0.5382, 0.03502, 0.00647, 0.00207, 0.00105

### 6.5 推荐怎么选（在 DAIR 上的“高性能”取舍）

- 只看 clean（σ=0）AP：优先用 `...pastat_ftfcooper_clean_2026_01_14_22_51_01`
- 更关心非 ego 相对位姿有噪声（σ>=1）的鲁棒：优先用 `...pastat_noise1_nonego_ft_2026_01_15_01_03_58`

### 6.6 本次复现涉及的关键代码/脚本（便于追溯）

- pose confidence（论文 Eq.(6)）：`HEAL/opencood/utils/pose_utils.py`
- 训练恢复策略（resume latest epoch）：`HEAL/opencood/tools/train_utils.py`, `HEAL/opencood/tools/train.py`, `HEAL/opencood/tools/train_ddp.py`
- init-only fine-tune：`HEAL/opencood/tools/train.py`, `HEAL/opencood/tools/train_ddp.py`（`--init_model_dir`）
- 噪声 sweep：`HEAL/opencood/tools/inference_w_noise.py`, `HEAL/opencood/tools/run_noise_sweep.sh`
- 训练监控/自动重启：`HEAL/opencood/tools/train_watchdog.py`, `HEAL/opencood/tools/live_train_status.py`

## 7. V2V4Real 复现（论文 Table 2 的“同数据集同设置”）

### 7.1 数据下载现状（重要）

目前能找到的官方入口是：
- 论文/官方仓库指向的下载页：`https://mobility-lab.seas.ucla.edu/v2v4real/`

但该页面给出的 **LiDAR+Labels(OPV2V format)** 下载链接是 `ucla.app.box.com/...`，在本环境下会跳转到 `ucla.account.box.com/login`（需要 UCLA Box 登录）。

结论：**如果你没有可用的 Box 访问方式，我们无法在服务器上“全自动下载” V2V4Real 的 OPV2V-format 原始数据。**

可行的方式是二选一：
1) 你手动把数据放到本机 `/data2/v2v4real/{train,validate,test}`（或提供一个不需要登录的直链/镜像）。
2) 你提供可用的下载方式（例如内部镜像路径、或你已下载好的压缩包路径），我再在服务器上解压并接入 HEAL。

### 7.2 HEAL 侧已准备好的配置（拿到数据即可开跑）

我已经在 HEAL(OpenCOOD) 里补了 `v2v4real` 数据集别名 + 训练 yaml：
- 数据集别名：`HEAL/opencood/data_utils/datasets/basedataset/v2v4real_basedataset.py`
- dataset 注册：`HEAL/opencood/data_utils/datasets/__init__.py`
- 训练 yaml（clean）：`HEAL/opencood/hypes_yaml/v2v4real/LiDAROnly/lidar_pastat.yaml`
- 训练 yaml（论文式 1m/1deg 噪声）：`HEAL/opencood/hypes_yaml/v2v4real/LiDAROnly/lidar_pastat_noise1.yaml`

数据放置建议（和 yaml 对应）：

```bash
mkdir -p /data2/v2v4real
ln -sfn /data2/v2v4real /home/qqxluca/v2xreg_private/HEAL/dataset/v2v4real
ls -lah /home/qqxluca/v2xreg_private/HEAL/dataset/v2v4real
```

### 7.2.1 本机实测的数据路径（2026-01-16）

本机已拿到的数据包位于：
- `/data2/V2V4REAL/Data/*.zip`（train_01..08, test_01..03, val.zip）

解压后的 OPV2V 目录位于：
- `/data2/v2v4real/{train,validate,test}`
- 并在 HEAL 内建立 symlink：`HEAL/dataset/v2v4real -> /data2/v2v4real`

### 7.3 训练命令（数据就绪后）

```bash
cd /home/qqxluca/v2xreg_private/HEAL
CUDA_VISIBLE_DEVICES=0,1,2,3 \
MAMBA_ROOT_PREFIX=$HOME/.micromamba ~/.local/micromamba/bin/micromamba run -n heal \
python opencood/tools/train_ddp.py \
  -y opencood/hypes_yaml/v2v4real/LiDAROnly/lidar_pastat_noise1.yaml \
  --fusion_method intermediate
```

### 7.4 关键兼容修复（V2V4Real 必需）

- V2V4Real 的 yaml 里 `lidar_pose` 是 `4x4` 矩阵；OpenCOOD pipeline 期望 `6-DoF` pose 向量：已在 `HEAL/opencood/data_utils/datasets/basedataset/opv2v_basedataset.py` 自动转换（`tfm_to_pose`）。
- `PointPillarBaseline` 在 PASTAT 分支缺少 `import torch`：已在 `HEAL/opencood/models/point_pillar_baseline.py` 补齐。

### 7.5 训练监控（推荐）

用 watchdog 自动重启/防卡死（DDP）：

```bash
cd /home/qqxluca/v2xreg_private/HEAL
MODEL_DIR=opencood/logs/<YOUR_RUN_DIR>
CUDA_VISIBLE_DEVICES=4,5,6,7 \
MAMBA_ROOT_PREFIX=$HOME/.micromamba ~/.local/micromamba/bin/micromamba run -n heal \
python opencood/tools/train_watchdog.py \
  --yaml opencood/hypes_yaml/v2v4real/LiDAROnly/lidar_pastat_noise1.yaml \
  --model_dir "$MODEL_DIR" \
  --cuda_visible_devices 4,5,6,7 \
  --nproc 4 \
  --num_workers 4 \
  --run_sweep_on_finish
```
