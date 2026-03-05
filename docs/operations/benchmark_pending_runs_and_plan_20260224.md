# 待跑实验清单 + 执行合同（2026-02-24）

本文件回答你问的两件事：

1) “我接下来到底要跑什么实验？”（把全矩阵补齐、把条件统一、把结果做成可复核产物）  
2) “现在还有什么待跑？”（按 P0/P1 阻塞与依赖顺序列出来，并给出 DoD/验收标准）

它不是重复叙述，而是把执行计划落成**可执行合同**（plan contract），避免再出现“跑了很多但 benchmark 对不上/混版本/no-op”的情况。

关联文档入口：
- OPV2V unified fullbench 合同与 smoke：`docs/operations/opv2v_unified_fullbench_plan_20260223.md`
- LiDAR lidar_reg/hkust no-op 根因：`docs/operations/lidarreg_noop_root_cause_and_rerun_20260224.md`
- 配准指标 ↔ AP 映射与漂移解释：`docs/operations/pose_error_to_ap_mapping_report_20260224.md`

---

## 结论

- **BLOCK（不允许直接启动 canonical fullbench）**：在 OPV2V 上要把 init/no-init/HKUST 全部跑成最终可引用结果，
  仍需先完成 LiDAR 注册 cache 预计算（否则成本不可控），并用全新 unified run_id 重跑（旧 run_id 混版本/不完整）。

---

## P0 阻塞项（必须先做）

### P0-1) OPV2V unified fullbench 必须用全新 run_id（旧 run_id 不可作为最终来源）

证据链：
- 旧 run：`outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1/run_state.jsonl`
  - `start=668`，`end=638`（仍有 30 条 start 无 end，说明 run 不完整）
  - 同 run_id 内存在 mixed-env + mid-run 修复混写（见 `docs/operations/opv2v_append_partial_results_20260222.md`）

Implication：
- 旧 run_id 只能作为“历史现象”，不能作为 fullmatrix 最终 numbers 的 source-of-truth。

### P0-2) LiDAR lidar_reg/HKUST：必须先做 cache（否则 fullbench 会被 CPU 注册拖死）

原因：
- HKUST/全局点云注册属于 CPU 重活；fullbench 会重复计算同一对点云 40 次以上（10 noises × 2 sweeps × 2 strategies）。
- 正确姿势：只算一次 per-(sample_idx, ego_id, cav_id) 的相对变换，存成 JSON cache，fullbench 时复用。

脚本与 cache 合同：
- 预计算脚本：`tools/precompute_opv2v_lidar_reg_cache.py`
- cache 目录：`data/OPV2V/lidar_reg_cache/`
- 期望文件名：`opv2v_test_<global_method>.json`

补充（非常关键）：
- 当前仓库里已经存在的 `opv2v_test_*.json` 可能只是 smoke/partial（例如 `meta.max_samples=5/20`），并不覆盖全 test split。
- 从 2026-02-24 起，`tools/run_opv2v_fullbench_fast.py --require-lidar-reg-cache` 在 **full eval**（`--max-eval-samples 0`）下会拒绝
  `meta.max_samples!=0` 的 cache，避免“部分样本走 cache、其余样本回退在线计算”的隐性混跑。

### P0-3) 所有“需要 apply pose update”的方法线：必须强制有效性 gate

DoD / 验收：
- 对每条方法线抽查 YAML（或汇总 CSV）必须满足：`pose_provider_applied_count > 0`
- 如果 `pose_provider_applied_count == 0`：该线等价 baseline，必须标 invalid（不进入对比/拟合/画图）

相关根因与修复：
- `docs/operations/imagematch_initfree_remote_audit_20260223.md`
- `docs/operations/lidarreg_noop_root_cause_and_rerun_20260224.md`

---

## Gate 表（Plan-Preflight）

本表是为了防止“跑出来但不可复现/不可比”的灾难性返工。

