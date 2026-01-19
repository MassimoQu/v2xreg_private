# HEAL 外参求解/特征对齐/外参噪声鲁棒性：实现与分析记录

**Owner:** qqxluca + Codex  
**Last updated:** 2026-01-16  

> 目的：把“用特征/用检测框做配准得到外参，再用于特征级协同感知”这条链路的实现细节与关键差异记录下来，
> 并解释外参在特征空间如何生效、以及为何“raw 上变换”和“特征上 warp”通常不严格等价（等变性视角）。

相关补充文档（更聚焦 occ-hint pipeline 本身）：`docs/operations/v2xregpp_midfusion_occ_hint.md`

---

## 1. 术语澄清：两条“中/后融合”轴不要混

HEAL/OpenCOOD 里经常同时讨论两件事：

1) **协同感知的融合范式（感知侧）**
   - *中融合*（feature-level fusion）：各车先提 BEV 特征，再对齐并融合，再检测/分割等。
   - *后融合*（box-level fusion）：各车先出检测框，再把框变换到统一坐标系后融合。
   - 对应推理入口：`HEAL/opencood/tools/inference_w_noise.py:397`（`--fusion_method intermediate|late`）。

2) **外参求解/配准用的信息源（配准侧）**
   - *特征配准*：用密集 BEV “图”（occupancy/feature）先估一个相对位姿 seed/hint（再用于匹配或直接作为候选）。
   - *检测框配准*：只用检测框/几何匹配求外参（V2X-Reg++ 传统“后融合配准范式”）。
   - 对应实现：V2X-Reg++ pose corrector 插在 dataset 内部（在 `pairwise_t_matrix` 计算前），见
     `HEAL/opencood/data_utils/datasets/intermediate_fusion_dataset.py:401`。

本文讨论的核心是：**配准侧**（特征 vs 框）得到的外参如何影响 **感知侧**（特征融合为主）的最终性能与鲁棒性。

---

## 2. 外参噪声扫参曲线：脚本、设置、产物

### 2.1 噪声是怎么注入的

- 注入位置：`HEAL/opencood/utils/pose_utils.py:44` 的 `add_noise_data_dict`。
- 注入对象：默认只对 `lidar_pose` 的 `(x, y, yaw)` 加噪（单位 m / deg），同时保存 `lidar_pose_clean`。
- 关键开关：`--noise-target non-ego`
  - CLI 参数：`HEAL/opencood/tools/inference_w_noise.py:85`
  - 选择逻辑：`HEAL/opencood/utils/pose_utils.py:50`
  - 用途：避免“ego 与 cav 同时加噪导致相对误差叠加/双倍”的歧义。

### 2.2 跑分与画图脚本

- 跑分：`HEAL/opencood/tools/inference_w_noise.py:55`
  - 读取 `--model_dir/config.yaml`（`HEAL/opencood/hypes_yaml/yaml_utils.py:14`）
  - 对每个噪声档位评测 AP30/50/70，并将结果 append 到一个 `AP030507_*.yaml`。
  - 同时记录“相对位姿误差统计”（用 `lidar_pose` vs `lidar_pose_clean` 计算），见
    `HEAL/opencood/tools/inference_w_noise.py:397`。
- 画图：`HEAL/opencood/tools/plot_noise_sweep.py:158`
  - 读多个 `AP030507_*.yaml`，对同一张图叠加多条曲线（按 x 排序、默认 `xlim=0,10`）。

### 2.2.1 本次曲线的关键“实现设置”（你问的细节）

1) **噪声档位**
   - 平移 sweep：`--pos-std-list 0,1,2,...,10` 且 `--rot-std-list 0`（paired 会把 rot 扩成同长度的全 0）
   - 旋转 sweep：`--pos-std-list 0` 且 `--rot-std-list 0,1,2,...,10`

2) **噪声施加对象**
   - 使用 `--noise-target non-ego`，只噪声化非 ego，避免“相对误差双倍”（第 2.1 节）。

3) **评测样本数**
   - 若文件名里带 `n50/n200`，通常对应 `--max-eval-samples 50/200` 的快速 sweep（不是全量 test）。  
   - 你可以通过 YAML 里的 `rel_success_at_m` 分母反推“有效 pair 数”（例如 0.8510638297≈40/47）。

