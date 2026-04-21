# Comm-Range Gating 与 CBM/VIPS 敏感性：证据链与实证对照（DAIR / OPV2V / V2V4Real）

更新：2026-03-04

这份文档只解决一个核心困惑：

> 为什么 `comm-range-gating noisy` vs `clean` 会对（尤其是）CBM/VIPS 这类“基于 boxes 的配准”方法产生很大影响，甚至让曲线形态/排序在不同数据集上差很多？

结论先说（TL;DR）：

- **comm-range gating 不只是“裁剪输入”**：在 OpenCOOD 的 intermediate/heter 数据集中，它会在 `__getitem__` 里直接 `pop` 掉 out-of-range CAV，进而改变 `record_len/cav_id_list`，也会影响 **merged GT**（任务难度）。因此 `gating=noisy` 让噪声 sweep 同时混入了“邻居集合抖动 + GT 集合抖动”的系统效应。
- **CBM/VIPS 对“盒子重叠/匹配是否存在”非常敏感**：邻居集合抖动会让可用 box/overlap 变少，CBM 容易出现 `no_matches` 或匹配质量骤降；`stable` 还会引入“复用历史 delta”的长尾风险（邻居 blink in/out 时更糟）。
- **必须显式 pin `--comm-range-gating`**：否则 `auto` 可能在 baseline 与 pose-correction 间引入隐式差异（变题/混语义），导致“看起来跑完了但不公平”。

---

## 1) 定义（你需要记住的最小集合）

### 1.1 comm-range gating 是什么

通信范围裁剪（pruning）发生在数据集读取阶段：对每个 non-ego CAV，计算它与 ego 的距离，若 `distance > comm_range` 则该 CAV 会被移除，不再进入后续融合/配准。

关键在于：**距离计算用的是 clean pose 还是 noisy pose**。

- `--comm-range-gating clean`：用 `lidar_pose_clean` 计算距离 → **邻居集合不随噪声改变（诊断更干净）**
- `--comm-range-gating noisy`：用 `lidar_pose` 计算距离 → **邻居集合会随噪声改变（更贴近系统）**

### 1.2 “邻居集合改变”会带来什么

在 intermediate/heter 数据集中，pruning 会直接改变：

- `base_data_dict` 中还剩哪些 agent
- `cav_id_list / record_len`（因此影响后续融合/配准）
- **merged GT**：仅会 stack/merge “保留下来的 agent” 对应的 GT（任务本身被改变）

所以 `gating=noisy` 时，你扫噪声并不只是“姿态更差”，而是**输入 agent 集合与 GT 集合也在抖**。

---

## 2) 代码级证据链（从 CLI 到 AP 曲线为什么会变）

### 2.1 噪声注入：为什么会同时存在 clean/noisy pose

`add_noise_data_dict` 会把当前 pose 复制成 clean，再对 `lidar_pose` 加噪：

- `HEAL/opencood/utils/pose_utils.py:45` `add_noise_data_dict`（`lidar_pose -> lidar_pose_clean`）
- `HEAL/opencood/utils/pose_utils.py:92`、`HEAL/opencood/utils/pose_utils.py:112`（对 `lidar_pose` 加噪）

### 2.2 pruning（comm-range gating）在哪里发生：它真的会改变 agent set 与 merged GT

Intermediate fusion 数据集在 `__getitem__` 内做距离裁剪（核心行为：`pop` out-of-range agent）：

- 距离计算用 clean 还是 noisy：`HEAL/opencood/data_utils/datasets/intermediate_fusion_dataset.py:383-387`
- out-of-range agent 被移除：`HEAL/opencood/data_utils/datasets/intermediate_fusion_dataset.py:394-404`
- merged GT / label 只由保留下来的 agent 生成：`object_stack -> object_bbx_center -> generate_label`，见 `HEAL/opencood/data_utils/datasets/intermediate_fusion_dataset.py:477-515`

Heter intermediate fusion 同理：

