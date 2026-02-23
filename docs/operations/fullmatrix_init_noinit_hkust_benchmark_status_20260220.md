# Full-Matrix 基准对齐与扩展执行状态（2026-02-20）

更新时间：2026-02-21

## 1) 本轮你提出的核心诉求（落地口径）

你要的不是“再给一版摘要”，而是两件都要同时完成：

1. 把仓库里分散 benchmark / config / docs 统一成**可追溯主文档**；
2. 以“无初值协同感知 AP 图”的统一标准，把**有初值 vs 无初值**方法在
   - DAIR / OPV2V
   - camera / lidar
   - AP 与配准（rel_trans / rel_yaw）
   做同口径大对比，并补齐之前没和下游协同感知拼跑的线（特别是 HKUST 相关）。

---

## 2) 本轮已新增的代码能力（为你这件事服务）

### 2.1 OPV2V 调度矩阵扩展（可直接补跑）
- 文件：`tools/run_opv2v_fullbench_fast.py`
- 新增 method 族：
  - 有初值：`vips_prior`, `cbm_prior`, `imagematch_current`
  - 无初值：`imagematch_noinit`, `lidarreg_ransac`
  - HKUST 对齐线：`hkust_teaser`, `hkust_fgr`, `hkust_quatro`
- 同时加了按模态筛选（例如 image-match 只跑 camera，HKUST 线只跑 lidar）。

### 2.2 LiDAR 注册后端扩展（支持 HKUST 三线）
- 文件：`HEAL/opencood/extrinsics/late_fusion/lidar_registration.py`
- 新增 `global_method`：
  - `ransac`, `fgr`, `teaser_gnctls`, `teaser_fgr`, `teaser_quatro`
- 新增 TEASER++ 路径（特征互检匹配 + solver + ICP refine）。

### 2.3 推理入口参数扩展
- 文件：`HEAL/opencood/tools/inference_w_noise.py`
- 新增参数：
  - `--lidar-reg-global-method`
  - `--lidar-reg-teaser-noise-bound`
  - `--lidar-reg-teaser-max-correspondences`

---

## 3) 统一对比产物（当前可用）

### 3.1 已生成的“全矩阵长表 + 图”
- 目录：`outputs/benchmark_fullmatrix_20260220/`
- 文件：
  - `outputs/benchmark_fullmatrix_20260220/combined_noise_curve_long.csv`
  - `outputs/benchmark_fullmatrix_20260220/method_registry.csv`
  - `outputs/benchmark_fullmatrix_20260220/summary.json`
  - `outputs/benchmark_fullmatrix_20260220/plots/*.png`

该批图已经按“无初值 AP 曲线”风格统一：
- 颜色：方法族（family）
- 线型：best/stable/bounds
- marker：init class（with_init / no_init / hkust / bound）

生成脚本：
- `tools/build_fullmatrix_benchmark_report.py`

### 3.2 目前 registry 覆盖（运行前快照）
- `rows_registry=68`，`valid_lines=68`
- OPV2V 当前仍是旧 13 条方法线（`v2xregpp/freealign/vips/cbm + bounds + single + camera-occhint`）
- 新扩展方法线尚未写入最终结果（见第 4 节执行状态）。

---

## 4) 你点名“没拼下游协同感知”的补跑：执行状态

### 4.1 已启动的扩展补跑（同 run_id 追加）
- 目标 run：`outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/`
- 追加 methods：
  - `vips_prior, cbm_prior, imagematch_noinit, imagematch_current, lidarreg_ransac, hkust_teaser, hkust_fgr, hkust_quatro`
- 计划总任务：`400`

### 4.2 当前进度快照（写本文档时）
- 以 `run_state.jsonl` 为准（source of truth）：
  - `camera append started = 158`
  - `camera append ended = 128`
  - `camera append failed = 0`
  - `camera append pending = 30`
  - ended by sweep:
    - `noise10 = 80`（4 methods × 10 noises × 2 strategies）
    - `drop20 = 48`（目前完成 noise=1..6，共 4 methods × 6 noises × 2 strategies）
- 当前已完成：
  - camera/noise10：`vips_prior, cbm_prior, imagematch_noinit, imagematch_current`（best+stable，noise=1..10 全完成）
  - camera/drop20：同上 4 条 method，best+stable 已完成 noise=1..6，剩余 noise=7..10 仍在跑
- HKUST lidar 线（`lidarreg_ransac, hkust_*`）尚未开始（队列后段）。

说明：
- 这批是 full 条件（非 smoke），单任务耗时较长，属于长跑任务。
- 跑完后会自动落到现有 canonical run 目录，统一汇总不再分叉 run id。

---

## 5) 后续自动汇总链路（跑完即可一键出最终对比）

1. OPV2V 追加跑完后：
   - `tools/summarize_opv2v_fullbench_from_yaml.py`（若需要刷新）
