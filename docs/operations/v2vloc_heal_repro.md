# V2VLoc (AAAI'26) 在 HEAL(OpenCOOD) 复现笔记（DAIR-V2X）

这份笔记对应 `docs/v2vloc.pdf` 的两大组件：
- **PGC**：Pose Generator with Confidence（生成 pose + confidence）
- **PASTAT**：Pose-Aware Spatio-Temporal Alignment Transformer（CE+FSA+Transformer 融合）

本仓库的实现入口在 `HEAL/opencood/` 下。

相关文档导航（本 repo 内）：
- 论文原文：`docs/v2vloc.pdf`
- 本文（复现/训练/评测主入口）：`docs/operations/v2vloc_heal_repro.md`
- V2V4Real 噪声 sweep 每条曲线的定义与解释：`docs/operations/v2v4real_noise_sweep_methods.md`
- 统一进度/结果汇总（含 V2V4Real comm=200 noise sweep 数字）：`docs/operations/experiment_progress.md`
- 外参噪声/对齐链路的实现细节记录：`docs/operations/heal_pose_alignment_noise_robustness.md`
- stable 模式（时序滤波）定义与复现方式：`docs/operations/heal_pose_alignment_stable_noise_sweep.md`
- 数据集适配（non-invasive）：`docs/operations/dataset_adaptation_non_invasive.md`

## 0. 论文方法、数据集、指标（摘自 `docs/v2vloc.pdf`）

### 0.1 方法在做什么（PGC + PASTAT）

- **PGC (Pose Generator with Confidence)**：回归式 LiDAR localization，直接从 raw point cloud 预测 pose，并额外预测 pose error `epsilon`；pose confidence 由论文 Eq.(6) 给出：`sigma = 1 / (1 + epsilon^2)`；用 RANSAC 得到最终 poses/confidences；训练时用 RSD (Redundant Sample Downsampling) 加速。
- **PASTAT (Pose-Aware Spatio-Temporal Alignment Transformer)**：
  - **CE (Confidence Embedding)**：把 PGC 的 `sigma` 归一化后拼到特征上（论文 Eq.(7)）。
  - **FSA (Feature Spatial Alignment)**：预测 3-DoF 的 feature offset（`dx, dy, dtheta`）做更精细的对齐。
  - **TE + Transformer**：把多帧对齐特征 flatten 成 token，加入 temporal encoding（论文 Eq.(10)~(12)），再用 ViT encoder 做全局时空建模。

> 备注（实现差异）：本仓库的 `PASTATFusion` 当前实现的是 **“pose 粗对齐 + CE + FSA + Transformer 融合”** 的主干，
> temporal 相关的 prior/encoding 在默认配置下为 0（没有显式多帧 token）。详见下文 **2.3** 的代码映射。

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

## 2.1 PGC（Pose Generator with Confidence）代码级细节（本仓库实现）

这一节把上面“PGC 做什么”的一句话拆成可复现/可调参的工程细节，方便你后续把 PGC 当作“外参求解模块”去迁移/改造。

### 2.1.1 PGC 的监督信号：不是直接回归 pose，而是回归每个点的 world 坐标（SCR）

在本仓库实现里，PGC 训练目标是 **Scene Coordinate Regression (SCR)**：
- 输入：单帧点云 `points (N,4)`（xyz + intensity）
- 输出：`y_pred (N,3)`，表示每个输入点在 world 坐标系下的预测位置
- 额外输出：`epsilon`（每帧 1 个标量），作为误差代理，用于计算 pose confidence

实现：
- 网络：`HEAL/opencood/pose/pgc.py:40`（`PGCNet`）
- pose confidence：`HEAL/opencood/pose/pgc.py:99`（`sigma = 1/(1+eps^2)`）

训练时 `y_gt` 的构造方式：用 GT pose 把 LiDAR 点变到 world：
- `y_gt = pose_to_tfm(pose) @ [x,y,z,1]^T`
- 代码：`HEAL/opencood/tools/train_v2vloc_pgc.py:97`（`_world_coords`）

### 2.1.2 RSD 下采样（Redundant Sample Downsampling）

