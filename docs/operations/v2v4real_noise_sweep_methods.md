# V2V4Real comm=200 外参噪声 Noise Sweep：每条曲线的含义与现象解释

本笔记回答两个问题：
1) 我们的 **noise sweep** 具体是怎么跑的、噪声加在什么地方、每条曲线分别代表什么方法；  
2) 为什么在当前设置下 **baseline（none）** 的 AP50 仍然很高、且随噪声下降不明显。

## 1. 统一口径（保证“只看配准/对齐”的影响）

核心原则：**协同感知模型/权重固定**，只替换“位姿/外参对齐模块”，看检测 AP 随外参噪声变化的曲线。

本次 v2v4real(comm=200) sweep 固定设置如下：
- Cooperative model：`HEAL/opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25`
  - 该模型在训练时启用了 pose noise augmentation（配置里 `noise_setting.pos_std=1.0, rot_std=1.0, target=all`，见 `.../config.yaml:185`）。
- Dataset：V2V4Real `test`，并开启 multi-ego 展开（`base_len=1993, expanded_len=3986`，见 slurm 输出）。
- Sweep：paired sweep，`pos_std = rot_std ∈ {0,1,2,3,4}`（单位 m / deg），`noise_target=non-ego`。
- Comm：`--comm-range-override 200`。
- 推理脚本：`HEAL/opencood/tools/inference_w_noise.py`
- Pose-corrector 需要的 stage1 cache（统一使用同一个）：
  - `HEAL/opencood/logs/v2v4real_stage1_pointpillar_from_pastat_bestval17_80boxes/test/stage1_boxes.json`
  - 注意：这个 stage1 cache **只用于 pose-correction**（如 v2xregpp/freealign/oracle），不改变 cooperative model 自己的检测网络权重。

产物：
- 每条曲线一个 YAML：`HEAL/opencood/logs/<model_dir>/AP030507_<method>_comm200_paper.yaml`
- 两张图：
  - `docs/operations/v2v4real_comm200_ap50_noise_curve_mix.png`
  - `docs/operations/v2v4real_comm200_ap50_noise_curve_stable.png`

补充（可重复性/公平性）：不同 run 的 `--num-workers` 不完全一致（baseline=4，其它多为 0），且当前实现不会“每个 noise level 重置 RNG seed”，因此不同方法之间的每档噪声并非完全相同的随机采样；不过由于样本数较大，曲线整体趋势仍具参考价值。若要严格可比，建议统一 `--num-workers 0` 并在 `inference_w_noise.py` 中为每个 noise level 设定固定 seed。

## 2. 噪声注入：加在什么地方、加到谁身上

- 注入代码：`HEAL/opencood/utils/pose_utils.py:add_noise_data_dict`
- 注入对象：对 `lidar_pose` 的 `(x, y, yaw)` 进行高斯噪声（单位 m / deg），并保存 clean 版本（`lidar_pose_clean` / `lidar_pose_clean_np`）。
- `--noise-target non-ego` 的含义：
  - 只对 **非 ego** 的 CAV 加噪；ego 自己不加噪。
  - 这样“ego↔cav 的相对位姿误差规模”更接近用户指定的 std（否则 ego 和 cav 同时加噪会叠加）。

YAML 里 `rel_error_stats` 的含义（很关键）：
- 统计的是 **“最终用于融合的 pose” vs “clean pose”** 的相对误差；
- 对 `none`：它基本反映“注入噪声本身”的误差；
- 对 `v2xregpp_* / freealign_* / v2vloc_*`：它反映“注入噪声 + pose correction 后剩下的残差误差”（可能更小，也可能更大）。

## 3. 每条曲线到底做了什么（`--pose-correction` 语义）

下表是本次曲线里常用方法的“输入/行为/注意点”（具体开关见每个 slurm `.out` 的 `cmd:` 行）：

### 3.1 baseline：`none`

- 含义：**不做任何外参修正**。直接用 noisy `lidar_pose` 构造 `pairwise_t_matrix`，中融合里用它 warp/对齐 BEV 特征。
- 本次命令（摘自 `slurm_v2v4_none_comm200_paper_143.out`）：
  - `--pose-correction none`