- `HEAL/opencood/data_utils/datasets/intermediate_heter_fusion_dataset.py:454`

### 2.3 `--comm-range-gating` 如何落到 dataset 行为上

CLI 参数来自：

- `HEAL/opencood/tools/inference_w_noise.py:461-468`（`--comm-range-gating`）

最终转成：

- `HEAL/opencood/tools/inference_w_noise.py:886-890` 设置 `hypes["comm_range_use_clean_pose"]`

dataset 读取该配置：

- `HEAL/opencood/data_utils/datasets/intermediate_fusion_dataset.py:81` 初始化 `self.comm_range_use_clean_pose`

### 2.4 更隐蔽但更重要：`auto` gating 会导致“跨方法不公平”

当 `--comm-range-gating=auto` 时，comm-range pruning 用 clean/noisy pose 的语义不是固定的，会被 runtime/pose-correction 路径改写：

- online backend 会先把 `hypes["comm_range_use_clean_pose"]=True`（默认 clean），见 `HEAL/opencood/tools/inference_w_noise.py:860-864`
- 但若你显式传 `--comm-range-gating clean/noisy`，会在后面覆盖，见 `HEAL/opencood/tools/inference_w_noise.py:883-890`

因此，如果你不显式 pin gating，**baseline（none）与 pose-correction（cbm/vips/…）可能在不同 gating 下运行**，导致比较结果不是“方法差异”，而是“题目差异”。

本仓库已经把它当作 benchmark 的硬前置门槛：

- `tools/run_opv2v_fullbench_fast.py:1097-1103`：online backend + `comm-range-gating=auto` 直接 precheck fail

### 2.5 额外证据：pose override 的顺序会让 noisy gating 更“系统化”

pose override（把 `lidar_pose` 改写成方法输出）发生在 pruning 之前：

- override 入口：`HEAL/opencood/data_utils/datasets/intermediate_fusion_dataset.py:335-361`
- noisy gating 用的就是 `params["lidar_pose"]`：`HEAL/opencood/data_utils/datasets/intermediate_fusion_dataset.py:383-387`

所以在某些 offline/override 路径下，方法输出甚至可能反过来影响“谁在 range 内”（进一步引入 confound）。
注意：上述“自反馈 confound”主要发生在 `pose_override_enabled=True` 且你又强制 `--comm-range-gating noisy`（即 pruning 读的是被 override 的 `lidar_pose`）时；否则默认更偏向用 clean pose 做 pruning（见 `HEAL/opencood/data_utils/datasets/intermediate_fusion_dataset.py:81` 与 `HEAL/opencood/tools/inference_w_noise.py:860-864`）。

---

## 3) 为什么 CBM/VIPS 对 gating 特别敏感（机制 + 代码证据）

### 3.1 CBM 的失败模式：empty / no_matches / svd_failed

CBMEstimator：

- 空输入直接失败：`HEAL/opencood/extrinsics/late_fusion/cbm.py:87-88`
- 匹配为空直接失败（`no_matches`）：`HEAL/opencood/extrinsics/late_fusion/cbm.py:119-126`
- SVD 解算失败会返回 `svd_failed`：`HEAL/opencood/extrinsics/late_fusion/cbm.py:136-145`

底层 matcher 会把“平均对齐距离过大”的匹配候选整体清掉：

- `legacy/v2x_calib/corresponding/CBM_torch.py:147-149`（`absolute_dis_lim` gate）

**noisy gating 的直接后果**：

1) 更容易 drop 掉“本来就靠边界”的邻居（可用 pair 少）  
2) 即便没 drop，剩下的 pair 往往 overlap/匹配更差（det boxes 更难匹配）  
=> CBM 更容易出现 `no_matches`，或者输出长尾错误（rel_error_stats mean 很大但 success@2m 仍有一定比例）

### 3.2 stage1-based pose correction 只对“pruning 后的 cav_id_list”生效

CBM/VIPS 的 stage1 pose corrector 只遍历 `cav_id_list`（即 pruning 后仍在场的 agent）：

