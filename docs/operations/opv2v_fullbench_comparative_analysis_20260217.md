# OPV2V Fullbench Comparative Analysis (old vs new, + offline reference)

Last updated: 2026-02-17

目标：把 **这次（online/fullbench, autopilot auto3）** 的结果，和 **前面几次 OPV2V fullbench** 以及你点名的 **离线 DAIR pose sweep/dropout** 做一次“证据链式”的对照复盘，给出论文可用的观察点 + 可执行的下一步研究/实验机会。

---

## 0) 先给结论（总-分-证据）

**总：这次 `20260216_auto3` 的 OPV2V online/fullbench 结果是可信的主结果**，它修复了你之前最在意的两类“曲线不合理/全平线”基础问题：

1) **LiDAR baseline 之前几乎水平（flat）是语义问题，不是画图问题**：旧 run 使用了 `pose_override=zero`（no-extr suite），直接把 pose-noise sweep 抵消掉，导致 baseline 随噪声不变；新 run 换成不带 pose_override 的 LiDAR checkpoint 后，baseline 对噪声出现明显下降（符合预期）。
2) **Camera 方法曲线以前几乎重合是 stage1 cache 结构错误**：旧 run 的 OPV2V camera stage1 cache 只有 50 个 sample 且 `len(cav_id_list)!=len(pred_corner3d_np_list)`，导致 offline_map solver 的 `pose_solver.applied==0`，所有方法退化成“没做 pose correction”；新 run 换成 `*_stage1_percav`（2170 samples, list 对齐）后，方法曲线开始分化（虽然 camera 上整体收益仍非常有限）。

**分：方法效果（new run）**：

- **LiDAR**：`v2xregpp-best` 基本追平 oracle（均值 AP50≈0.935 vs oracle≈0.959，覆盖 baseline→oracle gap 的 ~95%），且对噪声极稳；`freealign-best` 次之（≈0.842）；`vips-best/cbm-best` 基本回到 baseline（≈0.43），说明在当前 online 设置下这两条“best”没有带来有效注册增益；部分 `stable` 在中等水平（≈0.48~0.52）。
- **Camera**：只有 `v2xregpp-best` 在均值上比 baseline 略高（+0.005 左右），其他方法多为不增反降；且从 `rel_error_stats` 反推，部分 camera 在线修正甚至会把相对位姿误差放大（见第 5.2 节证据）。
- **drop20 vs noise10**：在 OPV2V fullbench 里两条 sweep 的数值几乎一样（MAD 很小），这本身就是一个值得写进论文/做 ablation 的点：当前 dropout 注入对总体 AP50 的“额外挑战”非常弱（见第 6 节）。

**证据**：本文件后续每个结论都用路径+数字支持；最关键的“可信主结果”链路见第 1~4 节。

---

## 1) 本次/对照 run 的“源数据”

### 1.1 New (主结果)：OPV2V online/fullbench, autopilot auto3

- run dir（产物目录）：
  - `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/`
- 结果 JSON（后续所有表格都从这里计算）：
  - `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/results_ap50_from_yaml.json`
- plot 目录（你现在看到的最新曲线图）：
  - `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/plots_yaml/`
- config 快照（证明这次跑的到底是什么设置）：
  - `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/config_snapshot.json`
- 完整完成证据（不要再用 log grep / task_summary.json 这种易错口径）：
  - `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/run_state.jsonl`

辅助证据：
- autopilot 总日志：`outputs/opv2v_autopilot_20260216_auto3/autopilot.log`
- supervisor 状态：`outputs/opv2v_autopilot_supervisor_20260216_auto3/state.json`
- “证据报告”（包含 stage1 校验、pose_override 检查等）：`docs/operations/opv2v_fullbench_evidence_autopilot_20260216_auto3.md`

### 1.2 Old (最相关对照)：OPV2V fullbench fast 20260212

- run dir：`outputs/full_bench_opv2v_fullbench_fast_20260212/`
- 结果 JSON：`outputs/full_bench_opv2v_fullbench_fast_20260212/results_ap50_from_yaml.json`
- plot：`outputs/full_bench_opv2v_fullbench_fast_20260212/plots_yaml/`
- config：`outputs/full_bench_opv2v_fullbench_fast_20260212/config_snapshot.json`

### 1.3 Offline reference（你点名“更合理”的两组离线 png）