- G0 Goal/Decision：PASS  
  目标决策：在 **同一 benchmark 合同** 下，给出 DAIR/OPV2V、camera/lidar、init/no-init/HKUST 的统一大对比，
  同时产出 AP 曲线与配准曲线，并明确哪些线无效（no-op/合同漂移）而被剔除。

- G1 DoD：PASS  
  Done 的定义不是“脚本跑完”，而是产出以下不可变证据链：
  - run_dir：`outputs/<run_id>/config_snapshot.json` + `run_state.jsonl` + `results_ap50_from_yaml.json`
  - 模型目录：`HEAL/opencood/logs/**/AP030507_*.yaml`（含 AP + rel_error_stats + timing_stats）
  - 聚合：`outputs/benchmark_fullmatrix_<date>/combined_noise_curve_long.csv` + `plots/`
  - 映射报告：`outputs/pose_error_to_ap_mapping_report_<date>/mapping_summary.json` + `plots/`

- G2 Semantics Freeze：P0（full） / PASS（smoke 已验证）  
  fullbench 必须显式冻结：`solver_backend/runtime_mode/pose_source/comm_range_gating`，并写入快照。

- G3 Input Contract：PARTIAL  
  stage1 cache / model dirs 已知，但 LiDAR cache 仍待生成（P0-2）。

- G4 Smoke-First：PASS  
  OPV2V unified smoke 已完成并通过关键链路：
  `outputs/full_bench_opv2v_unified_smoke_20260223_fix1/`

- G5 Confound/Cancellation：PASS（已加 mitigations）  
  `--comm-range-gating` + `pose_provider_applied_count` gate。

- G6 Effectiveness：PASS（机制已验证） / P0（全量仍需强制抽检）  
  LiDAR online payload 已修复导出；fullbench 必须持续抽检避免回退。

- G7 Source-of-Truth：PASS  
  completion：`run_state.jsonl`  
  metrics：`AP030507_*.yaml` + `results_ap50_from_yaml.json`

- G8 Resume/Re-run Safety：PASS  
  run_id 采用新目录；旧结果保留为历史。

- G9 Smoke-First：PASS  
  已执行。

- G10 Cost/Stop-Loss：P0  
  HKUST cache 未完成前不允许开 fullbench（成本不可控）。

---

## 待跑实验（按依赖顺序）

### A) OPV2V：LiDAR 注册 cache 全量预计算（必须先做）

目标：
- 生成以下 cache（按你要跑的方法覆盖）：
  - `opv2v_test_ransac.json`
  - `opv2v_test_teaser_gnctls.json`
  - `opv2v_test_teaser_fgr.json`
  - `opv2v_test_teaser_quatro.json`
  - （可选）`opv2v_test_fgr.json`（如果你还要跑纯 FGR 线）

推荐执行方式（长跑必须用 tmux；不要用 `nohup ... &`）：
- 说明：本 Codex harness 会回收后台子进程，`nohup`/`&` 不能稳定保活；`tmux` 才是可靠后台。

分片并行预计算（示例：16 shards，按 global_method 各跑一轮）：

```bash
# 以 teaser_gnctls 为例（全量：--max-samples 0）
N=16
GM=teaser_gnctls
for SID in $(seq 0 $((N-1))); do
  tmux new -d -s cache_${GM}_${SID} "bash -lc 'PYTHONPATH=$PWD/HEAL .micromamba/envs/v2x/bin/python tools/precompute_opv2v_lidar_reg_cache.py --global-method ${GM} --max-samples 0 --save-every 50 --resume --num-shards ${N} --shard-id ${SID} |& tee outputs/cache_${GM}_shard${SID}of${N}.log'"
done
```

合并分片：
```bash
.micromamba/envs/v2x/bin/python tools/merge_opv2v_lidar_reg_cache_shards.py \
  --in-dir data/OPV2V/lidar_reg_cache/shards \
  --pattern "opv2v_test_${GM}_shard*of${N}.json" \
  --out data/OPV2V/lidar_reg_cache/opv2v_test_${GM}.json
```

