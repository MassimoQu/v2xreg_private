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

官方入口：
- `https://mobility-lab.seas.ucla.edu/v2v4real/`（OPV2V-format 下载链接是 UCLA Box，可能需要登录）

本机当前已准备好可用的数据（见 7.2.1），无需再下载。

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
- V2V4Real 的 `vehicles.location/angle` 是 **LiDAR-local**（KITTI 风格），而 OpenCOOD 的投影逻辑假设它们是 world：已在 `HEAL/opencood/data_utils/datasets/basedataset/opv2v_basedataset.py` 自动转换为 world-frame。
- V2V4Real 官方 split 的 frame count 是 **按 ego 视角计数**（train/val/test = 14210/2000/3986），OPV2V 默认只取一个 ego：已在 `HEAL/opencood/data_utils/datasets/basedataset/v2v4real_basedataset.py` 增加 multi-ego 展开（test: 1993 -> 3986）。
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

### 7.6 当前 V2V4Real 复现实验结果（2026-01-17）

训练 run：
- run 目录：`HEAL/opencood/logs/v2v4real_pastat_noise1_fixlabels_initfcooper_ddp_g0123_2026_01_17_00_12_14`
- 初始化：`/data2/V2V4REAL/Models/PointPillar_Fcooper`
- checkpoint：`net_epoch60.pth`、`net_epoch_bestval_at17.pth`

评测（test=3986 ego-view frames，σ=1.0/1.0 (m/deg)，noise_target=all）：
- 本仓库 bestval@17：`AP030507_none_paper3986_noise11_bestval_afterfix.yaml` 为 **52.30 / 48.70 / 32.64**（AP@0.3/0.5/0.7）
- 论文 Table 2（V2V4Real, PASTAT）：**63.52 / 61.51 / 40.29**

结论：当前还差约 **12.8 AP@0.5**（以及 7.7 AP@0.7）。主要原因是：上述 run 训练阶段发生在 multi-ego 修复之前（当时 train len 只有 7105），下一步需要用 **multi-ego + 修正 label** 的新 pipeline 重新训练。

### 7.7 Multi-ego + World-label 的新训练（进行中）

当前正在训练的 run（已经启用 multi-ego 展开 + world-frame label 修复）：
- run 目录：`HEAL/opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25`
- DDP：`CUDA_VISIBLE_DEVICES=0,1,2,3`（4 卡）
- 初始化：`/data2/V2V4REAL/Models/PointPillar_Fcooper`
- 数据长度（log 打印）：train=14210, val=1496（val.zip 本身只有 748 timestamps，因此 ego-view 只有 1496；论文写 2000，可能是另一版 split）

当前训练进度建议看：
- 训练日志：`HEAL/opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25/train_stdout.log`
- 自动状态（每 60s 写一条，含 GPU util/mem）：`HEAL/opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25/live_status.jsonl`
- watchdog（会 attach 到训练，后续如遇 crash 会自动重启）：`HEAL/opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25/watchdog_stdout.log`

中途评测（test=3986，σ=1.0/1.0）：

```bash
cd /home/qqxluca/v2xreg_private/HEAL
CUDA_VISIBLE_DEVICES=8 \
MAMBA_ROOT_PREFIX=$HOME/.micromamba ~/.local/micromamba/bin/micromamba run -n heal \
python opencood/tools/inference_w_noise.py \
  --model_dir opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25 \
  --fusion_method intermediate \
  --pos-std-list 1 --rot-std-list 1 \
  --sweep-mode paired \
  --noise-target all \
  --note _paper3986_noise11
```

训练完成后本机已产出（2026-01-17）：
- bestval@17（`AP030507_none_paper3986_noise11_bestval.yaml`）：**61.54 / 57.50 / 40.04**
- epoch60（`AP030507_none_paper3986_noise11_epoch60.yaml`）：**58.24 / 54.32 / 35.57**

与论文 Table 2（V2V4Real, σ=1/1）相比：
- 论文：**63.52 / 61.51 / 40.29**
- 当前 bestval@17：AP@0.3 低 1.98，AP@0.5 低 4.01，AP@0.7 低 0.25（已经很接近 AP@0.7，但 AP@0.5 仍有差距）

### 7.8 评测口径敏感点：`score_threshold`

OpenCOOD 的后处理会先按 `score_threshold` 过滤候选框；这个阈值会显著影响 AP@0.3/0.5（recall 变化大）。