4) **随机性**
   - `inference_w_noise.py` 里 `np.random.seed(303)` 只在 dataset build 时设置一次（`inference_w_noise.py:283`），
     且每个噪声档位不会重置 seed，因此不同档位的噪声采样不是“同一随机序列缩放”，而是连续消耗 RNG 的结果。
     若要严格可比，可改为每个 noise level 都 `np.random.seed(fixed_seed)`（需要后续 patch）。

5) **v2xregpp 的关键开关**
   - `--pose-correction v2xregpp_initfree|v2xregpp_stable`：对应 dataset 内 pose corrector 的 `mode`（见第 3 节）。
   - `--v2xregpp-occ-from-lidar`：从 raw lidar 生成 occupancy（绕开超大的 `stage1_boxes.json` occ 字段）。
   - `--v2xregpp-use-occ-hint / --v2xregpp-use-occ-pose / --v2xregpp-force-occ-pose`：控制 occ 的“hint/候选/强制”角色（第 3.2 节）。
   - 新增：`--v2xregpp-min-precision`：绝对精度阈值（对应 `Stage1V2XRegPPPoseCorrector.min_precision`），用于减少“0 噪声时被错误 override”的情况。

### 2.3 本次 0–10m / 0–10deg 曲线的具体文件

日志目录（示例）：  
`HEAL/opencood/logs/HeterBaseline_DAIR_lidar_fcooper_2023_09_09_19_23_43`

生成的图（PNG）：
- `HEAL/opencood/logs/HeterBaseline_DAIR_lidar_fcooper_2023_09_09_19_23_43/noise_sweep_intermediate_trans_ap50.png:1`
- `HEAL/opencood/logs/HeterBaseline_DAIR_lidar_fcooper_2023_09_09_19_23_43/noise_sweep_intermediate_rot_ap50.png:1`
- `HEAL/opencood/logs/HeterBaseline_DAIR_lidar_fcooper_2023_09_09_19_23_43/noise_sweep_late_trans_ap50.png:1`
- `HEAL/opencood/logs/HeterBaseline_DAIR_lidar_fcooper_2023_09_09_19_23_43/noise_sweep_late_rot_ap50.png:1`

对应的 YAML（同目录下）：
- baseline（无修正）：`AP030507_none_*_ntnon_v2.yaml`
- box-only v2xregpp（不启用 occ）：`AP030507_v2xregpp_initfree_*_ntnon_v2.yaml`
- occ-from-lidar v2xregpp（启用特征配准）：`AP030507_v2xregpp_initfree_ntnon_*_occ_lidar.yaml`

> 注意：`AP030507_v2xregpp_stable_ntnon_late_rot010_n50_occ_lidar.yaml` 的 `ap50` 只有 8 个点（0–7°），
> `rot_std_list` 却有 11 个点（0–10°），因此对应绿线会“断在 7°”。属于产物不完整，需要补跑。

### 2.4 “特征配准 vs 框配准”对鲁棒性的对比（AP50 下降幅度）

以 AP50 从噪声=0 到噪声=10 的下降幅度（越接近 0 越抗噪）为例：

- 协同感知=中融合（intermediate），噪声=平移 0–10m：
  - none：Δ≈-0.143
  - box-only v2xregpp：Δ≈-0.160
  - feat(occ_from_lidar) v2xregpp：Δ≈-0.040
- 协同感知=中融合（intermediate），噪声=旋转 0–10°：
  - none：Δ≈-0.129
  - box-only v2xregpp：Δ≈-0.118
  - feat(occ_from_lidar) v2xregpp：Δ≈-0.060
- 协同感知=后融合（late），噪声=平移 0–10m：
  - none：Δ≈-0.133
  - box-only v2xregpp：Δ≈-0.155
  - feat(occ_from_lidar) v2xregpp：Δ≈-0.056
- 协同感知=后融合（late），噪声=旋转 0–10°：
  - none：Δ≈-0.121
  - box-only v2xregpp：Δ≈-0.074
  - feat(occ_from_lidar) v2xregpp：Δ≈-0.048

结论（就现有 sweep 而言）：
- **用 occ 的“特征配准”明显更抗外参噪声**；纯框配准对曲线压平贡献有限。
- 但 “曲线更平” 不等于 “位姿对得更准”，需要同时看 YAML 里的 `rel_error_stats`（见下节的 stable 退化风险）。

