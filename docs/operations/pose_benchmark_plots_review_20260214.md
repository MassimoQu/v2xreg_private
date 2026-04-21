# Pose Benchmark Plots 复盘（per-CAV sweep + dropout full）

Last updated: 2026-02-14

目标：针对你点名的两组 plots，
- `outputs/pose_sweep_1to10_camera_percav_full_plots/pose_sweep_1to10_camera_percav_ap50.png`
- `outputs/pose_dropout_1to10_full_plots/*.png`

给出“为什么看起来平 / 为什么会下降 / 设置差异导致的差距”的**证据链**（从产物 -> YAML 数字 -> 代码逻辑）。

> NOTE（2026-03-01）：本文复盘的是一条 **offline_map/per-CAV sweep** 口径（会在 oracle/offline solver 路径关闭 detection eval 的噪声注入），因此“oracle 平线”在这里是预期现象。  
> 在 unified **online_box**（端到端）且 `comm-range-gating=noisy` 的 system benchmark 下，oracle 是否严格水平取决于 comm-range pruning 是否固定 agent/GT set（见 `docs/operations/benchmark_semantics.md`）。

---

## 0. 先给结论（你最关心的点）

1) **oracle 通常是上界**：在本文这条 offline_map/per-CAV sweep 口径下，`inference_w_noise.py` 会把 detection eval 的 noise 注入关掉（见第 1.1 节证据），所以 oracle 对噪声轴不敏感，表现为水平线是预期现象；但这不是“所有 benchmark 的硬条件”（参见 `benchmark_semantics`）。
2) **baseline 并不平**：两组图里 baseline 都随噪声下降，只是“绝对 AP 下降幅度”较小，肉眼看像平。我们从 YAML 直接列出 `ap50` 序列 + Δ（见第 1.2/2.2 节证据）。
3) **无初值（initfree）曲线下降是合理的**：噪声越大 -> 特征对齐越错 -> coop 融合越伤 -> AP 下降；initfree 方法能把下降“压平”一些，但相机整体压不住到 oracle（见第 1.3/2.3）。
4) **stable 在这类 sweep 下经常更差也合理**：当前 sweep 的噪声是逐帧随机注入（且 dropout 会引入“pose 冻结”），stable 的 EMA/步长限制对这种非平稳噪声可能引入滞后/欠修正，导致比 baseline/single 还差（见第 1.4/2.4）。

---

## 1) per-CAV camera pose sweep（1-10m/deg）

对应图：
- `outputs/pose_sweep_1to10_camera_percav_full_plots/pose_sweep_1to10_camera_percav_ap50.png`

对应汇总 JSONL：
- `outputs/pose_sweep_1to10_camera_percav_full_results.jsonl`

关键设置差异（会导致“跟 canonical 不可混用”）：
- `stage1_result` 是 per-CAV cache：`data/DAIR-V2X/detected/camera_v2xvit_stage1_percav/val/stage1_boxes.json`
- 只包含 **camera**，且 stage1 cache 分布不同（对 pose solver 影响很大）

### 1.1 为什么 oracle 是水平线（证据链）

现象（从 YAML 读数）：
- oracle 的 `ap50` 在 10 个 noise 点完全相同：`[0.2232, ..., 0.2232]`

原因（代码证据）：
- `HEAL/opencood/tools/inference_w_noise.py:805` 会在 offline_map pose solver 路径“求解外参之后”把 detection eval 的 `noise_setting` 设为 `add_noise=False`（只评测修正后的干净外参）。
- `HEAL/opencood/tools/inference_w_noise.py:820` 会在 oracle(=GT) 路径把 detection eval 的 `noise_setting` 设为 `add_noise=False`（保持几何为 GT）。
  - 因此在本文这组 offline_map plots 里 oracle/bounds 曲线会呈现水平线，并且数值应接近“上界”。

### 1.2 baseline 不是平线（证据链）

baseline YAML：
- `HEAL/opencood/logs/HeterBaseline_DAIR_camera_v2xvit_2023_09_09_11_27_38/AP030507_none_sweep10m_camera_baseline_percav_full.yaml`

从 YAML 直接读取 `ap50`：
```
[0.1393, 0.1248, 0.1222, 0.1281, 0.1262, 0.1249, 0.1220, 0.1219, 0.1136, 0.1086]
```