在 **同一个 bestval@17 checkpoint** 上，仅把 `score_threshold` 从 0.2 临时改到 0.05（只影响评测过滤，不改模型/权重）：
- `AP030507_none_paper3986_noise11_bestval_score005.yaml`：**65.39 / 59.12 / 40.29**

这说明：当前和论文在 AP@0.5 的差距里，存在一部分来自 **后处理/评测口径**（论文具体阈值未在 PDF 里明确）。

### 7.9 GNSS noise sweep（σ=0..4 m/deg）

用 `HEAL/opencood/tools/inference_w_noise.py:68` 做 `pos_std, rot_std = 0..4` 的 sweep（paired：`(0,0),(1,1),...,(4,4)`），并输出整条曲线到 yaml：
- `AP030507_none_final_all.yaml`：`noise_target=all`
- `AP030507_none_final_nonego.yaml`：`noise_target=non-ego`

注意：本复现的 V2V4Real 设置本质是 **GT pose + 合成噪声**，并且 `pose_confidence` 由 `lidar_pose_clean` 与 `lidar_pose` 的误差“oracle”计算（见 `HEAL/opencood/utils/pose_utils.py:23`），因此它更像论文 V2V4Real 的设定，而不是严格的“无初值/未知噪声”。

## 8. FreeAlign / V2XReg++ / PASTAT 的“无可靠初值”对比（V2V4Real 实测）

你关心的“无初值/错初值/未知噪声”更接近 **外参/位姿校正**：先用 box/occ 等线索估计相对位姿，再把对齐后的特征喂给融合检测网络。

本仓库已把 pose correction 统一接入 `HEAL/opencood/tools/inference_w_noise.py`：
- `--pose-correction none|v2xregpp_initfree|v2xregpp_stable|freealign_paper|freealign_repo`
- 需要 `--stage1-result <stage1_boxes.json>`（FreeAlign / V2XReg++ 都依赖 stage1 box cache）

### 8.1 V2V4Real（test=3986 ego-view frames）对比：σ=1m/1deg，noise_target=non-ego

使用相同 detector（PASTAT bestval@17）、相同噪声注入、相同后处理配置，仅改变 `--pose-correction`。

stage1 cache：
- `HEAL/opencood/logs/v2v4real_stage1_pointpillar_from_pastat_bestval17_80boxes/test/stage1_boxes.json`

结果（AP@0.3/0.5/0.7）：
- none：0.6178 / 0.5763 / 0.4011（`AP030507_none_paper3986_noise11_nonego.yaml`）
- v2xregpp_initfree：0.6189 / 0.5774 / 0.4032（`AP030507_v2xregpp_initfree_paper3986_noise11_nonego.yaml`）
- freealign_paper：0.5823 / 0.5543 / 0.3942（`AP030507_freealign_paper_paper3986_noise11_nonego.yaml`）

对应的相对位姿误差统计（mean，单位 m/deg；越小越好）：
- none：1.248 / 0.791
- v2xregpp_initfree：1.027 / 0.711（对齐略有改善，AP 也略升）
- freealign_paper：29.117 / 50.438（大量帧对齐失败；FreeAlign 依赖 co-view objects，V2V4Real 上 overlap 稀疏时非常不稳定）

### 8.2 失败原因示例（FreeAlign：prior-free 但依赖 overlap）

在 `idx=0`（stage1 cache 的第 0 帧）里，两车真实相对平移约 75m，但 FreeAlign 估计成 ~10m 量级，导致相对误差 ~70m：
- `true T_ego_cav: xy≈(-75.7, 5.2)m, yaw≈-16.7°`
- `freealign est: xy≈(-6.6, -9.5)m, yaw≈-0.24°`

这类场景里两车 co-view objects 很少，图匹配容易产生错误对应，从而让刚体估计崩掉；这也是论文 Fig.1(b) 对 FreeAlign 的核心批评点。

### 8.3 子集 stress test（前 200 帧，σ=0/2/4/8，noise_target=non-ego）

为了快速观察“大噪声 + init-free”的趋势，我在前 200 帧上做了 `(0,0),(2,2),(4,4),(8,8)` sweep：
- `AP030507_none_robust_head200.yaml`
- `AP030507_v2xregpp_initfree_robust_head200.yaml`
- `AP030507_freealign_paper_robust_head200.yaml`