---

## 3. V2X-Reg++ Pose Corrector：集成点、候选源、initfree vs stable

### 3.1 集成点：为什么它能影响协同感知

V2X-Reg++ pose correction 是在 dataset 内改写 `lidar_pose`，从而影响后续 `pairwise_t_matrix`：

- 调用点（中融合 dataset）：`HEAL/opencood/data_utils/datasets/intermediate_fusion_dataset.py:401`
- 生成 `pairwise_t_matrix`：`HEAL/opencood/utils/transformation_utils.py:21`

因此它影响的是“特征对齐矩阵”，而不是直接改网络。

### 3.2 候选源：框匹配、occ-hint、occ-pose、ICP refine

实现：`HEAL/opencood/extrinsics/pose_correction/stage1_v2xregpp.py`

关键能力：

1) **框匹配求解（传统路线）**
   - 匹配引擎：`calib/matching/engine.py:13`（`MatchingEngine.compute`）
   - 求解：`Matches2Extrinsics`（在 `stage1_v2xregpp.py` 内调用）

2) **occ-hint（特征 seed / prior）**
   - 从 stage1 cache 读 occ map，或从 raw lidar 生成：`stage1_v2xregpp.py:228`、`stage1_v2xregpp.py:1116`
   - occ-hint 的实现：`stage1_v2xregpp.py:277`（见第 4 节 FFT 解释）

3) **use_occ_pose（把 occ-hint 当作“第一类位姿候选”）**
   - boxes 为空时仍可 occ-only 更新：`stage1_v2xregpp.py:721`
   - boxes 存在但 matcher 没候选时的 occ fallback：`stage1_v2xregpp.py:986`

4) **force_occ_pose（强制只用 occ）**
   - 入口：`stage1_v2xregpp.py:803`
   - 用途：让输出尽可能独立于当前 noisy pose/boxes（但要非常小心 occ 歧义）。

5) **ICP refine（可选）**
   - 入口：`stage1_v2xregpp.py:1147`

### 3.3 initfree vs stable：差别不是“用不用初值”，而是“是否带时序状态”

两者都可能参考 `T_current` 做 gating，但核心区别是：**stable 会跨帧平滑修正量**。

- initfree：逐帧独立，直接把估计的 `rel_T_est` 写回（`stage1_v2xregpp.py:1194`）。
- stable：逐帧算修正 `ΔT = rel_T_est @ inv(rel_current_T)`，对 `Δ(x,y,yaw)` 做
  - **步长限制**（max_step）：`stage1_v2xregpp.py:1182`
  - **EMA 平滑**：`stage1_v2xregpp.py:1185`
  - 再用 `rel_T_corrected = ΔT_smooth @ rel_current_T`（`stage1_v2xregpp.py:1191`）。

EMA 的实现（对 `(dx,dy,yaw)`）：`stage1_v2xregpp.py:643`。

> stable 的前提：样本顺序要保持、并且同一进程持有 state，所以 DataLoader workers 默认=0，
> 见 `HEAL/opencood/tools/inference_w_noise.py:303`。

补充（你提到的 `v2xregpp_init_pose`）：
- 当前 `inference_w_noise.py` 里没有 `init_pose` 这个选项，只有 `initfree|stable`（`inference_w_noise.py:94`）。
- 但“init_pose/有初值”这个概念在 V2X-Reg++ 的 late-fusion estimator 里存在：`HEAL/opencood/extrinsics/late_fusion/v2xregpp.py:10`，
  也就是 **把当前 pose 当作 prior（T_hint/init）去 gate 匹配**。这种做法会让输出随 pose noise 改变，本质上不是“真正无初值”。

### 3.3.1 EMA 平滑/步长限制到底在干什么（你问的“指数平滑”）

EMA（指数滑动平均）的标量形式是：

`y_t = (1-α) * y_{t-1} + α * x_t`，其中 `α∈(0,1]`。

- `α` 越小：越“稳”（历史权重更大）；`α` 越大：越“跟手”（更信任当前估计）。
- “指数”来自展开式：`y_t = α x_t + α(1-α) x_{t-1} + α(1-α)^2 x_{t-2} + ...`，旧样本权重按 `(1-α)^k` 指数衰减。