这两组是 **DAIR-V2X 的离线 sweep/dropout**（不是 OPV2V，也不是 online/fullbench），只能当“历史参考口径”，不要与 OPV2V online 直接混画。

- `outputs/pose_sweep_1to10_camera_percav_full_plots/`
- `outputs/pose_dropout_1to10_full_plots/`

对应证据链复盘文档（已写好）：
- `docs/operations/pose_benchmark_plots_review_20260214.md`
- “离线 vs 在线为何差这么多”的总复盘（含早期 OPV2V pathologies）：`docs/operations/offline_vs_online_benchmark_gap_20260215.md`

---

## 2) New run 真的跑完了吗？（“证据链”而不是感觉）

### 2.1 以 `run_state.jsonl` 为准（source of truth）

`docs/operations/opv2v_fullbench_evidence_autopilot_20260216_auto3.md` 已从
`outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/run_state.jsonl`
统计得到：

- unique_tasks_started: 404
- unique_tasks_ended: 404
- final_end_codes: {0: 404}
- （2026-02-20 更新）camera `v2xregpp_occhint` append 后同 run_id 统计为 444/444/code0=444；核心 cross-modal scope 仍是 404。

这条链路是“任务级别事实”，比任何 log grep 都可靠。

### 2.2 `task_summary.json` 可能是陈旧/误导

同一份证据报告里也给出了一个非常典型的坑：
- `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/task_summary.json` 显示 `pending=404`
- 但 `run_state.jsonl` 明确显示 `ended=404`

结论：**你之前“相机 30 个任务永远跑不完/但说跑完了”的混乱，很大概率来自用错了统计口径**（用 summary 文件/日志脚本推断任务完成，而不是用 run_state 事件流）。

---

## 3) Old vs New：关键设置差异（为什么曲线会变）

对照 `outputs/full_bench_opv2v_fullbench_fast_20260212/config_snapshot.json` 与
`outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/config_snapshot.json`：

### 3.1 Camera stage1（决定 camera pose solver 能不能“真的应用”）

- old: `data/OPV2V/detected/opv2v_camera_v2xvit_stage1/test/stage1_boxes.json`
- new: `data/OPV2V/detected/opv2v_camera_v2xvit_stage1_percav/test/stage1_boxes.json`

结构硬证据（直接读 JSON）：

- `data/OPV2V/detected/opv2v_camera_v2xvit_stage1/test/stage1_boxes.json`
  - samples = 50
  - len_mismatch = 50（每个 sample 的 `cav_id_list` 与 `pred_corner3d_np_list` 不对齐）
- `data/OPV2V/detected/opv2v_camera_v2xvit_stage1_percav/test/stage1_boxes.json`
  - samples = 2170
  - len_mismatch = 0

这就是“旧 run camera 方法曲线几乎重合/无意义”的第一性原因。

### 3.2 LiDAR checkpoint（决定 pose-noise sweep 有没有被抵消）

- old lidar model dir：
  - `HEAL/opencood/logs/freealign_repro_opv2v_baseline_noextr_v2xregpp`
  - 其 `config.yaml` 明确包含：
    - `pose_override.enabled: true`
    - `pose_override.mode: zero`
    - 位置：`HEAL/opencood/logs/freealign_repro_opv2v_baseline_noextr_v2xregpp/config.yaml:37-39`
- new lidar model dir：
  - `HEAL/opencood/logs/freealign_repro_opv2v_baseline`
  - `config.yaml` 不包含 `pose_override`

这就是“旧 run LiDAR baseline 全平线/方法全平线”的根因：no-extr 语义和 pose-noise sweep 语义冲突。

### 3.3 Online 语义（new 显式启用）

new config 里明确写了：
- `solver_backend: online_box`
- `runtime_mode: register_and_fuse`
- `pose_source: noisy_input`
- `allow_pose_override: False`
- `skip_preflight: False`

old config 没有这些字段（意味着旧 run 很可能处在默认 offline_map 语义或混杂语义下）。

---

## 4) “为什么之前会平/会错”：把根因落到证据上

### 4.1 LiDAR：old baseline/noise10 的 AP50 序列几乎常数（flat）

从 `outputs/full_bench_opv2v_fullbench_fast_20260212/results_ap50_from_yaml.json` 直接读取：