### 3.2 V2X-Reg++：`v2xregpp_initfree`

- 主要输入：stage1 cache 里的每车检测框（`pred_corner3d_np_list`）。
- 含义：每帧独立地用 **检测框匹配** 估计 ego->cav 相对位姿，solver 先产出 override map，
  dataset 只注入 override 后再进入协同感知融合（不再在 dataset 内跑求解）。
- 本次命令（摘自 `slurm_v2v4_v2xregpp_initfree_comm200_paper_144.out`）：
  - `--pose-correction v2xregpp_initfree --stage1-result <stage1_boxes.json>`
- 注意：
  - “initfree”不是“完全不看初值”的数学意义：当匹配质量差/候选不足时，会出现 fallback（输出仍受 noisy pose 影响），所以曲线仍可能随噪声下降。

### 3.3 V2X-Reg++ stable：`v2xregpp_stable`

- 含义：在 `v2xregpp` 输出的相对位姿 `T_est` 基础上，再套一层 **stable delta filter**（EMA + max-step gate），
  solver 负责平滑并产出 override map，dataset 仅注入。
- 本次用于画 `v2v4real_comm200_ap50_noise_curve_stable.png` 的命令（摘自 `slurm_v2v4_v2xregpp_stable_occlidar_comm200_paper_157.out`）：
  - `--pose-correction v2xregpp_stable --stage1-result <stage1_boxes.json>`
  - `--v2xregpp-use-occ-hint --v2xregpp-use-occ-pose --v2xregpp-occ-from-lidar --v2xregpp-force-occ-pose`
  - 也就是说这条 stable 曲线并非“纯框匹配”，而是强制走 occ-from-lidar 的 pose（再做 stable 平滑），更接近“无初值”的路线。
- 注意（重要）：stable 是 **状态机**，对 sample 顺序很敏感；如果 dataloader 顺序跨 sequence / 跨 ego 跳跃，state 会漂移，表现为噪声=0 也会产生很大误差。

实现位置：
- `HEAL/opencood/extrinsics/pose_correction/stage1_v2xregpp.py`（估计 + stable delta filter）

### 3.4 FreeAlign（paper 版）：`freealign_paper` / `freealign_paper_stable`

- 主要输入：stage1 cache 的检测框。
- 含义：按 FreeAlign 的 “anchor selection + 局部仿射/SE(2) 拟合” 思路，从框的几何/相似性构建对应关系并估计相对位姿。
- 本次命令：
  - initfree：`slurm_v2v4_freealign_paper_comm200_paper_145.out`
  - stable：`slurm_v2v4_freealign_paper_stable_comm200_paper_*.out`
- 注意：本次在 V2V4Real 上 `freealign_paper` 的 `rel_error_stats` 显示 **噪声=0 时就有非常大的相对误差**（例如 `AP030507_freealign_paper_comm200_paper.yaml` 里 mean rel_trans≈29m、mean yaw≈50°），这通常意味着：
  - 坐标系/角度定义不一致（或 stage1 cache 字段/单位与 FreeAlign 假设不一致）；或
  - 估计退化到某个“几乎固定的错误解”，导致检测表现接近“只靠 ego 单车”，因此曲线看起来几乎水平。

实现位置：
- `HEAL/opencood/extrinsics/pose_correction/stage1_freealign.py`

### 3.5 V2VLoc-style oracle：`v2vloc_oracle_initfree` / `v2vloc_oracle_stable`

- 主要输入：stage1 cache 的 `lidar_pose_clean_np`（噪声注入前的 pose）。
- initfree（真正 oracle 上界）：
  - 直接覆盖为 clean pose，因此 `rel_error_stats` 近似 0，理论上对噪声不敏感。
  - 但本次 `AP030507_v2vloc_oracle_initfree_comm200_paper.yaml` 只跑完了 0/1/2 三个点（需要补齐 3/4 才能画完整曲线）。