验收（最小）：
- cache 文件存在且 `pairs` 非空；
- 任取若干 key，值要么是 `null`（失败），要么包含 `T(4x4)+fitness+inlier_rmse`；
- fullbench 启动时加 `--require-lidar-reg-cache`，缺 cache 直接 fail-fast。

### B) OPV2V：unified fullbench（canonical run）

目标：
- 在 **同合同** 下跑出全矩阵（init/no-init/HKUST + bounds），并生成可引用 plots/CSV。

推荐 run_id（示例）：
- `opv2v_unified_full_20260224_r1`

启动命令（示例；按你机器 GPU 资源调整 `--gpus/--max-per-gpu/--num-workers`）：

```bash
tmux new -d -s opv2v_unified_full_20260224_r1 "bash -lc '\
.micromamba/envs/v2x/bin/python tools/run_opv2v_fullbench_fast.py \
  --run-id opv2v_unified_full_20260224_r1 \
  --modalities camera,lidar \
  --sweeps noise10,drop20 \
  --noise-list 1,2,3,4,5,6,7,8,9,10 \
  --rot-list 1,2,3,4,5,6,7,8,9,10 \
  --solver-backend online_box --runtime-mode register_and_fuse --pose-source noisy_input \
  --comm-range-gating noisy \
  --require-clean-git \
  --lidar-reg-cache-dir data/OPV2V/lidar_reg_cache --require-lidar-reg-cache \
  --methods v2xregpp,freealign,vips,cbm,vips_prior,cbm_prior,imagematch_noinit,imagematch_current,lidarreg_ransac,hkust_teaser,hkust_fgr,hkust_quatro \
  --max-eval-samples 0 \
  |& tee outputs/opv2v_unified_full_20260224_r1.launch.log'"
```

验收：
- `outputs/full_bench_opv2v_unified_full_20260224_r1/run_state.jsonl`：所有 `start` 都有 `end(code=0)`
- `config_snapshot.json`：`git_dirty=false` + 记录 heal commit + `comm_range_gating=noisy`
- 抽查若干方法线 YAML：必须有 `pose_provider_applied_count>0`（除非明确该线允许 no-op 并被标 invalid）

补充（2026-02-24）：
- `tools/run_opv2v_fullbench_fast.py` 的 preflight 现在会在 `solver_backend!=offline_map` 且 `comm_range_gating=auto` 时直接 fail-fast，
  以避免 baseline vs method 发生 gating 语义漂移的 cross-method confound。

### C) DAIR：补齐“with-init/HKUST + 下游 AP”同口径矩阵（如果你要 DAIR 也 fullmatrix）

现状：
- DAIR canonical 目前覆盖 core methods（baseline/oracle/v2xregpp/freealign/vips/cbm），证据在
  `outputs/pose_sweep_1to10_full_gpuvoxel20260218_results.jsonl`。

待补跑（建议先做小规模 smoke，再全量 noise10）：
- with-init：`vips_prior`, `cbm_prior`, `imagematch_current`（若 camera 线仍要）
- hkust/lidar_reg：与 OPV2V 对齐命名的 global 方法线（至少 teaser_gnctls / teaser_fgr / teaser_quatro）

DoD：
- 把新增 DAIR 结果并入同一套 long.csv 输出口径，能在 fullmatrix plots 里同图对比。

---

## 统一汇总与出图（fullbench 跑完后做）

1) 汇总 OPV2V run_dir（从 YAML 落到 JSON）：
- `tools/summarize_opv2v_fullbench_from_yaml.py --run-dir outputs/full_bench_<run_id>/`

2) 生成全矩阵长表 + “无初值 AP 标准”风格图：
- `tools/build_fullmatrix_benchmark_report.py`

3) 生成 DAIR+OPV2V 的 unified 主报告：
- `tools/build_unified_benchmark_report.py`

4) 在新 long.csv 上重算“配准指标 ↔ AP”映射（用于解释/预估/止损）：
- `tools/build_pose_error_to_ap_mapping_report.py`