- old lidar/noise10/baseline/bounds AP50（n=1..10）：
  - `[0.2747, 0.2745, 0.2744, 0.2745, 0.2746, 0.2745, 0.2745, 0.2745, 0.2746, 0.2744]`

对比 new（同一条曲线在主结果里明显下降）：

- new lidar/noise10/baseline/bounds AP50（n=1..10）：
  - `[0.6042, 0.4364, 0.4131, 0.4039, 0.4068, 0.4058, 0.4088, 0.4080, 0.4117, 0.4159]`

解释链路：
- old 使用 `pose_override=zero`（第 3.2 节证据），噪声注入在数据层/override 层被覆盖，baseline 对噪声不敏感 => 曲线必然平。

### 4.2 Camera：old 的 pose solver “统计上确实没应用”（applied=0）=> 方法曲线没意义

随便取一个代表性 YAML（旧 run，camera/noise10/v2xregpp-best/n1.0）：
- `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/AP030507_v2xregpp_initfree_opv2v_fullbench_fast_20260212_camera_noise10_v2xregpp_best_n1.0.yaml`
  - `timing_stats[0].pose_solver.applied == 0`

并且同 run 下 freealign/vips/cbm 的 `pose_solver.applied` 也是 0，且它们的 AP50@1 完全一致：
- `AP030507_freealign_paper_opv2v_fullbench_fast_20260212_camera_noise10_freealign_best_n1.0.yaml` ap50=0.205987..., applied=0
- `AP030507_vips_initfree_opv2v_fullbench_fast_20260212_camera_noise10_vips_best_n1.0.yaml` ap50=0.205987..., applied=0
- `AP030507_cbm_initfree_opv2v_fullbench_fast_20260212_camera_noise10_cbm_best_n1.0.yaml` ap50=0.205987..., applied=0

解释链路：
- old camera stage1 cache 是结构错误版本（第 3.1 节证据），solver 无法对齐多车 list => `applied=0` => “方法对比”退化。

### 4.3 20260211 的 camera AP≈0：这是 perception 基座坏掉，不是 pose/noise 问题

旧问题中最极端的一次（你说“垃圾曲线”里最明显的一类）：
- `HEAL/opencood/logs/HeterBaseline_opv2v_camera_v2xvit_2026_01_17_21_49_18/AP030507_none_opv2v_fullbench_20260211_gpu_camera_noise10_baseline.yaml`
  - `ap50` 在 10 个噪声点都是 `~4e-07..6e-07`（≈0）

这类结果不具备讨论注册/融合曲线形状的意义（上游 perception 已经崩了）。

---

## 5) New run（auto3）结果：方法行为、合理性与“值得写进论文的点”

以下统计来自：
- `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/results_ap50_from_yaml.json`
- 图像参考：
  - camera/noise10 AP50：`outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/plots_yaml/noise10_camera_ap50.png`
  - lidar/noise10 AP50：`outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/plots_yaml/noise10_lidar_ap50.png`

### 5.1 LiDAR：注册是“必要条件”（否则 coop 直接伤害），v2xregpp-best 近乎上界

关键均值（noise10，AP50 mean across n=1..10）：

- baseline=0.431, single=0.907, oracle=0.959（**无注册时 coop 反而远低于单车**）
- v2xregpp-best=0.935（覆盖 baseline→oracle gap 的 ~95%）
- freealign-best=0.842（覆盖 ~78% gap，但仍低于 single）
- vips-best=0.432、cbm-best=0.430（≈baseline，几乎没增益）

噪声敏感性（举例 n=1 → n=10）：
- baseline: 0.604 → 0.416（Δ=-0.188）
- v2xregpp-best: 0.942 → 0.933（Δ=-0.008，几乎不掉）
- freealign-best: 0.885 → 0.837（Δ=-0.049）
- vips-best: 0.561 → 0.420（Δ=-0.141，基本“跟 baseline 一起掉回去”）

论文可用解释（不夸大）：
- **协同感知在 pose 噪声下不是“稳健退化”，而是会被外参误差反向伤害**：`single` 明显高于 `baseline`（0.907 vs 0.431 mean），说明“没配准就融合”是错误策略。
- **有效在线配准可以把 cooperative gain 基本追回**：`v2xregpp-best` 从 baseline 直接拉到接近 oracle。

### 5.2 Camera：在线 pose correction 的收益非常有限，且可能“修坏”

关键均值（noise10，AP50 mean across n=1..10）：