在 `stage1_v2xregpp.py:643` 里，EMA 是对 `Δ(x,y,yaw)` 做的，其中 yaw 需要处理角度 wrap（`_delta_angle_deg`）。

步长限制（`stage1_v2xregpp.py:663`）则是一个“异常值保护”：如果本帧估计的 `Δ` 相比上帧 `Δ` 跳变太大（超过 `max_step_xy_m / max_step_yaw_deg`），就认为可能是 outlier，直接沿用上一帧 `Δ`。

### 3.3.2 我们对 initfree 做的关键修正（让它更像“真正无初值”）

在 `HEAL/opencood/extrinsics/pose_correction/stage1_v2xregpp.py`：
- **initfree 不再把 `T_current` 传入 `_estimate_rel_T`**，避免“apply 决策依赖当前 noisy pose”导致曲线随噪声起伏。
- 新增 `min_precision`（对应 `--v2xregpp-min-precision`）作为绝对质量门控，减少“0 噪声时被低质量估计覆盖”的情况。

### 3.4 重要风险：stable 曲线“平”可能是退化（不是鲁棒）

历史 sweep 中出现过“stable 曲线几乎完全平”，但 `rel_error_stats` 在噪声=0 时就巨大：
- 例如 `AP030507_v2xregpp_stable_ntnon_trans010_n50_occ_lidar.yaml`：噪声=0 时 `rel_trans_median≈51m` / `rel_yaw_median≈89°`。

这种“平”往往意味着对齐已经崩了，协同感知退化成近似单车/错位融合，“平坦”不具备意义。

因此建议在所有 sweep 里同时看：
- AP 曲线（感知端）
- `rel_error_stats`（位姿端，`inference_w_noise.py:485` 写入）

---

## 4. “FFT 找平移峰值 + 旋转枚举找 yaw”：occ-hint 的具体含义

occ-hint 的输入是两张 2D BEV “图”（本实现默认是 occupancy map）：
- `occ_src`：cav
- `occ_dst`：ego

### 4.1 平移：phase correlation（FFT 相位相关）

实现核心在 `stage1_v2xregpp.py:314`～`stage1_v2xregpp.py:325`：

1) 对目标图 `occ_dst` 做 FFT：`Fb = fft2(occ_dst)`
2) 对源图 `occ_src` 做 FFT：`Fa = fft2(occ_src)`
3) 构造互功率谱并归一化（只保留相位）：
   - `R = Fa * conj(Fb)`
   - `R /= |R| + eps`
4) 逆 FFT 得到相关图：`corr = ifft2(R)`（`stage1_v2xregpp.py:322`）
5) `corr` 的最大值位置就是平移峰值（`stage1_v2xregpp.py:324`）

直觉：纯平移对应频域“线性相位”，相位相关能把线性相位还原成一个尖峰。

### 4.2 旋转：暴力枚举角度 + 取最大峰值

实现核心在 `stage1_v2xregpp.py:372`～`stage1_v2xregpp.py:412`：

- 枚举角度 `angle ∈ [-rotation_max_deg, +rotation_max_deg]`，步长 `rotation_step_deg`
- 对每个 angle 旋转 `occ_src`（`scipy.ndimage.rotate`），再跑一次 phase correlation，取峰值 `peak(angle)`
- 选 `peak` 最大的角度作为 yaw
- 对 top-N 再做一次 refine（更小步长）

并用峰值比做歧义过滤（best/second-best）：`stage1_v2xregpp.py:418`～`stage1_v2xregpp.py:421`。

### 4.3 从像素位移到米：依赖 bev_range 与分辨率

转换在 `stage1_v2xregpp.py:425`～`stage1_v2xregpp.py:436`：
- `resolution_x = extent_x / W`
- `resolution_y = extent_y / H`
- `tx = -shift_col * resolution_x`
- `ty = -shift_row * resolution_y`

注意：如果 `resolution_x != resolution_y`（像素在物理空间是“长方形”），那么在像素网格上做 `rotate()` 枚举 yaw
对应的是“带拉伸的旋转”，会破坏 yaw 估计的物理意义。对 DAIR 的默认 `bev_range`（x=204.8m, y=102.4m），
若直接用 `grid_hw=256x256` 则 `resolution_x=0.8m/px`、`resolution_y=0.4m/px`。

