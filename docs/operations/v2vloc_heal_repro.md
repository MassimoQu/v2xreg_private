# V2VLoc (AAAI'26) 在 HEAL(OpenCOOD) 复现笔记（DAIR-V2X）

这份笔记对应 `docs/v2vloc.pdf` 的两大组件：
- **PGC**：Pose Generator with Confidence（生成 pose + confidence）
- **PASTAT**：Pose-Aware Spatio-Temporal Alignment Transformer（CE+FSA+Transformer 融合）

本仓库的实现入口在 `HEAL/opencood/` 下。

## 0. 环境

本机使用 micromamba 环境 `heal`：

```bash
cd /home/qqxluca/v2xreg_private/HEAL
MAMBA_ROOT_PREFIX=$HOME/.micromamba ~/.local/micromamba/bin/micromamba run -n heal python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

## 1. 关于 DAIR/OPV2V 的 PGC 训练

论文在 V2V4Real 上明确说明：由于**每个地点只有单次 traversal**，不训练 PGC（否则会过拟合场景几何），而是用 **GT pose + 1.0/1.0 噪声**，并由 pose error 得到 confidence。

DAIR/OPV2V与 V2V4Real 更接近，因此这里推荐：
- **训练/评测 PASTAT：使用 GT pose + 合成噪声**（见下文 `noise_setting` 与 `inference_w_noise.py`）。
- 若你后续拿到多 traversal 的定位数据（或自建），再用 `HEAL/opencood/tools/train_v2vloc_pgc.py` 训练 PGC。

## 2. 训练 PASTAT（DAIR）

### 2.1 全量训练（论文式：带 pose 噪声）

配置：`HEAL/opencood/hypes_yaml/dairv2x/LiDAROnly/lidar_pastat_noise1.yaml`

```bash
cd /home/qqxluca/v2xreg_private/HEAL
CUDA_VISIBLE_DEVICES=9 \
MAMBA_ROOT_PREFIX=$HOME/.micromamba ~/.local/micromamba/bin/micromamba run -n heal \
python opencood/tools/train.py \
  -y opencood/hypes_yaml/dairv2x/LiDAROnly/lidar_pastat_noise1.yaml \
  --fusion_method intermediate
```

### 2.2 子集快速跑通（debug）

配置：`HEAL/opencood/hypes_yaml/dairv2x/LiDAROnly/lidar_pastat_subset_noise1.yaml`（train_400 / val_200）

```bash
cd /home/qqxluca/v2xreg_private/HEAL
CUDA_VISIBLE_DEVICES=9 \
MAMBA_ROOT_PREFIX=$HOME/.micromamba ~/.local/micromamba/bin/micromamba run -n heal \
python opencood/tools/train.py \
  -y opencood/hypes_yaml/dairv2x/LiDAROnly/lidar_pastat_subset_noise1.yaml \
  --fusion_method intermediate
```

### 2.3 用已有模型初始化（更快收敛）

`train.py` 新增了 `--init_model_dir`：加载权重但不继承 epoch/优化器（用于 fine-tune）。

```bash
cd /home/qqxluca/v2xreg_private/HEAL
CUDA_VISIBLE_DEVICES=9 \
MAMBA_ROOT_PREFIX=$HOME/.micromamba ~/.local/micromamba/bin/micromamba run -n heal \
python opencood/tools/train.py \
  -y opencood/hypes_yaml/dairv2x/LiDAROnly/lidar_pastat_noise1.yaml \
  --init_model_dir opencood/logs/HeterBaseline_DAIR_lidar_fcooper_2023_09_09_19_23_43 \
  --fusion_method intermediate
```

### 2.4 debug 用的加速参数

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

## 3. 噪声鲁棒性评测（对应论文 Table 4）

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

### 3.1 自动等待训练结束并跑完整 sweep（推荐）

训练结束后再跑 sweep，避免抢 GPU。脚本会同时跑 `noise-target=all` 和 `noise-target=non-ego` 两条曲线（各占 1 张卡）：

```bash
cd /home/qqxluca/v2xreg_private/HEAL
MODEL_DIR=opencood/logs/<YOUR_TRAINED_MODEL_DIR>
nohup bash opencood/tools/watch_train_and_sweep.sh "$MODEL_DIR" > "$MODEL_DIR/watch_and_sweep.log" 2>&1 &
tail -f "$MODEL_DIR/watch_and_sweep.log"
```

## 4. （可选）PGC pose 注入到 PASTAT

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