- baseline=0.106, single=0.149, oracle=0.302
- v2xregpp-best=0.111（只比 baseline +0.005，覆盖 gap 约 2.5%）
- freealign-best=0.099（比 baseline 低）
- vips-best=0.070、cbm-best=0.053（明显低于 baseline）

更关键的“错误方向”证据（相对位姿误差）：

- baseline（camera/noise10/baseline/n1.0）：
  - `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/AP030507_none_opv2v_autopilot_full_20260216_auto3_a1_camera_noise10_baseline_n1.0.yaml`
  - `rel_trans_m.mean ≈ 1.225m`，`rel_yaw_deg.mean ≈ 0.799deg`
- v2xregpp-best（camera/noise10/v2xregpp-best/n1.0）：
  - `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/AP030507_v2xregpp_initfree_opv2v_autopilot_full_20260216_auto3_a1_camera_noise10_v2xregpp_best_n1.0.yaml`
  - `rel_trans_m.mean ≈ 6.939m`，`rel_yaw_deg.mean ≈ 8.985deg`

含义：
- 至少在这个设置/实现下，camera 的在线 pose correction 并没有把相对位姿拉近 GT，反而出现“平均误差更大”的现象（对应 AP 也没有显著提升）。

论文/研究机会（非常明确）：
- **“为什么 LiDAR 可行而 camera 不行”**：这不是画图问题，而是 stage1/匹配/几何约束与模态特性有关。你可以把它写成一个“跨模态配准可行性差距”的实验结论，然后围绕它做方法改进（深度辅助、跨模态引导、多尺度匹配、置信度门控融合等）。

---

## 6) drop20 vs noise10 为什么几乎一样？（这不是小细节，是实验轴本身的“有效性”问题）

对 new run 做了 sweep 间对照（逐 noise 点比较，取 mean absolute diff / MAD）：

- camera: 大多数方法 `mad_per_noise` 在 0.001~0.005
- lidar: baseline `mad_per_noise≈0.007`，其它方法多在 0.001~0.015

直观结论：**dropout=0.2 在当前 OPV2V fullbench 设置里，对 AP50 的额外扰动非常弱**。

可能原因（需要 ablation 去证伪/证实）：
1) dropout 的实现是“pose freeze + confidence=0”，但下游融合/模型可能根本不使用 `pose_confidence`；
2) OPV2V test 的序列组织方式，使“freeze 上一帧”不一定构成更难的几何错位（尤其当噪声已很大时，dropout 的增量影响可能被淹没）；
3) online 模式下方法本身每帧都在覆盖 pose（注册/重建 pairwise），dropout 被抵消。

写论文时建议把这条当成一个“benchmark 设计有效性”的发现，而不是当成“结果没变化所以没意义”。它提示你：**当前 dropout 轴可能不够 stress**，需要更真实的 outage 模型（相关漂移、长时 outage、分车/分段 outage 等）。

---

## 7) 速度与“全 GPU 化”现状：你要的目标还差在哪

### 7.1 在线 solver 当前大量走 CPU fallback（不是全 GPU）

从 pose timing 聚合（取自各 YAML 的 `pose_timing.*`）：
- new run 的各类 pose solver 都出现 `cpu_fallback_count=1`（每 batch 至少一次 legacy CPU apply 路径）

这意味着：**当前 online pose correction 仍是“GPU 推理 + CPU 配准/写回”的混合路径**，离你要的“全 GPU 在线端到端”还有明显距离。

### 7.2 注意：`results_ap50_from_yaml.json` 里的 pose_sec/pose_fps 有过计数风险

`HEAL/opencood/tools/inference_w_noise.py` 会把 `pose_provider_total_sec`、`pose_override_sec`、`online_solver_sec`、`pairwise_rebuild_sec` 这些都汇总再相加，容易把包含关系重复加进 `pose_sec`（因为 `pose_provider_total_sec` 已经包含其它项）。

建议论文里：
- 用 `pose_provider_total_sec`（或单独的 `online_solver_sec`）做配准开销 proxy；
- 不要直接用当前 `pose_sec/pose_fps` 做严格结论（除非先修复统计口径）。

---

## 8) 论文可用的“可证伪陈述”（你可以直接引用/改写）