本 repo 已在 `stage1_v2xregpp.py:1124` 增加 `occ_preserve_aspect`：当 `occ_grid_hw` 给的是正方形时，会自动把 `W`
调整到 `W/H = extent_x/extent_y`（DAIR 上等价于 `256x512`），从而保持“方形像素”。

---

## 5. 协同感知中：外参如何对齐特征？为什么“外参维度 != 特征维度”不是问题

### 5.1 外参在网络里是如何使用的

在 HEAL 的典型 BEV feature fusion 中，外参最终被用成一个 2x3 的仿射矩阵去做 `grid_sample`：

- 生成 pairwise 4x4：`HEAL/opencood/utils/transformation_utils.py:21`
- 归一化到 `affine_matrix (B,L,L,2,3)`：`HEAL/opencood/utils/transformation_utils.py:68`
- warp：`HEAL/opencood/models/sub_modules/torch_transformation_utils.py:323`

本质上外参只影响“采样坐标”（H/W 维度），并不需要与通道维 C 对齐。

可以把 BEV 特征看成函数 `F: R^2 -> R^C`，外参 `g` 的作用是：

`(g·F)(p) = F(g^{-1} p)`

即：用几何变换把“在哪取特征”这件事对齐，采到的仍是 C 维向量。

### 5.2 “把外参编码成高维特征再融合”什么时候才需要？

当你的融合算子想显式使用 pose 信息（例如做 attention bias、置信度、或显式残差对齐）时，才会出现“把 pose 变成可学习输入”的操作。

HEAL 里一个典型例子是 PASTAT：
- 先做 pose coarse warp：`HEAL/opencood/models/fuse_modules/pastat_fusion.py:219`
- 再用特征 + 置信度 embedding 学一个残差 `dx,dy,dtheta` 并二次 warp：`pastat_fusion.py:228`
- 置信度 embedding 是把标量映射成 `Ce` 通道再拼到特征上：`pastat_fusion.py:50`

---

## 6. 等变性视角：raw 上变换 vs 特征上 warp 为何通常不严格等价

### 6.1 两条路线在代码里同时存在（可直接对照）

在 `intermediate_fusion_dataset.py` 中：

- **raw 路线（proj_first=True）**：先把点云投到 ego，再做 voxel/pillar：
  - 计算 `T_ego_cav`：`HEAL/opencood/data_utils/datasets/intermediate_fusion_dataset.py:147`
  - 投影点云到 ego：`HEAL/opencood/data_utils/datasets/intermediate_fusion_dataset.py:164`
  - 若 `proj_first` 则直接替换点云：`HEAL/opencood/data_utils/datasets/intermediate_fusion_dataset.py:167`
- **feature 路线（proj_first=False）**：不投影点云，后续在网络里用 `pairwise_t_matrix` warp 特征。

并且 `get_pairwise_transformation` 里对 `proj_first=True` 直接返回 identity：
`HEAL/opencood/utils/transformation_utils.py:42`

这两条路就是你关心的对照组。

### 6.2 等价条件：需要整体算子对外参变换“等变”

用算子写：
- `x`：raw（点云/图像）
- `g`：外参变换
- `D`：离散化/voxelization/栅格化（把连续 raw 变为离散网格）
- `f`：backbone（CNN/Transformer）
- `W_g`：对特征图做空间 warp（`grid_sample`）

两条路线分别是：

- raw 先对齐：`f(D(g·x))`
- 特征后 warp：`W_g(f(D(x)))`

想要“严格等价”，需要：

`f(D(g·x)) = W_g(f(D(x)))`

这要求 `f∘D` 对 `g` 等变（可交换），但在实际中通常不成立。

### 6.3 为什么通常不成立（结合 HEAL 的具体实现）

1) **D 不等变：hard voxel/pillar vs bilinear warp**
   - raw 路线的 D 是“硬分桶+聚合”；feature 路线的 W 是 `grid_sample` 的插值采样。
   - 一个亚像素平移：raw 路线可能导致点跨格跳变；feature 路线会在相邻格做插值扩散。

2) **f 不旋转等变**
   - 卷积对平移近似等变，但对旋转通常不等变；因此 `R` 角度变化时两条路线差别更大。

3) **3D→2D 压缩导致不可交换**
   - 点云到 BEV 的过程中有高度聚合/稀疏性处理；先做 3D 变换再聚合 vs 先聚合再 2D warp，本就可能不同。