- `HEAL/opencood/extrinsics/pose_correction/stage1_vips_cbm.py:267`（`for cav_id in cav_id_list:`）

因此，一旦 noisy gating 把某个 agent 剪掉，该 agent 既不会被修正，也不会被融合 → 下游 AP 直接受影响。

### 3.3 stable 的额外风险：blink in/out 会让“复用历史 delta”更危险

stable 分支会缓存上一帧 delta 并在当前没有有效估计时继续使用（带平滑/步长限制）：

- `HEAL/opencood/extrinsics/pose_correction/stage1_vips_cbm.py:356-369`

当 noisy gating 导致某个 agent **时有时无** 或时序关联被破坏时，stable 更容易把“旧 delta”用到不该用的地方，出现长尾错误。

---

## 4) 数据集层面的“为什么差这么多”（几何证据）

你会看到同样是 `gating=noisy`：

- OPV2V/DAIR 曲线更抖（更敏感）
- V2V4Real@200 往往更平（不敏感）

原因链条是：**ego↔non-ego 距离分布相对 comm_range 的位置**。

已经在这份文档做了量化（near-boundary rate + Monte-Carlo dropout）：

- `docs/operations/dataset_comm_range_and_gating_analysis_20260228.md`

这里把关键数字直接摘出来（用 `tools/analyze_comm_range_gating_effect.py` 从 stage1 cache 的 `lidar_pose_clean_np` 估计；仅考虑平移噪声，因为距离 gating 只看 x/y；`mc_draws=5000`）：

- OPV2V (comm_range=70)：near-boundary(±5m)≈2.44%；sigma=10m 时 in-range link dropout≈2.07%
- DAIR (comm_range=100)：near-boundary(±5m)≈4.70%；sigma=10m 时 in-range link dropout≈3.31%
- V2V4Real (comm_range=70)：near-boundary(±5m)≈0.00%；sigma=10m 时 in-range link dropout≈1.45%

其中最关键的一句话（解释曲线“抖不抖”）：

- near-boundary 比例越高，noisy gating 越容易发生 link 翻转（in-range ↔ out-of-range），agent set/GT set 就越抖。

---

## 5) 实证对照（把“推测”补成“证据”）

（指标口径补充）文中 “applied” 指 `pose_provider_applied_count`：每个样本是否真的应用了 pose correction 的 0/1；汇总后的 mean 值可粗略理解为“在当前 comm_range 下，至少还有 1 个非 ego 可用且校正被采纳的比例”。实现：`HEAL/opencood/utils/pose_provider_runtime.py:1333-1337`。

### 5.0 一个容易忽略但会“把 smoke 结论带歪”的事实：V2V4Real 的 head 子集在 clean gating 下可能全是单车

在 V2V4Real（comm_range=70）的 stage1 cache 里，样本按 `sample_idx` 排序后，**前 294 个样本 ego↔non-ego 的 clean 距离都 >70m**（因此 `--comm-range-gating clean` 会把非 ego 全部 pruning 掉，record_len 变成 1，导致：

- baseline / single / 所有 core 方法曲线会“看起来几乎一样”（因为输入事实上都变成单车）
- rel_error_stats 也会大量缺失（没有 non-ego 就无法计算相对误差）

这不是 bug，是**子集选择偏置**：`--max-eval-samples 200` 默认取 dataset head，刚好落在 out-of-range 前缀里。

证据（从 `opencood/logs/v2v4real_stage1_pointpillar_from_pastat_bestval17_percav/test/stage1_boxes.json` 的 `lidar_pose_clean_np` 直接算距离）：

- head200：inside<=70 = 0/200；距离分位数 q50≈80.72m（都在 range 外）
- prefix_all_out = 294（即 sample_idx 0..293 全 out-of-range）
- 存在一个 200 样本窗口 sample_idx 294..493：inside<=70 = 200/200（适合作为 smoke 子集）