1) **Pose-noise 下 coop fusion 会产生负收益**：在 OPV2V LiDAR 上，`single`(AP50≈0.907) 显著高于 `baseline`(≈0.431)，表明未配准的协同融合会强烈伤害检测性能。
2) **有效注册可恢复 cooperative gain，且方法间差距巨大**：`v2xregpp-best` 将 LiDAR AP50 从 baseline 提升到 ≈0.935（接近 oracle≈0.959），而 `vips-best/cbm-best` 在该设置下几乎无增益。
3) **跨模态差距显著**：相同 pipeline 下，camera 的在线 pose correction 对 AP50 的提升非常有限（v2xregpp-best 仅 +0.005 mean），并出现相对位姿误差均值变大的现象。
4) **dropout 轴在当前实现下“挑战不足”**：drop20 与 noise10 的曲线几乎重合，提示需要更强/更真实的 outage 注入才能构成有效 benchmark 维度。

每条都可以用本文件列出的 JSON/YAML/plot 路径复现。

---

## 9) 下一步“研究机会 / 可做的 ablation”（按优先级）

1) **相机配准为何失败/退化**：
   - 先用 `rel_error_stats` 与 AP 的相关性做诊断（误差变大但 AP 未提升，说明修正方向可能错）。
   - 研究：depth/geometry prior、跨模态引导（LiDAR→camera）、置信度门控融合、鲁棒匹配（outlier rejection）。
2) **把“负收益”变成系统设计点**：
   - 现在最强的对照就是 `single`：研究“什么时候应该拒绝融合/降低融合权重”。
3) **全 GPU 在线化**：
   - v2xregpp 有实验性的 GPU stage1 solver 路径（需显式开启），其它方法仍 CPU apply；
   - 研究：GPU 上的匹配/求解、批处理、多车并行、把 stage1 特征缓存搬到 GPU。
4) **Dropout 轴 redesign**：
   - 改成相关漂移 + 连续 outage 段；对 ego/non-ego 做不同 outage；或直接评测“系统级 fallback（single）策略”。
5) **补全 telemetry（让 benchmark 更可解释）**：
   - 记录 `pose_provider_applied`、每帧成功配准对数、残差分布；修复 pose_sec 的重复计时统计。

---

## 10) 你刚刚问的：LiDAR single 为啥这么高？会不会跑错了？

结论：**这条 single 不是“在噪声=1..10 下的单车”，而是“comm_range=0 + noise=0 的单车下界”**；数值高是合理的（LiDAR 单车感知本来就强），且它在 old/new 两次 OPV2V fullbench 里是一致的（不是这次突然跑飞）。

### 10.1 single 任务的真实 launch 参数（硬证据）

看单车任务日志即可（以 LiDAR/noise10 为例）：
- `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/logs/lidar_noise10_single_bounds_n0.0.log`
  - 启动命令明确包含：
    - `--comm-range-override 0`（只保留 ego）
    - `--pos-std-list 0 --rot-std-list 0`（无噪声）
  - 运行时也明确打印：
    - `Noise Added: 0.0/0.0/0.0/0.0.`
    - `The Average Precision ... IOU 0.5 is 0.91`

所以 single 高不是 bug，它是“零噪声 + 只用 ego”的单车性能。

### 10.2 comm_range=0 为什么一定会变成单车（代码证据）

中间融合数据集在取样时会按 `comm_range` 过滤远端 CAV（距离 > comm_range 直接剔除）：
- `HEAL/opencood/data_utils/datasets/intermediate_fusion_dataset.py:365-387`
  - `if distance > self.params['comm_range']: ... continue`

因此当 `comm_range=0` 时，只有距离为 0 的 ego 会保留（等价单车）。

### 10.3 重要口径提醒（写论文/汇报时必须说清）

因为 single 是 `noise=0`，而 baseline/methods 是 `noise=1..10`：
- **single 这条线本质上是“单车下界/止损线”，不是同噪声条件下的对照点**。
- 但在本套设置里 `noise_target=non-ego`，单车只用 ego，理论上对 pose-noise 不敏感，所以用 noise=0 画成水平线是合理的。

---

## 11) 你刚刚问的：V2X-Reg++ 在 LiDAR 上为什么这么强？会不会“偷看 GT”？

结论：**没有发现 GT 泄漏路径**；V2X-Reg++ 强的主要原因是：它用 stage1 的 per-agent 检测框（本地坐标）做 init-free 相对位姿估计，本质上对注入的外参噪声不敏感，所以曲线接近 oracle 是合理现象。