论文里的 RSD 在工程上主要是“固定点数 + 去冗余”，以便 batch 训练稳定。

本仓库实现是近似版：
- 先对 XYZ 做 voxelize（每个 voxel 至多取 1 个点）
- 再随机采样/补齐到固定 `num_points`
- 代码：`HEAL/opencood/pose/pgc.py:12`（`rsd_downsample`）

### 2.1.3 网络结构（PGCNet）：PointNet + 全局特征回灌

结构要点：
- `encoder`：1x1 Conv + BN + ReLU（PointNet 风格）提取 per-point feature
- `g = maxpool(feat)` 得到全局场景描述
- 把 `g` 拼回每个点 feature，再回归每点 world XYZ（保证“同一个局部形状在不同场景可分”）
- 单独的 `err_head(g)` 回归 `epsilon`

代码：`HEAL/opencood/pose/pgc.py:40`

### 2.1.4 损失函数：点误差 + 误差代理一致性（epsilon）

本仓库实现对齐论文 Eq.(4)(5) 的形式（以每帧平均点误差 `u` 为主）：
- `u = mean_i || y_pred_i - y_gt_i ||`
- `L = mean( u + |u - epsilon_pred| )`

代码：`HEAL/opencood/tools/train_v2vloc_pgc.py:173`

### 2.1.5 从 SCR 输出恢复 pose：RANSAC + Kabsch（SE(3)）

有了对应关系 `(p_i (LiDAR),  Xhat_i (world))` 后，用 RANSAC(Kabsch) 解刚体变换 `T`：
- 每次采 3 对点算一次 Kabsch
- 统计 inliers（阈值 `ransac_inlier_th`）
- inliers 足够则用 inliers 再拟合一次，否则回退到全点拟合

实现：
- Kabsch：`HEAL/opencood/pose/pgc.py:103`（`_kabsch_se3`）
- RANSAC：`HEAL/opencood/pose/pgc.py:122`（`ransac_se3`）
- 推理入口：`HEAL/opencood/pose/pgc.py:186`（`infer_pose_and_confidence`）

### 2.1.6 coord_scale：解决“大坐标数值条件差”的缩放开关

如果 world 坐标量级很大（例如 UTM/GNSS 风格上千米），直接回归会很难优化。

本仓库提供 `coord_scale`：
- 训练时：同时缩放输入点 XYZ 和 GT pose 平移
- 推理时：同样缩放点，再在缩放坐标系内做 RANSAC，最后把平移缩放回米

实现：
- train：`HEAL/opencood/tools/train_v2vloc_pgc.py:148`
- infer：`HEAL/opencood/pose/pgc.py:171`

### 2.1.7 PGC 的脚本链路（训练→导出→评测→接入协同感知）

训练（保存 `.pth`）：
- `HEAL/opencood/tools/train_v2vloc_pgc.py:1`

导出每帧每车的 pose JSON（供协同感知侧 pose override 用）：
- `HEAL/opencood/tools/infer_v2vloc_pgc_pose.py:1`

评测 PGC pose JSON 相对位姿误差（ego->cav 的 TE/RE）：
- `HEAL/opencood/tools/eval_pgc_pose_json.py:1`

训练过程自动监控（每隔 N 秒抓最新 ckpt，跑一遍 infer+eval，append 到 jsonl）：
- `HEAL/opencood/tools/pgc_quick_eval_watch.py:1`

## 2.2 PGC 如何作为“外参/位姿求解模块”接入 HEAL（只替换对齐模块）

我们把 PGC 的输出当作一个“stage-1 pose cache”，**先由外部 pose solver 生成 override map**，
dataset 只负责注入 `lidar_pose`，从而改变后续的 `pairwise_t_matrix`（也就是特征对齐矩阵）。

### 2.2.1 JSON 格式与字段

`infer_v2vloc_pgc_pose.py` 输出的 JSON 大致是：
- `sample_idx -> { cav_id_list: [...], lidar_pose_pred_np: [[x,y,z,roll,yaw,pitch], ...], pose_confidence_np: [...] }`

对应实现：`HEAL/opencood/tools/infer_v2vloc_pgc_pose.py:73`