4) **尺度与下采样带来的近似**
   - feature warp 使用 `discrete_ratio * downsample_rate` 做单位换算（`normalize_pairwise_tfm`），本质是离散近似。

### 6.4 什么时候“近似等价”会更好？

- 平移为主、幅度小
- BEV 分辨率高、下采样率小
- D 有平滑（比如 occupancy 的 `gaussian_filter`：`stage1_v2xregpp.py:268`）
- 网络主要依赖平移等变的卷积结构

### 6.5 与“外参噪声鲁棒性”的关系

协同感知里普遍做的是 feature warp + fuse（见第 7 节），因此外参噪声会直接变成“特征错位采样”的误差源。

缓解的两类思路：
- **把外参估得更准/更稳**（本文主线：v2xregpp + occ）
- **让融合对错位更不敏感**（如 PASTAT 的 residual alignment，或通信/attention 的 mask/gating）

---

## 7. HEAL 中的协同感知“方法”按统一框架拆解

### 7.1 数据层（fusion.core_method）

见 `HEAL/opencood/data_utils/datasets/__init__.py:1`：
- `early`：更偏 raw 级早对齐
- `intermediate`：BEV 特征对齐后融合（最常见）
- `intermediate2stage`：两阶段变体
- `late`：框级后融合
- `intermediateheter` / `lateheter` / `intermediateheterinfer`：异构/推理特化版本

### 7.2 特征对齐（共通）

所有 feature-level 方法几乎都依赖同一条对齐链：
- `pairwise_t_matrix(4x4)`：`HEAL/opencood/utils/transformation_utils.py:21`
- `affine_matrix(2x3)`：`HEAL/opencood/utils/transformation_utils.py:68`
- `warp_affine_simple`：`HEAL/opencood/models/sub_modules/torch_transformation_utils.py:323`

### 7.3 融合算子（fuse_modules）

下面按“对齐后怎么融合”列举（并给出代码入口）：

1) **MaxFusion / AttFusion / DiscoFusion / V2VNetFusion / V2XViTFusion**
   - 入口：`HEAL/opencood/models/fuse_modules/fusion_in_one.py:87`
   - 共性：都是先把邻车特征 warp 到 ego，再做 max/attention/像素权重/ConvGRU/ViT 融合。

2) **TransformerFuse**
   - 入口：`HEAL/opencood/models/fuse_modules/transformer_fuse.py:120`
   - 特点：基于对齐后特征做 transformer 交互，并显式构造 ROI mask（`transformer_fuse.py:155`）。

3) **SelfAttn**
   - 入口：`HEAL/opencood/models/fuse_modules/self_attn.py:48`
   - 特点：对齐后把每个像素位置当 token 做 self-attn（`self_attn.py:65`）。

4) **When2com**
   - 入口：`HEAL/opencood/models/fuse_modules/when2com_fuse.py:16`
   - 特点：先对齐，再用学习到的 policy/attention 决定“要不要通信/融合谁”（`when2com_fuse.py:122`）。

5) **Where2comm (attn)**
   - 入口：`HEAL/opencood/models/fuse_modules/where2comm_attn.py:174`
   - 特点：学习空间 ROI/通信 mask，再在 mask 下做融合（文件内部多处 `warp_affine_simple`）。

6) **PyramidFusion（多尺度）**
   - 入口：`HEAL/opencood/models/fuse_modules/pyramid_fuse.py:65`
   - 特点：多尺度特征分别对齐与加权融合，权重来自每尺度的 occ_map/single_head（`pyramid_fuse.py:91`、`pyramid_fuse.py:164`）。

7) **SwapFusion (window/grid attention)**
   - 入口：`HEAL/opencood/models/fuse_modules/swap_fusion_modules.py:10`
   - 特点：窗口注意力/网格注意力在 agent×空间维度上重排 token；通常假设特征已在同一坐标系内。

8) **PASTATFusion（pose-aware 残差对齐 + transformer 融合）**
   - 入口：`HEAL/opencood/models/fuse_modules/pastat_fusion.py:131`
   - 特点：外参只做 coarse warp，然后学习 residual SE(2) 修正（`pastat_fusion.py:228`），更贴合“对外参噪声不敏感”的目标。