2. 生成全矩阵长表+图：
   - `tools/build_fullmatrix_benchmark_report.py`
3. 统一主报告（含 DAIR+OPV2V+Table3）刷新：
   - `tools/build_unified_benchmark_report.py`

---

## 6) DAIR 扩展线（有初值/HKUST 与下游 AP 拼跑）

目前 DAIR 的 canonical 仍是既有主线（baseline/oracle/v2xregpp/freealign/vips/cbm）。
下一步将在同 noise10 条件下补齐：
- `vips_prior`, `cbm_prior`
- HKUST 对齐线（与 OPV2V 对齐命名）

补齐后会并入同一 `build_fullmatrix_benchmark_report.py` 输出口径，保证 DAIR/OPV2V 同图可比。

---

## 7) Subagent 说明

按你的要求尝试了 subagent 并行编排，但当前环境下子代理被 Landlock 限制阻断（无法读仓库）。
因此本轮改为主代理直接并行推进：代码扩展 + 长跑任务启动 + 统一报告脚本落地。

---

## Update（2026-02-23）

### 当前队列（OPV2V append）在跑什么

正在运行的 append 调度进程（本机）：
- `tools/run_opv2v_fullbench_fast.py`（run_id=`opv2v_autopilot_full_20260216_auto3_a1`，methods=`vips_prior/cbm_prior/imagematch_*/lidarreg_ransac/hkust_*`）

以 `outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/run_state.jsonl` 为准，
当前 append scope（400 tasks）状态为：
- done_in_scope=187
- in_progress=30
- pending=183

补充：append 的 camera 4 条方法线（`vips_prior/cbm_prior/imagematch_{noinit,current}`）已全部跑完（noise10+drop20，n=1..10，best+stable）。

### 重要风险：mid-run 代码修复导致“同一 run_id 下混版本”

在 append 长跑过程中，HEAL 子模块新增/修复了：
- online runtime 的 imagematch payload（camera_data/intrinsic/extrinsic 注入）
- online runtime 的 lidar_reg per-CAV raw LiDAR payload（`lidar_np_by_cav` 导出）
- lidar_reg 的相对位姿方向（T）修复
- （2026-02-24）进一步修复：将 `lidar_np_by_cav` 导出语义从 `visualize` 解耦，
  当 `pose_provider.enabled && online_method==lidar_reg` 时即使 `visualize=False` 也会导出，
  避免某些脚本（如 `inference.py`/`eval_calibfree_align.py`）在默认 `visualize=False` 下 silent no-op。

因此：
- append 中早期开跑/已完成的 imagematch 与部分 lidar_reg/hkust 任务属于“旧代码版本结果”，不应直接并入最终 fullmatrix 结论；
- 需要在 **git clean + 统一 comm-range gating** 的条件下重新启动一版 unified run（见下一条）。

补充证据（why “旧版本结果”可能是退化的）：
- camera/imagematch：在统一条件 smoke/remote audit 下，`image_match_initfree` 常见 `pose_provider_applied_count=0.0`，
  AP 与 baseline 完全一致（等价 no-op）。见：
  - `docs/operations/imagematch_initfree_remote_audit_20260223.md`
  - `outputs/full_bench_opv2v_unified_smoke_20260223_fix1/`
- lidarreg/hkust：append 早期已完成的点上，`hkust_teaser` 与 `lidarreg_ransac` 可以出现 **AP/配准指标完全一致**，
  且 `match_sec` 极小（典型 no-op / payload 未就绪特征）。例如（同一个点 n=1.0）：
  - `HEAL/opencood/logs/freealign_repro_opv2v_baseline/AP030507_lidar_reg_initfree_opv2v_autopilot_full_20260216_auto3_a1_lidar_noise10_lidarreg_ransac_best_n1.0.yaml`
  - `HEAL/opencood/logs/freealign_repro_opv2v_baseline/AP030507_lidar_reg_initfree_opv2v_autopilot_full_20260216_auto3_a1_lidar_noise10_hkust_teaser_best_n1.0.yaml`
  其中一种常见成因是：运行时 batch 未携带 per-CAV raw points（`lidar_np_by_cav`），
  导致 online `lidar_reg` corrector 无法组装 `base_data_dict[*].lidar_np` 而直接返回不 apply。

### 新的统一合同与 smoke

已落地的统一条件调度能力：
- `tools/run_opv2v_fullbench_fast.py` 新增 `--comm-range-gating` 并在 `config_snapshot.json` 写入 git/heal commit。

已启动 smoke（用于验证机制与产物链路）：
- `outputs/full_bench_opv2v_unified_smoke_20260223_fix1/`
- 合同与 preflight 记录：`docs/operations/opv2v_unified_fullbench_plan_20260223.md`