- stable：
  - 使用同样的 clean pose 作为 `T_est`，但再走 stable delta filter（会把 “oracle 修正量” 当成时序信号滤波）。
  - 这会导致 **并非严格 oracle**：如果 state 漂移/step gate 生效，最终 pose 仍可能偏离 clean（因此 YAML 里误差会随噪声变大）。

实现位置：
- `HEAL/opencood/extrinsics/pose_correction/stage1_pgc_pose.py`

## 4. 为什么 baseline（none）这么高、且下降不明显？

以 `AP030507_none_comm200_paper.yaml` 的 AP50 为例：`[0.5751, 0.5722, 0.5686, 0.5627, 0.5602]`（0→4m/deg 只降 ~0.015）。

这不是“噪声没加上”，而是当前设置下的合理现象，主要原因通常包括：

1) **pos_std=0 的 baseline 本来就是“协同感知模型的真实性能上限之一”**  
   - 在 noise=0 时，`none` 就是用数据集原始外参（clean pose）进行融合，AP 高是正常的。

2) **训练时已经做过噪声增强（noise1）**  
   - 该 cooperative model 训练配置里 `noise_setting.pos_std=1, rot_std=1, target=all`。  
   - 我们测试只到 4，并且只对 non-ego 加噪（相对误差分布往往比“all 都加噪”更温和），所以模型天然更抗噪。

3) **ego 不加噪 + 单车能力不弱 ⇒ 误对齐的非 ego 特征会被“压过去”**  
   - `noise-target=non-ego` 保证 ego 自身特征不受噪声影响；即使其它车对齐偏了，网络仍能靠 ego 单车维持较高 AP。

4) **从 FreeAlign 的“低但平”可以反推：曲线变平不一定代表 pose 更准**  
   - `freealign_paper` 的 pose 残差非常大，但 AP50 仍约 0.553 且几乎不随噪声变，符合“融合几乎失效 → 退化到 ego-only”这一解释。  
   - 所以看鲁棒性时必须同时看 `rel_error_stats`（位姿残差）而不是只看 AP 曲线。

## 5. 本次曲线对应的 YAML 与数字（便于复核）

comm=200, paired pos_std=rot_std=0..4, non-ego noise：
- baseline（none）：`HEAL/opencood/logs/v2v4real_pastat_noise1_.../AP030507_none_comm200_paper.yaml`
  - AP50：`[0.5751, 0.5722, 0.5686, 0.5627, 0.5602]`
- V2X-Reg++（initfree）：`HEAL/opencood/logs/v2v4real_pastat_noise1_.../AP030507_v2xregpp_initfree_comm200_paper.yaml`
  - AP50：`[0.5753, 0.5734, 0.5698, 0.5658, 0.5627]`
- FreeAlign（paper）：`HEAL/opencood/logs/v2v4real_pastat_noise1_.../AP030507_freealign_paper_comm200_paper.yaml`
  - AP50：`[0.5529, 0.5527, 0.5522, 0.5519, 0.5516]`
- V2X-Reg++（stable）：`HEAL/opencood/logs/v2v4real_pastat_noise1_.../AP030507_v2xregpp_stable_comm200_paper.yaml`
  - AP50：`[0.5432, 0.5417, 0.5472, 0.5457, 0.5448]`
- FreeAlign（paper stable）：`HEAL/opencood/logs/v2v4real_pastat_noise1_.../AP030507_freealign_paper_stable_comm200_paper.yaml`
  - AP50：`[0.5395, 0.5398, 0.5403, 0.5381, 0.5380]`
- V2VLoc oracle（stable）：`HEAL/opencood/logs/v2v4real_pastat_noise1_.../AP030507_v2vloc_oracle_stable_comm200_paper.yaml`
  - AP50：`[0.5753, 0.5734, 0.5683, 0.5634, 0.5596]`
- V2VLoc oracle（initfree，上界但未补齐）：`HEAL/opencood/logs/v2v4real_pastat_noise1_.../AP030507_v2vloc_oracle_initfree_comm200_paper.yaml`
  - 当前已跑 AP50：`[0.5753, 0.5752, 0.5753]`（仅 0/1/2；需要补跑 3/4）