为避免再被 head 子集带歪，我在 `inference_w_noise.py` 增加了 `--eval-sample-start`（跳过前 N 个样本，再取 `--max-eval-samples`），并在 V2V4Real runner 里透传该参数。

### 5.1 V2V4Real：clean vs noisy 的现象复盘（注意：不是严格控制变量）

两次 run 的关键信息：

- clean gating：`outputs/v2v4real_core_core_clean_v4_laneD_20260303_run1/manifest.json`（`comm_range_gating: clean`）
- noisy gating：`outputs/v2v4real_core_v2v4real_noise10_comm70_20260227_062938/logs/*.log`（可见 `--comm-range-gating noisy`）

我们观测到（CBM best）：

- clean：mean AP50 ≈ 0.5676；noise0 applied≈0.24
- noisy：mean AP50 ≈ 0.5517；noise0 applied≈0.83

重要更正（避免过度归因）：

- 这两次 run **不满足“唯一差别是 gating”**。noisy run 的日志里只传了 `--pose-compare-current`，但没有显式 pin compare gate（例如 `--pose-current-precision-threshold` 等）；clean run 的 `manifest.json` 里明确记录了 compare gate pins，并在日志里显式传参。  
  - clean run 证据：`outputs/v2v4real_core_core_clean_v4_laneD_20260303_run1/logs/cbm_initfree_noise0.log`（含 `--pose-current-precision-threshold 1.8 ...`）  
  - noisy run 证据：`outputs/v2v4real_core_v2v4real_noise10_comm70_20260227_062938/logs/cbm_initfree_noise0.log`（仅 `--pose-compare-current`）

因此：

- 上述“applied 在 noise=0 大幅上升、AP 下滑”的现象，更可能主要来自 **compare-current gate 没 pin**（导致 CBM 更接近“能算就 apply”），而不是 gating 本身。
- 该现象仍然能作为“为什么必须 pin compare-current 阈值”的证据，但不能单独作为 gating 的对照结论。

### 5.2 OPV2V：控制变量实验（smoke200），唯一差别是 gating

为避免“历史 run 混语义”，我补了一个 **严格控制变量** 的对照：

- **clean gating**：`outputs/full_bench_opv2v_cbm_gating_clean_smoke200_20260304_a1/`（已完成）
- **noisy gating**：`outputs/full_bench_opv2v_cbm_gating_noisy_smoke200_20260304_a1/`（已完成）

共同设置（写在各自 `config_snapshot.json`）：

- solver_backend=`online_box`；runtime_mode=`register_and_fuse`；pose_source=`noisy_input`
- comm_range_override=`70`
- noise axis=`0..10`（paired sweep），noise_target=`non-ego`
- max_eval_samples=`200`（相同样本子集）
- methods 仅跑 `cbm`（best+stable）+ bounds（baseline/oracle/single）

clean gating（已出结果）的 smoke200（mean AP50）：

- lidar：baseline≈0.6663；cbm-best≈0.7713；cbm-stable≈0.6919；oracle≈0.9550；single≈0.8873
- camera：baseline≈0.1128；cbm-best≈0.0893；cbm-stable≈0.0754；oracle≈0.1608；single≈0.1195

noisy gating（已出结果）的 smoke200（mean AP50）：

- lidar：baseline≈0.6641；cbm-best≈0.7730；cbm-stable≈0.6921；oracle≈0.9550；single≈0.8876
- camera：baseline≈0.1130；cbm-best≈0.0905；cbm-stable≈0.0761；oracle≈0.1608；single≈0.1195

结论（就这次控制变量 smoke200 而言）：

- **OPV2V 上 gating(clean vs noisy) 对 CBM 的 AP 影响非常小**（cbm-best 的 mean AP50 变化量在 ~0.001-0.002 的量级）。
- 这说明你之前观察到的“巨大差异”，更可能来自 **混语义**（例如 `auto` gating 造成 baseline 与 pose-correction 的 pruning 语义不一致）或其他 confound，而不是 gating 本身。

