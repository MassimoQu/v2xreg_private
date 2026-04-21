# OPV2V Camera: V2X-Reg++ occ-hint Ablation (online, no-init)

Last updated: 2026-02-19

目标（写论文用的一句话）：
- 在 **OPV2V camera** 的 **online end-to-end（`solver_backend=online_box`, `runtime_mode=register_and_fuse`）** 语义下，
  评估 **V2X-Reg++ 的 occ-hint（中融合增强/occupancy hint seed）** 是否能改善/稳定无初值配准曲线，
  并把它加入到已有 camera benchmark 曲线对比里。

---

## 0) 输入/语义冻结（必须保持不变）

- perception 基座（camera）：
  - model dir: `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope`
  - ckpt: `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/net_epoch_bestval_at21.pth`
- 语义（与主结果 auto3 对齐）：
  - `--solver-backend online_box`
  - `--runtime-mode register_and_fuse`
  - `--pose-source noisy_input`
  - `--noise-target non-ego`
  - noise axis: `pos_std=rot_std=1..10`（paired）
- stage1 cache（必须 multi-agent per-CAV）：
  - baseline（旧）：`data/OPV2V/detected/opv2v_camera_v2xvit_stage1_percav/test/stage1_boxes.json`
  - occhint 需要新增字段：
    - `occ_map_level0_path`（每个 sample 里与 `cav_id_list` 对齐的 `.npz` path 列表）

---

## 1) 代码改动（必要条件）

1) per-CAV stage1 exporter 支持导出 occ map（并且**即使没有 box 也导出**）：
   - `HEAL/opencood/tools/export_stage1_boxes_per_cav.py`
   - flags:
     - `--dump_occ_map_path`（推荐；写 `occ_map_level0_path` + `.npz`）
     - `--dump_occ_map`（不推荐；inline 写进 JSON 会爆炸）

2) fullbench 调度器新增方法键（用于画新曲线）：
   - `tools/run_opv2v_fullbench_fast.py`
   - 新方法：`v2xregpp_occhint`（= `v2xregpp_*` + `--v2xregpp-use-occ-hint`）

3) 汇总/画图脚本放宽 method name，支持 `v2xregpp_occhint`：
   - `tools/summarize_opv2v_fullbench_from_yaml.py`
   - `tools/plot_opv2v_dual_suite_from_yaml.py`

---

## 2) Smoke evidence（100 samples, n=1.0）

### 2.1 先验：occ stage1 cache 能正确生成

- stage1（100 samples, 含 occ paths）：
  - `data/OPV2V/detected/opv2v_camera_v2xvit_stage1_percav_occ_100/test/stage1_boxes.json`
  - 校验通过：
    - `./.micromamba/envs/py39/bin/python tools/validate_stage1_cache.py --stage1 ... --expected-samples 100 --require-contiguous-keys`

### 2.2 在线端到端 smoke（n=1.0, max_eval_samples=100）

对应 YAML（source of truth）：
- baseline：
  - `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/AP030507_none_opv2v_camera_baseline_smoke100_n1.yaml`
- v2xregpp（无 hint）：
  - `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/AP030507_v2xregpp_initfree_opv2v_camera_v2xregpp_smoke100_n1.yaml`
- v2xregpp + occ-hint：
  - `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/AP030507_v2xregpp_initfree_opv2v_camera_occhint_smoke100_n1.yaml`
- v2xregpp + occ-pose（对照，当前看起来更差）：
  - `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/AP030507_v2xregpp_initfree_opv2v_camera_occpose_smoke100_n1.yaml`

读取到的 AP50（单点，非最终结论）：

| line | AP50 |
| --- | --- |
| baseline | 0.1867 |
| v2xregpp (initfree) | 0.1716 |
| v2xregpp + occ-hint | 0.1814 |
| v2xregpp + occ-pose | 0.1534 |

对应的相对位姿误差（同一 smoke 点，来自 YAML `rel_error_stats` 的 `mean`）：

| line | rel_trans_m.mean | rel_yaw_deg.mean |
| --- | --- | --- |
| baseline | 1.38 | 0.67 |
| v2xregpp (initfree) | 7.51 | 4.32 |
| v2xregpp + occ-hint | 4.73 | 1.14 |
| v2xregpp + occ-pose | 30.48 | 38.08 |

解读（仅对 smoke 有效）：
- camera 上 **v2xregpp 本身可能伤害** baseline（符合你之前对 online camera 的观察）。
- **occ-hint 有“把伤害拉回一些”的趋势**：不仅 AP50 从 0.1716 -> 0.1814 回升，同时相对位姿误差从 `7.51m/4.32deg` 降到 `4.73m/1.14deg`。
- occ-pose 在当前实现/设置下更差（先不纳入主线）。

---

## 3) 下一步（full）

1) 导出 OPV2V camera 全量 occ stage1（2170 test samples）：
   - `data/OPV2V/detected/opv2v_camera_v2xvit_stage1_percav_occ_full/test/stage1_boxes.json`
   - 并 merge 到 baseline stage1：`data/OPV2V/detected/opv2v_camera_v2xvit_stage1_percav_occ_merged/test/stage1_boxes.json`

2) **最小代价**把 occhint 曲线加到“已有 camera benchmark”里（不重跑 auto3 全套）：
   - 直接在 **auto3 的同一 run_id** 上追加 occhint 任务（避免 cross-run 合并的口径风险）
   - launcher（等 DAIR sweep 完成后自动跑）：
     - `outputs/launch_occhint_append_auto3_after_dair_20260219.sh`
   - 产物位置：
     - 新增日志：`outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/logs/*v2xregpp_occhint*.log`
     - 新增 YAML：`HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/AP030507_*_opv2v_autopilot_full_20260216_auto3_a1_camera_*v2xregpp_occhint*.yaml`
     - 更新 plots：`outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/plots_yaml/noise10_camera_ap50.png`（以及 drop20/camera 等）

3) 汇总/验收（“是否真的生效”）：
   - 要看 **AP 曲线** + `pose_solver.applied` 是否显著 >0（不能 silent no-op）
   - 若 occhint 只在高噪声段改善或只改善 rel_error_stats，也要在文档里明确。