### 2.2.2 注入点：在 comm-range 过滤前先应用 override

原因：如果先按 noisy pose 做 comm-range filtering，可能把“本应在范围内”的 agent 过滤掉，
后续再纠正 pose 也没用了。

实现位置：
- solver：`HEAL/opencood/extrinsics/pose_correction/pose_solver.py`
- 注入：`HEAL/opencood/utils/pose_utils.py:108`（`apply_pose_overrides`，在 dataset 内部 pre-filter 调用）

### 2.2.3 initfree vs stable（这里的 stable 不是“更无初值”，而是“有状态时序滤波”）

`Stage1PGCPoseCorrector` 支持两种模式：
- `initfree`：直接用预测相对位姿 `T_est` 覆盖当前相对位姿
- `stable`：把“修正量”表示成 `ΔT = T_est * inv(T_cur)`，对 `Δ(x,y,yaw)` 做 EMA 平滑 + 步长 gate，再乘回去

实现：`HEAL/opencood/extrinsics/pose_correction/stage1_pgc_pose.py:57`

重要注意：
- stable 依赖 sample 顺序（内部有 per-CAV state），所以 sweep 时需要 `num_workers=0` 且尽量保证顺序不乱（跨场景跳跃会导致 state 漂移）。
- 因此 stable 并不是 oracle 上界；真正的 oracle 上界是 `v2vloc_oracle_initfree`（直接覆盖为 clean pose，不做滤波）。

### 2.2.4 inference_w_noise.py 里如何启用（用于做 noise sweep）

`inference_w_noise.py` 会先跑 PGC/Oracle solver 生成 override map，再进入协同感知评测：
- `--pose-correction v2vloc_pgc_initfree|v2vloc_pgc_stable`：读取 PGC pose json（字段 `lidar_pose_pred_np`）
- `--pose-correction v2vloc_oracle_initfree|v2vloc_oracle_stable`：直接读取 stage1 cache 里的 `lidar_pose_clean_np`

实现：`HEAL/opencood/tools/inference_w_noise.py:320`

## 2.3 PASTAT（Pose-Aware Spatio-Temporal Alignment Transformer）在本仓库的代码映射

这一节回答两个工程问题：
1) “PASTAT 在代码里到底长什么样，哪些模块对应 CE/FSA/Transformer？”  
2) “pose_confidence 是怎么从 dataset 传到 fusion 模块里的？”

### 2.3.1 入口：PointPillars backbone + PASTATFusion

PASTAT 作为一个 fusion module 接在 PointPillars backbone 后：
- `HEAL/opencood/models/point_pillar_baseline.py:49`（`fusion_method == 'pastat'`）
- 融合模块实现：`HEAL/opencood/models/fuse_modules/pastat_fusion.py:131`（`PASTATFusion`）

启用方式：在 hypes yaml 中设定 `model.fusion_method: pastat`，并配置 `model.args.pastat: ...`（例如 `HEAL/opencood/hypes_yaml/v2v4real/LiDAROnly/lidar_pastat_noise1.yaml`）。

### 2.3.2 pose_confidence 的来源与传递（论文 Eq.(6) 在 HEAL 里的落地）

数据侧：
- 噪声注入会在 `lidar_pose` 上加噪，并保存 `lidar_pose_clean`：`HEAL/opencood/utils/pose_utils.py:add_noise_data_dict`
- 如果 `params.pose_confidence` 不存在，会用 `epsilon = ||(x,y)-(x_clean,y_clean)||` 近似 pose error，并按 Eq.(6) 写入：
  - `sigma = 1/(1+epsilon^2)`  
  - 代码：`HEAL/opencood/utils/pose_utils.py:23`（`attach_pose_confidence`）
- 中融合 dataset 每个 sample 会在构造 `pairwise_t_matrix` 前调用一次：`HEAL/opencood/data_utils/datasets/intermediate_fusion_dataset.py:499`

模型侧：
- `point_pillar_baseline.py` 会把 `pose_confidence` 扩成一个常数 confidence map，并拼到 BEV 特征最后一维通道：
  - `conf_map = pose_confidence.view(-1,1,1,1).expand(-1,1,H,W)`
  - `x = cat([feat, conf_map], dim=1)`
  - 代码：`HEAL/opencood/models/point_pillar_baseline.py:131`