噪声 1 -> 10 的变化：
- AP50@1=0.139, AP50@10=0.109, Δ=-0.031（-22.0%）

### 1.3 “无初值(initfree)”下降幅度（用数字说话）

同一张图（per-CAV stage1）的 AP50@1 -> @10 变化（来自各自 YAML 的 `ap50[0]` 与 `ap50[-1]`）：

| line | AP50@1 | AP50@10 | Δ | 相对Δ |
| --- | --- | --- | --- | --- |
| baseline (none) | 0.139 | 0.109 | -0.031 | -22.0% |
| v2xregpp initfree | 0.138 | 0.114 | -0.024 | -17.4% |
| freealign initfree | 0.125 | 0.107 | -0.019 | -14.9% |
| vips initfree | 0.124 | 0.108 | -0.016 | -13.2% |
| cbm initfree | 0.099 | 0.095 | -0.003 | -3.2% |
| oracle (GT) | 0.223 | 0.223 | +0.000 | +0.0% |

解读：
- 相机 initfree 的“压平”能力有限：相比 baseline，v2xregpp/freealign/vips 的下降幅度确实更小，但离 oracle 仍很远。
- cbm_initfree 曲线几乎不变并不代表“很鲁棒”，而是它整体 AP 就偏低、且对噪声不敏感（更像“没能正确对齐/收益很小”）。

### 1.4 stable 为何会“更差/更陡”（证据 + 合理解释）

稳定策略的 AP50@1 -> @10：

| line | AP50@1 | AP50@10 | Δ | 相对Δ |
| --- | --- | --- | --- | --- |
| v2xregpp stable | 0.139 | 0.065 | -0.074 | -53.4% |
| freealign stable | 0.022 | 0.032 | +0.010 | +44.2% |
| vips stable | 0.131 | 0.106 | -0.025 | -19.0% |
| cbm stable | 0.035 | 0.041 | +0.006 | +17.2% |

你在图里看到的“下面那几条很平/很低”的本质：
- freealign_stable / cbm_stable 的 AP50 全程在 0.02~0.04，已经**明显低于** baseline，且接近/低于 single（图中黑线 ~0.052），说明稳定更新在这里基本是“把外参改坏了/或融合被严重破坏”，这时候曲线形状本身意义不大。
- v2xregpp_stable 的曲线在相机上非常陡，是典型“EMA/步长限制 + i.i.d 噪声”不匹配的症状：噪声每帧随机变化，stable 的平滑会产生滞后，导致误差累积，融合越来越错位 -> AP 迅速掉。

附：legacy single（comm_range=0 / single_comm0）为什么几乎水平？（不要当作 canonical single）
- sweep10m camera single YAML `ap50` 完全常数（证据）：`AP030507_none_sweep10m_camera_single_comm0_full.yaml` 的 AP50 10 个点完全相同 `0.051897...`
- 原因：comm=0 下基本退化成“只用 ego”，`noise_target=non-ego` 时外参噪声对 ego 的贡献很小/无；所以对噪声轴不敏感。
 - canonical single 请用 `single_ego_only=--force-ego-input-only`（保持 comm_range/GT set 不变），见 `docs/operations/benchmark_semantics.md`。

---

## 2) Dropout sweep（pose_dropout_prob=0.2, full）

对应目录：
- `outputs/pose_dropout_1to10_full_plots/`

对应汇总 JSONL：
- `outputs/pose_dropout_1to10_full_results.jsonl`

关键设置解释（证据来自代码）：
- `dropout_prob` 的实现不等于“丢车”，而是 **模拟定位 outage：复用上一帧 pose（pose 冻结）**，并把 `pose_confidence=0.0`。证据：`HEAL/opencood/utils/pose_utils.py:52`（注释说明）+ `HEAL/opencood/utils/pose_utils.py:88`（`skip_noise` 分支）。
  - 这会导致曲线整体更低、且会带来一定的非单调抖动（因为随机 dropout 会改变帧间误差结构）。

### 2.1 camera（best/stable）读图要点

你点名的“会下降的无初值（initfree）”在相机上确实下降，但幅度相对温和：

