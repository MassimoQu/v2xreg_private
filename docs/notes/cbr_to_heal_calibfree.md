# CBR → HEAL：把“无需外参/标定”的思路迁移到协同感知融合里（工作记录）

## 1. CBR 在做什么（和我们关心的点）

CBR（Calibration-free BEV Representation, arXiv:2303.03583）面向 **基础设施侧相机**：

- 不使用相机内外参做显式几何投影；
- 通过 **DecoupleViewProjection**（两个 MLP，把 PV 特征映射为 FV/BEV 两个“解耦视图”特征）+ 由 3D 框诱导的前景监督（FV/BEV seg）让网络学到“视图变换”；
- 再用 **CrossViewEnhancement** 做基于相似度的跨视图增强：对 FV/BEV 特征做 query/key/value 轻量匹配，把 FV 信息注入 BEV。

对 HEAL/协同感知的可迁移抽象：

- CBR 的核心不是“某种固定 RoPE”，而是 **不依赖标定（外参）也能通过相似度/监督学到对齐与融合**。
- 对应到多车协同：如果不输入 pairwise pose（外参），就必须在网络里 **隐式或显式估计对齐**（SE(2)/SE(3)）或做 **内容驱动的匹配融合**。

## 2. HEAL 里外参目前怎么用（为什么 3D PE 容易不收益）

以 V2X-ViT/中间融合为例：

- 主干先得到每个 agent 的 BEV feature map；
- 融合前通常用 `pairwise_t_matrix` 把邻车 feature warp 到 ego BEV（在 BEV 平面里等价于 2D SE(2)）；
- Transformer/Attention 里的“pose PE”即使做成 3D，本质也常只在 BEV 平面生效（高度维度被池化/离散化得很弱），所以盲目把 2D PE 换成 3D RoPE/ProPE 很容易出现：
  - 任务所需几何自由度仍是 SE(2)，3D 注入反而引入“无用/噪声”维度；
  - 特征本身是 BEV 2D token，3D PE 的 inductive bias 不匹配。

## 3. 我们在 HEAL 里先做的“几何注入/无外参输入”原型（路线 A）

目标：在不输入 `pairwise_t_matrix` 的情况下，让融合模块自己估计 ego->cav 的 SE(2) 并完成 warp，再走原 V2X-ViT Transformer。

实现点：

- 新增：`HEAL/opencood/models/fuse_modules/calibfree_align.py`
  - 用 **phase correlation（相位相关）** 在下采样 BEV 特征上估计平移；
  - 可选 yaw grid-search（离散角度）估计旋转；
  - 输出兼容 `warp_affine_simple` 的 (2,3) affine（normalized coords）。
- 修改：`HEAL/opencood/models/fuse_modules/fusion_in_one.py` 的 `V2XViTFusion`
  - `v2xvit.calibfree.enabled: true` 时：
    - 忽略 `affine_matrix/pairwise_t_matrix`；
    - 对每个邻车估计 ego->cav warp 并 warp 特征；
    - 同时将 `pairwise_t_matrix=None`（避免 transformer pose PE 变相使用外参）。
- 允许“真的不提供外参也能跑”：
  - `HEAL/opencood/models/point_pillar_baseline.py`、`HEAL/opencood/models/heter_model_baseline.py`：
    - 当 `data_dict` 不含 `pairwise_t_matrix` 时自动回退为 identity（使 calibfree 运行不依赖外参字段）。

配置样例：

- `HEAL/opencood/hypes_yaml/opv2v/LiDAROnly/lidar_v2xvit_calibfree.yaml`
  - 开启 `v2xvit.calibfree`，默认 `downsample=8`、`yaw_search max=45 step=5`。

注意：这条路线本质是“内容驱动对齐”，和 CBR 的 CrossViewEnhancement 抽象一致，但这里用的是频域相位相关（更像几何匹配/相关性）。

## 4. 第二条更“CBR/几何”的路线（路线 B，建议做对比）

HEAL 本仓库其实已经有对象级几何注入/外参估计：

- `HEAL/opencood/pose/freealign_repo.py`、`HEAL/opencood/pose/freealign_paper.py`
- `HEAL/opencood/extrinsics/pose_correction/stage1_v2xregpp.py`（包含 occ-hint phase corr）

它们的特点：

- 不是在 feature map 上直接“猜 pose”，而是用 box/占据栅格等几何中间量估计 SE(2)；
- 对外参噪声往往更稳，但需要额外的 stage1（检测/占据图）作为输入。

如果你的目标是“协同感知不需要外参输入”，路线 B 往往更容易先做出可用 baseline（尤其在 overlap 小/纹理重复的场景）。

## 5. 预期现象与风险（为什么可能会掉点）

即使实现正确，AP 下降也很常见，主要原因：

- 无外参时对齐任务变成“无监督配准”，在 overlap 小、动态物体多、道路重复纹理时很容易多峰/错峰；
- 相位相关假设较强（整体平移/旋转），对遮挡/局部对齐不友好；
- 若 backbone/feature 不是为“可配准性”训练的（例如原来依赖 GT pose warp），相关性峰会变钝，导致对齐误差放大；
- yaw 搜索离散化会引入量化误差；downsample 越大误差越大。

## 6. 下一步建议（按优先级）

1) 先在 OPV2V 做“只测对齐误差”的快速实验：用 GT `pairwise_t_matrix` 计算真值 SE(2)，对比 calibfree 估计的 RTE/RRE（不跑检测头也行）。
2) 再在固定 checkpoint 上做 ablation：GT pose warp vs calibfree warp（仅推理）看 AP 掉多少；如果掉很多，考虑小规模 finetune 让特征更“可配准”。
3) 把路线 B（FreeAlign/V2XReg++/occ-hint）接到同一接口里，形成强基线对比。