注意点（也属于证据链的一部分）：

- 在 smoke200 的 head 子集里，`pose_provider_applied_count`（例如 oracle）≈0.405，说明该子集有相当比例样本在 comm_range 下只剩 ego（这会放大 CBM 的“无可比 pair”问题）。这不是 bug，是数据子集分布特征。

### 5.3 V2V4Real：严格控制变量实验（smoke200 + start294），唯一差别是 gating（clean vs noisy）

为把 V2V4Real 的 gating 结论也补成“证据”（且避免 head 子集退化为单车），我做了一个严格控制变量对照：

- clean gating：`outputs/v2v4real_core_v2v4real_gating_clean_smoke200_start294_20260304_a2/`
- noisy gating：`outputs/v2v4real_core_v2v4real_gating_noisy_smoke200_start294_20260304_a2/`

共同设置（写在各自 `manifest.json` / logs 里）：

- comm_range=70，noise axis=0..10（paired），noise_target=non-ego
- solver_backend=online_box，runtime_mode=register_and_fuse，pose_source=noisy_input
- compare-current gate pins 显式固定：`distance=3.0 / current_precision=1.8 / minimp=0 / minmatched=0`
- smoke 子集：`max_eval_samples=200`，并加 `eval_sample_start=294`（保证 clean gating 下也确实有非 ego in-range）

结论（mean AP50，对 clean vs noisy gating）：

- oracle_gt：0.581605 vs 0.581542（几乎不变）
- baseline：0.565021 vs 0.564953（Δ≈-0.00007）
- vips-best：0.564619 vs 0.564592（Δ≈-0.00003）
- cbm-best：0.561736 vs 0.561913（Δ≈+0.00018）

=> 在这个“同样样本子集 + 同样 gate pins + 唯一差别是 gating”的实验里，**V2V4Real 上 clean/noisy gating 对 CBM/VIPS 的 AP 影响同样非常小**。

这与 OPV2V 的控制变量结论一致：你之前看到的巨大差异，更可能来自“混语义/混设置”（最常见的是 compare-current gate 没 pin、或 gating=auto 被路径改写），而不是 gating 本身。

---

## 6) 对 unified benchmark 标准的直接落地建议（避免以后再踩坑）

1) **把 gating 当作题目的一部分写死**（每次 run 都要在 manifest/config_snapshot 里可追溯）  
   - 诊断公平（Track-D）：`--comm-range-gating clean`（agent set 固定）  
   - 系统真实（Track-S）：`--comm-range-gating noisy`（接受 agent set/GT set 抖动）  

2) **禁止 `auto` 用于 benchmark**（避免 baseline 与方法混语义）  

3) **single 只能用 `--force-ego-input-only`**（而不是 `comm_range=0`）  
   - `comm_range=0` 会改变 GT 集合（任务更容易），可能出现 `single > oracle` 的假象  
   - `--force-ego-input-only` 才是“同 GT 难度下的单车下界”  

4) **用 rel_error_stats 做旁证，但不要用它替代 AP**  
   - CBM/VIPS 这类方法常见“success@2m 还行但 mean_trans 很大”的长尾，AP 的变化更可信。

---

## 7) 下一步还差哪些实验（如果你要把结论写进论文/报告）

按优先级：

1) （已完成）V2V4Real strict-control clean vs noisy gating smoke 对照（同时 pin compare-current 阈值，并用 eval_sample_start 避免 head 子集退化为单车）  
2) 如果要进一步解释“为什么 CBM/VIPS 召回低”：在 `stage1_vips_cbm.py` 加 debug 统计（no_matches/empty_boxes/compare-gate reject 比例）并写进 YAML timing_stats（建议只在 smoke 模式打开）  
3) 若要跨数据集解释曲线形态：用 `tools/analyze_comm_range_gating_effect.py` 对每个 dataset+comm_range 量化 near-boundary 与 link 翻转概率（已有框架，缺的只是把你关心的配置跑全并入表格）