因此：在 “GT pose + 合成噪声” 的设定下，PASTAT 实际拿到的是 **oracle 置信度**（由噪声残差直接算），这与论文在 V2V4Real 的设定是一致的方向（论文也不训练 PGC，而是用 GT+noise，并由 pose error 得到 confidence）。

### 2.3.3 PASTATFusion 的 3 个核心步骤（CE/FSA/Transformer）

`PASTATFusion` 的 forward（`HEAL/opencood/models/fuse_modules/pastat_fusion.py:176`）做了：

1) **Pose 粗对齐（coarse alignment）**  
   - 输入 `affine_matrix` 来自 `pairwise_t_matrix` 的归一化版本（由 `point_pillar_baseline.py` 构建）。
   - 把非 ego 的特征先按 pose warp 到 ego 坐标系：`warp_affine_simple`  
   - 代码：`HEAL/opencood/models/fuse_modules/pastat_fusion.py:223`

2) **CE（Confidence Embedding） + FSA（Feature Spatial Alignment）**  
   - CE：把每个 agent 的 confidence scalar 在 batch 内归一化后，通过一个线性层投影成 `embed_dim`，再 broadcast 成 `(H,W)` 的 embedding map：
     - `ConfidenceEmbedding`：`HEAL/opencood/models/fuse_modules/pastat_fusion.py:43`
   - FSA：对每个 non-ego agent，输入 `cat([ego_feat, neigh_feat, ce_map])`，回归 `dx, dy, dtheta`，并再 warp 一次做细对齐：
     - `FSAPairwiseAligner`：`HEAL/opencood/models/fuse_modules/pastat_fusion.py:69`
     - warp：`HEAL/opencood/models/fuse_modules/pastat_fusion.py:251`

3) **Transformer 融合（复用 V2X-ViT encoder）**  
   - 这里复用的是本 repo 的 `V2XTransformer`：`HEAL/opencood/models/sub_modules/v2xvit_basic.py:200`
   - `PASTATFusion` 会构造一个 `prior`（默认全 0，形状 `(B,L,3,H,W)`），并把 feature 与 prior 拼到一起再喂给 transformer：
     - `prior` 构造：`HEAL/opencood/models/fuse_modules/pastat_fusion.py:256`
   - 注意：`V2XTransformer` 内部支持 RTE（相对时间编码）与 STTF（时延/速度补偿），但在 PASTATFusion 默认 `prior=0`、`spatial_correction_matrix=I` 时，这部分不会产生有效的 temporal 建模。因此当前实现更接近“pose-aware spatial fusion + transformer”，而不是完整的 multi-frame spatio-temporal token 设计。

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

### 8.5 “stable” 的定义与常见误解（曲线变平 ≠ 更鲁棒）

在本 repo 里，`*_stable` 不是“更无初值”，而是给 pose correction 增加一个 **时序 delta 滤波器**：

1) 从当前（可能带噪）pose 得到 `T_cur`  
2) 从配准模块得到 `T_est`  
3) 计算修正量 `ΔT = T_est · inv(T_cur)`，并转成 `Δ(x,y,yaw)`  
4) 对 `Δ(x,y,yaw)` 做 EMA 平滑 + max-step gate（防止跳变）  
5) 再把滤波后的 `ΔT` 乘回 `T_cur` 得到 `T_corrected`

实现（PGC/oracle 与 V2XReg++/FreeAlign 复用同一套路）：
- `HEAL/opencood/extrinsics/pose_correction/stage1_v2xregpp.py`（stable delta filter 参考实现）
- `HEAL/opencood/extrinsics/pose_correction/stage1_freealign.py`
- `HEAL/opencood/extrinsics/pose_correction/stage1_pgc_pose.py`