### 7.4 模型封装（models/）

模型由 `model.core_method` 决定（创建逻辑：`HEAL/opencood/tools/train_utils.py:196`）。

在当前 repo 的 `HEAL/opencood/hypes_yaml` 中常见的 `model.core_method` 有：
- `point_pillar`：单车
- `point_pillar_baseline`：中融合 wrapper（支持多种 `fusion_method`，见 `HEAL/opencood/models/point_pillar_baseline.py:36`）
- `point_pillar_disconet`：固定 DiscoFusion（`HEAL/opencood/models/point_pillar_disconet.py:17`）
- `heter_*`：异构多模态协同（车/路侧、相机/激光等）

仓库 `HEAL/opencood/models/` 目录里还有 CenterPoint/SECOND/VoxelNet/LSS/PIXOR/FPVRCNN/CIASSD 等实现；
如果后续要“把所有方法都拆一遍”，建议以 `model.core_method` + `fusion_method`（或对应 fuse_module）为索引做清单化整理。

---

## 8. 实战建议：对“真正无初值、检测结果不受外参噪声影响”的启发

1) **评测必须同时看 AP 曲线 + rel pose stats**
   - 只看 AP 曲线可能会把“退化成单车/错位融合”的假平坦当成成功。

2) **优先推进 occ/特征配准 + gating**
   - 在 0–10m/0–10° sweep 中，`occ_from_lidar` 明显能压平曲线（第 2.4 节）。
   - 若只关心 0–10°，可以考虑把 occ yaw 搜索范围收紧到 10° 降低歧义（配置在 `configs/pipeline_midfusion_detection_occ.yaml:43`）。

3) **把“外参噪声鲁棒”分两层做**
   - 位姿层：更鲁棒/更不依赖 noisy pose 的外参估计（v2xregpp + occ + stable delta smooth）
   - 融合层：对错位更鲁棒的融合（如 PASTAT 的 residual alignment）

4) **raw 对齐 vs feature 对齐：用 proj_first 做 A/B 对照**
   - 能快速定位鲁棒性瓶颈主要来自 D（离散化）、f（backbone 非等变）、还是 W（warp 插值/边界）。

---

## 9. 中融合配准（DAIR /data2）当前进度与主要问题

**进度（已具备）**
- HEAL 侧：`inference_w_noise.py` 已支持 `v2xregpp_initfree/stable`，并能对 `intermediate|late` 画 0–10m/0–10° 曲线（第 2 节）。
- 配准侧：Stage1V2XRegPPPoseCorrector 已支持 box matching + occ-hint（FFT seed）+ occ_pose 候选 + ICP refine（第 3.2 节）。
- 关键口径：`--noise-target non-ego` 已避免相对误差“叠加/双倍”（第 2.1 节）。

**DAIR 上仍突出的问题（你现在会看到的瓶颈）**
1) **occ-hint 歧义**：车路侧大基线/视野差异导致相关图多峰；如果 `force_occ_pose` 直接用 occ，可能把对齐打崩。
2) **“无初值”仍随噪声波动**：根因往往是实现里仍有“依赖当前 noisy pose 的 gating/决策”（例如是否 apply），而不是 estimator 本身需要初值。
3) **检测框稀疏/错检导致配准不稳**：box matching 在低重叠场景容易走向错误局部最优；需要 hint/refine/gating 来兜底。
4) **分辨率/下采样带来的近似误差**：BEV 离散化 + `grid_sample` 插值导致“对齐/不对齐”对性能影响更敏感，尤其是 yaw。

**下一步最有效的工程抓手（按优先级）**
1) **把 initfree 的 apply 决策彻底与 `T_current` 解耦**（已在 `stage1_v2xregpp.py` 做了第一步，见第 3.3.2 节），并用绝对质量阈值（`min_precision/min_matches/min_stability`）替代“相对 current 的提升”。
2) **为 occ-hint 加强置信 gating**：用 `occ_hint_min_peak_ratio / min_peak` 过滤歧义帧，必要时做 multi-hypothesis（top-K yaw/shift）再用 box precision 选优。
3) **需要更准的平移时启用 ICP refine**：在 `occ` 或 `occ_refined` 给出较好 init 时，ICP 往往比纯 box SVD 更能补上平移精度（代价是耗时）。
