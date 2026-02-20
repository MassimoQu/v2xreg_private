# OPV2V Fullbench Audit (2026-02-14)

结论先说：你看到的“曲线几乎全是平的 / baseline 也平”不是画图脚本的问题，而是**实验设置本身把 pose-noise 的影响抵消/绕开了**，以及 **camera 的 pose-correction 实际上完全没生效**，所以画出来必然“不符合直觉意义”。

本文件把证据链、根因、以及哪些设置在什么目标下是合理的梳理清楚，避免再用“跑完了但不可信”的结果做决策。

---

## 1) 现象复核（用数字说话）

### 1.1 LiDAR：baseline 几乎完全不随 noise 变化（所以看起来一条平线）

来自：`outputs/full_bench_opv2v_fullbench_fast_20260212/results_ap50_from_yaml.json`

- LiDAR baseline/noise10：AP50 范围约 `0.274674 -> 0.274414`（跨度 ~`2.6e-4`）
- LiDAR baseline/drop20：AP50 范围约 `0.274441 -> 0.274395`（跨度 ~`2.5e-4`）

这在“pose std 从 1 到 10”这种 sweep 下非常不合理（baseline 理应明显下降），因此需要追根因。

### 1.2 Camera：各个 pose-correction 方法曲线完全重合（几乎一模一样）

抽样证据（noise10, n=1.0）：

- `AP030507_v2xregpp_initfree_opv2v_fullbench_fast_20260212_camera_noise10_v2xregpp_best_n1.0.yaml`
- `AP030507_freealign_paper_opv2v_fullbench_fast_20260212_camera_noise10_freealign_best_n1.0.yaml`
- `AP030507_vips_initfree_opv2v_fullbench_fast_20260212_camera_noise10_vips_best_n1.0.yaml`
- `AP030507_cbm_initfree_opv2v_fullbench_fast_20260212_camera_noise10_cbm_best_n1.0.yaml`

它们的 `ap50` 完全相同（到小数点后很多位都一致），同时 YAML 的 `timing_stats[0].pose_solver.applied == 0`（见 §2.2）。

这说明：**camera 的“姿态校正器”压根没在任何 sample 上应用成功**，因此所有方法退化为同一个东西（自然重合）。

---

## 2) 根因（带代码路径/证据）

### 2.1 LiDAR baseline 为何会“平”：你用的是 no-extrinsics 的模型配置，且开启了 pose_override=zero

证据 1：LiDAR 模型配置里明确写了“覆盖 pose 为 zero”

`HEAL/opencood/logs/freealign_repro_opv2v_baseline_noextr_v2xregpp/config.yaml`：

```yaml
pose_override:
  enabled: true
  mode: zero
  apply_to: all
  set_confidence: 0.0
```

证据 2：数据管线里 noise 是先加、后被 pose_override 覆盖掉（等价于“无论 noise 多大，最终 pose 都一样”）

`HEAL/opencood/data_utils/datasets/intermediate_fusion_dataset.py`：

- `__getitem__` 先 `add_noise_data_dict(...)`（加噪）
- 然后如果 `pose_override_enabled`，会调用 `override_lidar_poses(...)` 把 `lidar_pose` 强制改写

对应实现：

- `HEAL/opencood/utils/pose_utils.py:add_noise_data_dict`（修改 `params['lidar_pose']`）
- `HEAL/opencood/utils/pose_utils.py:override_lidar_poses`（把 `params['lidar_pose']` 直接设为 `[0,0,0,0,0,0]`）

因此：在 baseline（`--pose-correction none`）下，**pose-noise sweep 被模型自身的 no-extrinsics 设定抵消**，曲线必然是平的。这种设置在“校准自由/无外参”实验里是合理的，但在“pose-noise 鲁棒性曲线”里不合理（目标与设置不一致）。

### 2.2 Camera pose-correction 为何全部失效：stage1 cache 结构不支持 multi-agent box matching

证据 1：camera 的 stage1 cache 只有 50 个 sample，且每个 sample 的 `pred_corner3d_np_list` 只有 1 个 agent 的预测

`data/OPV2V/detected/opv2v_camera_v2xvit_stage1/test/stage1_boxes.json`（统计）：

- 样本数：`50`
- `cav_id_list` 长度：`2`（两车）
- `pred_corner3d_np_list` 长度：`1`
- 50/50 样本存在 `len(cav_id_list) != len(pred_corner3d_np_list)` 的结构性 mismatch

而 LiDAR stage1 cache（对照）：

`data/OPV2V/detected/opv2v_lidar_v2xvit_stage1/test/stage1_boxes.json`