因此：
- `stable` 需要 **顺序数据**（同一进程持有 state，且 sample 顺序不能乱），sweep 时一般要 `--num-workers 0`；
- 如果 sample 顺序跨场景/跨 ego 跳跃，stable state 可能漂移，表现为 **噪声=0 也会很差**；
- 某些情况下 stable 曲线“很平”，只是因为修正量被 gate/EMA 锁死，或者融合退化到 ego-only，并不代表 pose 估计更准。  
  判断是否真鲁棒，必须同时看 YAML 里的 `rel_error_stats`。

### 8.6 comm=200 全量曲线补充：stable / oracle / “无初值(occ+ICP)” 的实际表现

以下所有曲线都固定：
- cooperative perception：`HEAL/opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25`（bestval@17）
- stage1 cache：`HEAL/opencood/logs/v2v4real_stage1_pointpillar_from_pastat_bestval17_80boxes/test/stage1_boxes.json`
- 数据：V2V4Real test=3986（multi-ego）
- paired sweep：`(pos_std,rot_std)=(0,0),(1,1),...,(4,4)`，`noise_target=non-ego`

AP@0.5（σ=0..4）：
- none：`[0.5751, 0.5722, 0.5686, 0.5627, 0.5602]`（`AP030507_none_comm200_paper.yaml`）
- v2xregpp_initfree（box matching）：`[0.5753, 0.5734, 0.5698, 0.5658, 0.5627]`（`AP030507_v2xregpp_initfree_comm200_paper.yaml`）
- freealign_paper（anchor+affine）：`[0.5529, 0.5527, 0.5522, 0.5519, 0.5516]`（`AP030507_freealign_paper_comm200_paper.yaml`）

stable 版本（注意：这里的 v2xregpp_stable/freealign_paper_stable 都走了 stable delta filter；v2xregpp_stable 的该次配置是 occ-from-lidar + force_occ_pose）：
- v2xregpp_stable：`[0.5432, 0.5417, 0.5472, 0.5457, 0.5448]`（`AP030507_v2xregpp_stable_comm200_paper.yaml`）
- freealign_paper_stable：`[0.5395, 0.5398, 0.5403, 0.5381, 0.5380]`（`AP030507_freealign_paper_stable_comm200_paper.yaml`）

V2VLoc-style oracle（用于隔离“完美定位”对同一协同感知模型的上界；不是训练得到的 PGC）：
- v2vloc_oracle_stable：`[0.5753, 0.5734, 0.5683, 0.5634, 0.5596]`（`AP030507_v2vloc_oracle_stable_comm200_paper.yaml`）
- v2vloc_oracle_initfree：**未完整跑完**（只生成了 0/1/2 三个点：`AP030507_v2vloc_oracle_initfree_comm200_paper.yaml`）；严格的 oracle 上界应以 initfree 为准（stable 会引入滤波误差）。

尝试“真正无初值（不依赖 noisy pose）”的一版：occ-from-lidar + ICP refine，并强制使用 occ pose（输出几乎与噪声无关）：
- `AP030507_v2xregpp_initfree_comm200_occpose_fromlidar_icp.yaml`
  - AP@0.5：`[0.5649, 0.5645, 0.5641, 0.5635, 0.5633]`
  - 但 `rel_error_stats` 显示噪声=0 就有很大残差（mean rel_trans≈17.7m、mean yaw≈25.6°），说明该“无初值 pose”在 V2V4Real 上大量帧估错（曲线平更多是退化/不敏感，而不是对齐更准）。

补充解释：为什么 baseline（none）在这里看起来也“很稳”？
- 该 cooperative model 训练时开启了 pose noise augmentation（`noise_setting pos_std=1/rot_std=1`），因此对 0..4m/deg 的测试噪声天然更鲁棒；
- 本 sweep 只对 non-ego 加噪，ego 自己不加噪；一旦其它车对齐变差，网络容易退化到 “ego-only 主导”，AP 不会像 “all 都加噪” 那样断崖式下降；
- 因此鲁棒性评估必须同时看 `AP` 和 `rel_error_stats`（对齐是否真的变准）。

### 8.7 noise sweep 的实现口径（写给以后复现实验的人）

噪声注入与曲线产物：
- 噪声注入：`HEAL/opencood/utils/pose_utils.py:add_noise_data_dict`
- 只噪 non-ego：`--noise-target non-ego`
- AP 输出：`HEAL/opencood/tools/inference_w_noise.py` 会把每个 σ 的 AP30/50/70 append 到 `AP030507_*.yaml`，并写入 `rel_error_stats`