注意：这是 **子集**（不是论文指标口径），但可以直观看到：FreeAlign 在该子集上 AP 明显掉到 ~0.50 且相对位姿误差非常大；V2XReg++ 整体更稳。

### 8.4 全量曲线：σ=0..4（m/deg），comm_range=200（V2V4Real test=3986）

为了严格保证“协同感知部分完全一样”，这里 **强制 `comm_range=200`**（`--comm-range-override 200`），避免噪声改变 agent 间距离筛选，从而把 “通信拓扑变化” 混进对齐方法对比里。

配置：
- detector：PASTAT bestval@17（同 8.1）
- 噪声：Gaussian，paired sweep：`(pos_std,rot_std)=(0,0),(1,1),...,(4,4)`，`noise_target=non-ego`
- stage1 cache（V2XReg++ / FreeAlign 共用）：`HEAL/opencood/logs/v2v4real_stage1_pointpillar_from_pastat_bestval17_80boxes/test/stage1_boxes.json`

运行命令（示例：V2XReg++；其它方法只改 `--pose-correction`）：

```bash
cd /home/qqxluca/v2xreg_private/HEAL
CUDA_VISIBLE_DEVICES=0 \
MAMBA_ROOT_PREFIX=$HOME/.micromamba ~/.local/micromamba/bin/micromamba run -n heal \
python opencood/tools/inference_w_noise.py \
  --model_dir opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25 \
  --fusion_method intermediate \
  --pos-std-list 0,1,2,3,4 --rot-std-list 0,1,2,3,4 \
  --sweep-mode paired \
  --noise-target non-ego \
  --comm-range-override 200 \
  --num-workers 0 \
  --save_vis_interval 100000000 \
  --log-interval 400 \
  --note _comm200_paper \
  --pose-correction v2xregpp_initfree \
  --stage1-result opencood/logs/v2v4real_stage1_pointpillar_from_pastat_bestval17_80boxes/test/stage1_boxes.json
```

输出（曲线 yaml）：
- none：`AP030507_none_comm200_paper.yaml`
- v2xregpp_initfree：`AP030507_v2xregpp_initfree_comm200_paper.yaml`
- freealign_paper：`AP030507_freealign_paper_comm200_paper.yaml`

绘制曲线：
- AP@0.5：`docs/operations/v2v4real_extrinsic_sweep_comm200_paper_ap50.png`
- AP@0.3/0.5/0.7：`docs/operations/v2v4real_extrinsic_sweep_comm200_paper_ap.png`

结果（AP@0.3 / 0.5 / 0.7）：

**none**
- σ=0：0.6181 / 0.5751 / 0.4014
- σ=1：0.6142 / 0.5722 / 0.3977
- σ=2：0.6079 / 0.5686 / 0.3955
- σ=3：0.5991 / 0.5627 / 0.3941
- σ=4：0.5942 / 0.5602 / 0.3926

**v2xregpp_initfree**
- σ=0：0.6183 / 0.5753 / 0.4016
- σ=1：0.6153 / 0.5734 / 0.3999
- σ=2：0.6094 / 0.5698 / 0.3984
- σ=3：0.6028 / 0.5658 / 0.3973
- σ=4：0.5978 / 0.5627 / 0.3950

**freealign_paper**
- σ=0：0.5809 / 0.5529 / 0.3932
- σ=1：0.5808 / 0.5527 / 0.3928
- σ=2：0.5799 / 0.5522 / 0.3931
- σ=3：0.5795 / 0.5519 / 0.3928
- σ=4：0.5789 / 0.5516 / 0.3928

对应的相对位姿误差（mean，单位 m/deg；越小越好）：
- none：σ=4 时约 **5.019m / 3.149°**
- v2xregpp_initfree：σ=4 时约 **3.999m / 2.556°**（比 none 稍好，因此 AP 也有小幅提升）
- freealign_paper：σ=0..4 始终约 **29m / 50°**（灾难性错误匹配占比高，导致整体检测显著变差且对噪声不敏感）

备注：
- `freealign_repo`（ported released repo matching）在 test=3986、默认 `max_boxes=60` 下耗时过高，4h 预算内跑不完；如果你需要这条曲线，我可以：
  1) 先用更小的 `--freealign-max-boxes` 跑完整曲线（速度更快但可能影响其最优性能）；或
  2) 针对 `HEAL/opencood/pose/freealign_repo.py` 做等价加速（不改变输出）后再跑。