- 样本数：`2170`
- `len(cav_id_list)` 与 `len(pred_corner3d_np_list)` 在所有样本都匹配（2~5 个 agent）

证据 2：camera 的 pose solver 在所有样本上 applied=0（从 YAML timing_stats 可直接读到）

例如：

`HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/AP030507_v2xregpp_initfree_opv2v_fullbench_fast_20260212_camera_noise10_v2xregpp_best_n1.0.yaml`

- `timing_stats[0].pose_solver.applied == 0`

原因链：

- stage1-based 方法（v2xregpp/freealign/vips/cbm）需要“ego + cav”两边的 boxes 才能估计相对位姿；
- 但 camera stage1 里只有 1 份 boxes（对应 agent_idx=0），agent_idx=1 取 boxes 会得到空列表；
- 正常逻辑下就永远算不出 `rel_T_est`，因此 `apply()` 永远不更新任何 pose，最终 applied=0。

这不是“算法本身不行”，而是**stage1 cache 的输出形态与算法需求不匹配**（multi-agent box list 缺失）。

补充：为什么 DAIR camera 可以做这件事、而 OPV2V camera 不行？

- `pose_graph_pre_calc.py` 的 `--per_agent` 模式是专门为 DAIR 那种“车+路侧两 agent”设计的，可以分别导出两边的 single-agent boxes 后再 merge。
- OPV2V 是多车场景（2~5 个 agent），当前 repo 没有通用的 multi-agent per-CAV stage1 exporter，所以用默认 export 得到的是“只含 1 份输出”的 cache。

---

## 3) 哪些设置“合理”、哪些在当前目标下“不合理”

### 合理（但要写清楚实验目标）

- `pose_override: mode=zero/ego`：用于 **no-extrinsics / calibration-free** 场景，强制隐藏相对位姿，让校正器去恢复。
- `comm_range_use_clean_pose: true`：用于让 comm-range pruning 不被 noise 扰动，避免“邻居进出范围”混入曲线（做公平对比时通常是好事）。
- oracle 曲线平：oracle 用 GT pose，本来就应当与 noise 无关（正确现象）。

### 在你“pose-noise 鲁棒性曲线”的目标下不合理 / 需要拆开

- LiDAR 选用 `*_noextr_*` 模型 + `pose_override=zero` 去做 noise sweep：噪声被覆盖掉，曲线失去意义。
- Camera 继续用“只含 1 份输出”的 stage1 cache 去跑 stage1-based pose correction：校正器永远不生效，方法间对比失去意义。

---

## 4) 建议的止损与修复路线（按优先级）

1) **先明确你要的 benchmark 是哪一种：**
   - A) pose-noise robustness（外参可用但有噪声，baseline 会随噪声掉）
   - B) calibration-free/no-extr（外参不可用，baseline 不该用 noise sweep）

2) 若选 A（更符合你刚才对“baseline 应该掉”的直觉）：
   - LiDAR：换用“不启用 pose_override=zero 的模型目录”（例如 `HEAL/opencood/logs/HeterBaseline_opv2v_lidar_v2xvit_calibfree_2026_01_22_00_20_19`），或显式禁用 pose_override 后重跑。
   - Camera：需要实现一个 **multi-agent per-CAV stage1 exporter**（输出 `pred_corner3d_np_list` 长度与 `cav_id_list` 对齐，且覆盖 2170 个 test sample），否则 v2xregpp/freealign/vips/cbm 在 camera 上无法做公平对比。

3) 若选 B（no-extr）：
   - 不做 pose-noise sweep（或把 x 轴改成“检测质量/匹配阈值/遮挡比例”等真正影响校正器的变量）。
   - baseline 平是合理的，但要在图标题/文档里明确“no-extr”语义，避免误读。

4) 增加硬性校验（防止再浪费算力）：
   - 在调度器启动前校验 stage1 cache：样本数、key 连续性、`len(cav_id_list)==len(pred_corner3d_np_list)`。
   - 在汇总时输出 `pose_solver.applied` 统计；camera 出现全 0 直接标红/报错。

---

## 5) 当前 run（opv2v_fullbench_fast_20260212）的结论标签

这个 run 的产物（`plots_yaml/`）可以留作“日志/管线完整性证明”，但**不应作为你要的‘pose-noise 公平 benchmark 曲线’的最终结论**，因为：

- LiDAR baseline 属于 no-extr 语义，noise sweep 对它无意义；
- Camera 的 pose-correction 方法全都没生效（applied=0），方法对比无意义。