口径注意点：
- 当前实现不会在每个 noise level 重置随机 seed（dataset build 时只 seed 一次），不同方法的每档噪声并非严格“同一随机噪声样本”；如果你要严格可比，建议统一 `--num-workers 0` 并在每个 noise level 处显式重置 seed。

## 9. PGC（外参/位姿求解）在 V2V4Real 上的训练尝试：结果与结论

论文明确说明：V2V4Real “single traversal per location” 会让回归式 LiDAR localization 极易过拟合，因此论文 **不在 V2V4Real 上训练 PGC**。  
这里我们仍然硬训 PGC 的目的，是验证“问题定义本身是否可行”，以及为后续改造（相对配准/地图/检索）提供证据。

### 9.1 我们训的是什么（本 repo 训练脚本口径）

- 训练脚本：`HEAL/opencood/tools/train_v2vloc_pgc.py`
- 监督：用 GT pose 把点变到 world，做每点 world 坐标回归（SCR），并回归每帧 `epsilon`（误差代理），损失见 `train_v2vloc_pgc.py:173`
- 推理：`HEAL/opencood/tools/infer_v2vloc_pgc_pose.py`（导出每帧每车的 pose JSON）
- 评测：`HEAL/opencood/tools/eval_pgc_pose_json.py`（评 ego->cav 的相对位姿 TE/RE）

### 9.2 代表性训练 run 与评测指标（val200）

（1）paper 超参风格（wd=1200），并启用 `coord_scale=1e-2` 做数值缩放：
- ckpt：`HEAL/opencood/pose/pgc_outputs/v2v4real_pgc_dedup_scale1e-2_wd1200_100e_gpu1_epoch100.pth`
- val200 指标：`HEAL/opencood/pose/pgc_outputs/v2v4real_pgc_dedup_scale1e-2_wd1200_100e_gpu1_pose_epoch100_val200_metrics.json`
  - TE mean ≈ 32.0 m，RE mean ≈ 1.68°，`success@10m = 0`

（2）小 weight_decay（wd=1e-4），同样 `coord_scale=1e-2`：
- ckpt：`HEAL/opencood/pose/pgc_outputs/v2v4real_pgc_dedup_scale1e-2_wd1e-4_100e_gpu6_epoch100.pth`
- val200 指标：`HEAL/opencood/pose/pgc_outputs/v2v4real_pgc_dedup_scale1e-2_wd1e-4_100e_gpu6_pose_epoch100_val200_metrics.json`
  - TE mean ≈ 619 m，RE mean ≈ 9.34°，`success@10m = 0`

训练监控（非必须，但用于持续监督）：
- `HEAL/opencood/tools/pgc_quick_eval_watch.py` 会自动抓最新 epoch ckpt，跑 infer+eval，并写 jsonl 日志到 `HEAL/opencood/pose/pgc_outputs/*quick_pose_eval*.jsonl`。

### 9.3 结论（当前证据）

- 在 V2V4Real 条件下，把 PGC 当作“绝对定位器”训练出来的 pose 在相对位姿口径（ego->cav）上 **完全不可用**（val200 上 `success@10m=0`）。
- `wd=1200` 的 run 出现 “RE 很小但 TE 仍 ~32m” 的典型退化现象：网络更像学到一个“压缩/偏置的平移尺度”，而不是学到可泛化的全局定位。
- 这与论文对 V2V4Real 的判断一致：在 single-traversal（缺少同地多趟）条件下，单帧绝对定位更像记忆问题，泛化很差。

如果你的研究目标是“抛掉 multi-traversal 假设”，更可能的路线是：
- 把外参求解改成 **相对配准/短时序配准**（不回归 world pose，而是回归 ego->cav 的相对 SE(2)/SE(3)）；或
- 引入 **地图/检索/记忆**（从已见帧中检索相似场景，辅助 SCR/pose）；或
- 把 pose correction 目标直接绑定到协同检测 loss（端到端对齐），而不是单独训练绝对定位器。