| line | AP50@1 | AP50@10 | Δ | 相对Δ |
| --- | --- | --- | --- | --- |
| baseline (none) | 0.110 | 0.090 | -0.021 | -18.7% |
| v2xregpp initfree | 0.121 | 0.108 | -0.013 | -10.8% |
| freealign initfree | 0.112 | 0.100 | -0.013 | -11.1% |
| vips initfree | 0.112 | 0.102 | -0.010 | -9.1% |
| cbm initfree | 0.095 | 0.094 | -0.001 | -0.8% |
| oracle (GT) | 0.223 | 0.223 | +0.000 | +0.0% |

稳定策略依然会明显更差（尤其 freealign_stable/cbm_stable/vips_stable）：
- 例如 `freealign_paper_stable` 的 AP50 只有 0.03~0.04，基本“被 single 线压着打”，属于“修正策略不适配当前噪声模型/匹配质量”。

### 2.2 lidar（best/stable）读图要点

LiDAR 的 initfree 方法整体明显更强，且对噪声更稳：

| line | AP50@1 | AP50@10 | Δ | 相对Δ |
| --- | --- | --- | --- | --- |
| baseline (none) | 0.283 | 0.209 | -0.074 | -26.2% |
| v2xregpp initfree | 0.407 | 0.382 | -0.024 | -5.9% |
| freealign initfree | 0.401 | 0.372 | -0.029 | -7.3% |
| vips initfree | 0.349 | 0.298 | -0.051 | -14.5% |
| cbm initfree | 0.316 | 0.313 | -0.004 | -1.1% |
| oracle (GT) | 0.431 | 0.431 | +0.000 | +0.0% |

重要解读：
- 在 LiDAR 上，v2xregpp/freealign 能把“从 baseline 到 oracle 的 gap”明显吃掉（AP50 大幅高于 baseline），这说明 pose solver 在 LiDAR 的 stage1/matching 上更可靠。
- single（comm0）在 LiDAR dropout sweep 里并不一定低于 baseline：当 coop 外参错到一定程度，**“不合作”反而更好**，这不是 bug，是一个应当展示出来的现实下界。

### 2.3 single 在 dropout sweep 下为什么不严格水平（证据链）

你会发现 dropout sweep 的 single（comm0）不是完全水平，原因来自 dropout 实现：
- `add_noise_data_dict` 在 `skip_noise=True` 时会对**所有 CAV（包括 ego）**复用 last_pose，并把 `pose_confidence=0.0`。
- 因此即使 comm=0，“ego 自己的 pose/置信度”也可能被影响，导致 AP50 轻微波动。

证据（从 YAML 读数）：
- camera dropout single AP50：`[0.0400, 0.0383, 0.0366, 0.0422, ...]`
- lidar dropout single AP50：`[0.3913, 0.3773, 0.3936, 0.3984, ...]`

### 2.4 需要单独标红的异常（建议后续排查）

LiDAR `vips_stable` 在 dropout sweep 下出现明显的非单调“跳变”（噪声 8/9 的 AP50 突然跳高）：
```
vips_stable ap50=[0.2937, 0.2990, 0.2483, 0.2466, 0.2455, 0.2441, 0.2417, 0.2978, 0.2937, 0.2392]
```

这通常意味着：
- pose solver 在某些噪声档位出现“偶发大错/偶发回退”，或者
- stable 状态在不同噪声档位之间被意外复用/重置（需要结合 `rel_error_stats` 与 `pose_solver.applied` 看）。

---

## 3) 你觉得“全是平线”的根因：多数是“读图口径”+ 少数是真问题

建议你以后看图时用 3 个 sanity checks 判断“是不是正常的 benchmark”：

1) **oracle 通常最高**；是否“严格水平”取决于你是否冻结了 comm-range pruning 语义以及是否保留噪声注入（参见 `benchmark_semantics`）。
2) **baseline 应随噪声下降**（否则说明噪声没注入进 detection eval）。
3) **single 可能比 baseline 高**（当 coop 在错外参下伤害了融合，这是正常现象；它是你需要的“及时止损下界”）。

如果某张图违反了 (2)，那才是“曲线平”最危险的信号，需要回到 `inference_w_noise.py`/YAML 检查是否误把 noise 关掉了。
