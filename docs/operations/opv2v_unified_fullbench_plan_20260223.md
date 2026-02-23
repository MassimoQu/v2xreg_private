# OPV2V Unified Fullbench Plan + Preflight (2026-02-23)

本文件把“全矩阵（有初值/无初值/HKUST）+ 下游协同感知 AP + 配准指标”的 OPV2V 部分，落成一个可执行合同（plan contract），并记录 preflight gate 证据。

---

## 结论

- **ALLOW（先 smoke，再 full）**：已具备启动统一条件 smoke 的所有输入；但 full run 必须在 **git clean** 状态下启动。

---

## P0 阻塞项（Full run 之前必须修）

1) **Git dirty / 混用风险**
- smoke run 允许 dirty；但 fullbench 作为 canonical numbers 必须保证：
  - 主仓 `git_dirty=false`
  - HEAL 子模块 `heal_dirty=false`
  - submodule 指针已提交（主仓不再显示 `M HEAL`）
- 证据：smoke 的 `config_snapshot.json` 里当前 `git_dirty=true`：
  - `outputs/full_bench_opv2v_unified_smoke_20260223_fix1/config_snapshot.json`

2) **Comm-range gating 语义必须冻结**
- 已在调度器补齐 `--comm-range-gating` 并写入快照；full run 必须显式指定。
- 证据：`tools/run_opv2v_fullbench_fast.py` 已支持并写入 `comm_range_gating`。

---

## Gate 表（plan-preflight）

G0 Goal/Decision: PASS
- 决策：在统一条件下比较 with-init/no-init/HKUST 方法在 OPV2V 的 AP+配准曲线，确认真实增益与排序。

G1 DoD: PASS
- DoD 产物（full run）：run_dir + `config_snapshot.json` + `run_state.jsonl` + `results_ap50_from_yaml.json`
  + `outputs/benchmark_fullmatrix_*/combined_noise_curve_long.csv` + `plots/`。

G2 Semantics Freeze: PASS (smoke) / P0 (full)
- PASS：调度器已支持显式冻结：
  - `solver_backend=online_box`
  - `runtime_mode=register_and_fuse`
  - `pose_source=noisy_input`
  - `comm_range_gating={clean|noisy}`
- P0：full run 需要在 git clean 下启动，避免语义漂移不可复原。

G3 Input Contract: PASS
- dataset：`dataset/OPV2V/test`（len=2170）
- stage1 cache（仅对 v2xregpp/freealign/vips/cbm 需要；本 smoke 不需要，但路径已固定）：
  - `data/OPV2V/detected/opv2v_camera_v2xvit_stage1_percav/test/stage1_boxes.json`
  - `data/OPV2V/detected/opv2v_lidar_v2xvit_stage1/test/stage1_boxes.json`
- model dirs：
  - camera：`HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope`
  - lidar：`HEAL/opencood/logs/freealign_repro_opv2v_baseline`

G4 Smoke/Toolchain: PASS (in progress)
- smoke run 已启动（见下）。

G5 Confound/Cancellation: PASS (new mitigation landed)
- 风险：online runtime 下 `comm_range_use_clean_pose` 的隐式切换会造成 cross-method confound。
- 缓解：fullbench 调度器新增 `--comm-range-gating` 并写入快照（避免 baseline vs method 不同语义）。

G6 Effectiveness: PASS (local micro-verify)
- imagematch 路径已验证“可以 apply”（放松门限时 `pose_provider_applied_count=1.0`），说明 online payload wiring 生效；
  但默认安全门限下大概率被拒绝（`applied_count=0`），属于算法能力问题而非 wiring bug。

G7 Source-of-Truth: PASS
- completion：`run_state.jsonl`
- metrics：模型目录 `AP030507_*.yaml` + 聚合 `results_ap50_from_yaml.json`

G8 Resume/Re-run Safety: PASS
- `run_state.jsonl` + overwrite/append 可控；full run 建议使用新 run_id，避免混写。

G9 Smoke-First: PASS
- 已启动 smoke（见下）。

G10 Cost/Stop-loss: PARTIAL
- 本轮先 smoke（`max_eval_samples=20`）验证机制；full run 再评估预算。

---

## Smoke Run（已启动）

Run dir（source of truth）：
- `outputs/full_bench_opv2v_unified_smoke_20260223_fix1/`

合同快照：
- `outputs/full_bench_opv2v_unified_smoke_20260223_fix1/config_snapshot.json`

当前 smoke scope：
- modality：camera + lidar
- sweep：noise10
- noise：pos=rot=1.0
- methods：`imagematch_{noinit,current}`（camera-only）、`lidarreg_ransac`（lidar-only）、`hkust_teaser`（lidar-only）
- bounds：baseline + oracle
- comm_range_gating：`noisy`
- max_eval_samples：20

---

## Full Run（待 smoke 通过后启动）

建议 full run run_id 命名：
- `opv2v_unified_full_20260223_<tag>`

建议 methods（按你的诉求覆盖全矩阵）：
- bounds：baseline/oracle/single
- no-init（object-level / stage1）：v2xregpp/freealign/vips/cbm
- with-init：vips_prior/cbm_prior/imagematch_current
- no-init（image/raw）：imagematch_noinit
- no-init（lidar/global/HKUST）：lidarreg_ransac/hkust_teaser/hkust_fgr/hkust_quatro

输出汇总链路：
- `tools/summarize_opv2v_fullbench_from_yaml.py --run-dir <run_dir> --allow-incomplete`
- `tools/build_fullmatrix_benchmark_report.py`
- `tools/build_unified_benchmark_report.py`

