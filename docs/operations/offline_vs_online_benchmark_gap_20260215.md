# Offline vs Online Benchmark Gap (DAIR full-sweep vs OPV2V fullbench)

Last updated: 2026-02-15

目的：解释“离线 DAIR pose sweep/dropout（看起来合理）”与“OPV2V 全 GPU online/fullbench（看起来很不一样）”之间的差距，
并给出**证据链**定位当前 OPV2V online/fullbench 的评测基础问题，以及修复路线（止损优先）。

相关已有文档：
- 离线 plots 复盘（你点名的两组）：`docs/operations/pose_benchmark_plots_review_20260214.md`
- OPV2V fullbench 复盘（问题清单 + 根因）：`docs/operations/opv2v_fullbench_audit_20260214.md`
- OPV2V fullbench 证据报告（run_state + stage1 + applied）：`docs/operations/opv2v_fullbench_evidence_20260214.md`

---

## 1) 一句话结论

你看到的“online/fullbench 曲线不合理 / 跟离线差很多”主要不是算法突然退化，
而是 **OPV2V 的评测基础与离线口径不一致**，包含：

1) **选了错误/不可用的 perception checkpoint**（导致 camera AP≈0，即使 oracle 也≈0）；  
2) **camera stage1 cache 结构不满足多车 multi-agent matching**（导致 pose-correction applied=0，方法间曲线重合）；  
3) **LiDAR 使用了 no-extr（pose_override=zero）模型**，把 pose-noise sweep 抵消掉（baseline 曲线必然“平”）；  
4) 当前多数 run 实际还是 `offline_map` 路径，并非你要的“在线端到端 register_and_fuse”语义。

---

## 2) 离线（DAIR）为什么“看起来合理”

离线 DAIR full sweep（canonical）满足 3 个 sanity checks：

1) baseline 随噪声下降（noise 注入确实影响 detection/fusion）
2) oracle 水平且最高（GT 外参；eval 几何固定）
3) single 提供下界（comm=0；通常对噪声更不敏感）

对应产物（canonical）：
- `outputs/pose_sweep_1to10_full_plots/`
- `outputs/pose_dropout_1to10_full_plots/`

对应设置综述见：
- `HEAL/docs/pose_alignment_report_2026-02-05.md`
- `docs/operations/benchmark_inventory.md`（Section A）

---

## 3) OPV2V online/fullbench 为什么会“变化大到不合理”：三类硬问题

### 3.1 Camera AP≈0（即使 oracle 也≈0）=> 不是 pose/noise 问题，而是 perception 基座不可用

证据（YAML 数字）：
- `HEAL/opencood/logs/HeterBaseline_opv2v_camera_v2xvit_2026_01_17_21_49_18/AP030507_none_opv2v_fullbench_20260211_gpu_camera_noise10_baseline.yaml`
  - `ap50` 在 10 个噪声点都是 `~4e-07..6e-07`（≈0）

证据（log 输出保留两位小数，看起来全 0）：
- `outputs/full_bench_opv2v_fullbench_20260211_gpu/logs/camera_noise10_baseline.log:35`
  - “The Average Precision ... IOU 0.5 is 0.00”

含义：
- 这类 run 的曲线形状没有讨论意义（上游 perception 已经崩了），不能用于判断 online pose registration。

对照（可用的 camera 基座）：
- `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/AP030507_none_opv2v_fullbench_fast_20260212_camera_noise10_baseline_n1.0.yaml`
  - `ap50=[0.2077...]`（正常量级）

### 3.2 Camera pose-correction applied=0 => stage1 cache 不满足 multi-agent

证据（stage1 结构硬校验）：
- `data/OPV2V/detected/opv2v_camera_v2xvit_stage1/test/stage1_boxes.json`
  - samples=50（应为 2170）
  - 且每条样本 `len(cav_id_list)=2` 但 `len(pred_corner3d_np_list)=1`

这直接导致 stage1-based 的 solver（v2xregpp/freealign/vips/cbm）无法对 “ego<->cav” 成对求解。

证据（applied=0）：
- `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/AP030507_v2xregpp_initfree_opv2v_fullbench_fast_20260212_camera_noise10_v2xregpp_best_n1.0.yaml`
  - `timing_stats[0].pose_solver.applied == 0`

含义：
- online/fullbench 里 camera 的方法对比在当前 stage1 cache 下无效：所有 pose-correction 方法退化成“没应用修正”。

### 3.3 LiDAR baseline “平” => 你用了 no-extr 模型（pose_override=zero），噪声被覆盖

证据（模型 config 明确覆盖 pose）：
- `HEAL/opencood/logs/freealign_repro_opv2v_baseline_noextr_v2xregpp/config.yaml:37`
  - `pose_override.enabled=true, mode=zero`

含义：
- 这个设置适合 “calibration-free/no-extr” suite，但不适合 “pose-noise robustness sweep”。
- 在 pose-noise sweep 目标下，它会把噪声抵消掉，baseline 曲线必然“平”，这是语义不一致不是画图问题。

---

## 4) 你真正要的“全 GPU 在线端到端 benchmark”应该怎么定义（避免混语义）

建议明确两套 benchmark（不要混在一张图里）：

### A) Pose-noise robustness（外参可用但有噪声）
- baseline：使用 noisy pose（应随噪声下降）
- methods：在线/离线求解相对位姿并修正（应把曲线拉回）
- oracle：GT pose（水平上界）
- single：comm=0 下界

### B) Calibration-free / No-extr（外参不可用）
- 需要显式 `pose_override=zero/ego` 隐藏相对位姿
- 这时 “pose-noise sweep” 本身不再是核心轴（因为 pose 被你强制改写）

---

## 5) 修复/止损路线（按优先级）

1) **先把 OPV2V 的 perception 基座统一**（camera/lidar 都用“能出正常 AP”且不包含 `pose_override=zero` 的模型目录）。
2) **修复 OPV2V camera stage1 cache**：产出 2170 test samples 的 per-agent 预测，使：
   - `len(cav_id_list) == len(pred_corner3d_np_list)`
   - 每个 cav 都有 boxes（允许为空但必须对齐 list 长度）
3) **加硬 gate**（已经在 `tools/run_opv2v_fullbench_fast.py` 里做了）：
   - stage1 结构校验不过直接退出
   - `pose_override=zero` 在 pose-noise suite 下直接退出
   - 汇总时若 `pose_solver.applied` 全 0 直接标红/报错
4) **再做 online backend 的 A/B parity**：
   - 同一模型/同一 stage1/同一噪声点，比较 `offline_map` vs `online_box(register_and_fuse)` 是否一致（小样本即可）。