### 11.1 它确实跑的是 online + 有噪声（不是误用 oracle）

看 LiDAR/noise10/v2xregpp-best/n1.0 的任务日志：
- `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/logs/lidar_noise10_v2xregpp_best_n1.0.log`
  - 命令包含：
    - `--solver-backend online_box --runtime-mode register_and_fuse`
    - `--pose-correction v2xregpp_initfree --pose-compare-current`
    - `--stage1-result .../opv2v_lidar_v2xvit_stage1/test/stage1_boxes.json`
  - 且运行时打印：
    - `Noise Added: 1.0/1.0/0.0/0.0.`

### 11.2 关键：stage1 boxes 没有用外参投到 ego/world（避免“GT 坐标系泄漏”）

LiDAR stage1 export 走的是 `UncertaintyVoxelPostprocessor.post_process_stage1`：
- `HEAL/opencood/data_utils/post_processor/uncertainty_voxel_postprocessor.py:74-86`
  - 这里生成 corners 后 **没有做** `project_box3d(..., transformation_matrix)`（代码注释里明确写了但注释掉）
  - `pred_corners_tensor = boxes3d_corner` 直接作为 stage1 输出

含义：stage1 盒子是在 **每个 CAV 自己坐标系** 下输出的，不依赖 clean 外参投影。

### 11.3 V2X-Reg++ 实现本身不读取 clean pose 字段（避免“直接用 GT pose 修正”）

- `HEAL/opencood/extrinsics/pose_correction/pose_solver.py:55-126` 里只有 `method == "gt"` 才会用 `lidar_pose_clean`
- `HEAL/opencood/extrinsics/pose_correction/stage1_v2xregpp.py` 全文不包含 `lidar_pose_clean*` 字段引用（可以 grep 验证）

所以它不是 oracle/gt 路径。

### 11.4 反证：在高噪声点 baseline 的相对位姿误差巨大，而 v2xregpp 把误差明显拉回

同是 LiDAR/noise10：

- baseline n10：
  - `HEAL/opencood/logs/freealign_repro_opv2v_baseline/AP030507_none_opv2v_autopilot_full_20260216_auto3_a1_lidar_noise10_baseline_n10.0.yaml`
  - `rel_trans_m.mean ≈ 12.476m`, `rel_yaw_deg.mean ≈ 8.002deg`, AP50≈0.416
- v2xregpp-best n10：
  - `HEAL/opencood/logs/freealign_repro_opv2v_baseline/AP030507_v2xregpp_initfree_opv2v_autopilot_full_20260216_auto3_a1_lidar_noise10_v2xregpp_best_n10.0.yaml`
  - `rel_trans_m.mean ≈ 1.502m`, `rel_yaw_deg.mean ≈ 1.082deg`, AP50≈0.933

这说明它确实在“对噪声 pose 做修正”，不是把噪声关掉或直接替换成 GT。

## Appendix A) OPV2V old vs new（AP50）关键数表（可用于论文表格初稿）

完整 CSV 版本可由 `results_ap50_from_yaml.json` 直接导出；这里给出最关键的 “mean / n1 / n10” 对照（old=20260212, new=auto3）。

### A.1 LiDAR noise10（最能解释“为什么之前全平线”）

- baseline mean：old=0.275 → new=0.431（Δ=+0.157），且 new 在 n1→n10 有明显下降（0.604→0.416）
- v2xregpp-best mean：old=0.774 → new=0.935（Δ=+0.161）
- freealign-best mean：old=0.779 → new=0.842（Δ=+0.062）
- vips-best mean：old=0.782 → new=0.432（Δ=-0.350）
- cbm-best mean：old=0.776 → new=0.430（Δ=-0.346）

### A.2 Camera noise10（旧 run 的方法对比无效，新 run 开始分化）

- baseline mean：old≈new≈0.106
- v2xregpp-best mean：old=0.107 → new=0.111（Δ=+0.004）
- freealign-best mean：old=0.107 → new=0.099（Δ=-0.008）
- vips-best mean：old=0.107 → new=0.070（Δ=-0.037）
- cbm-best mean：old=0.107 → new=0.053（Δ=-0.054）

（更完整的可复用数表见：`docs/operations/opv2v_fullbench_ap50_compare_old20260212_vs_new20260216_auto3.csv`，来源是两个 results JSON 的直接计算。）
