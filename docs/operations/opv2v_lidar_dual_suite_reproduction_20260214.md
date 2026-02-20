# OPV2V LiDAR Dual-Suite Benchmark Reproduction (2026-02-14)

目标：在 **LiDAR-only** 下同时产出两套语义曲线，并放到统一汇总中：

- Suite A: **Pose-Noise robustness**（无 `pose_override=zero`，baseline 应随噪声下降）
- Suite B: **No-Extr**（允许 `pose_override=zero`，baseline 可能近似平）

> 当前策略：Camera 暂停。先把 LiDAR 跑成“可信 + 可复现 + 有证据链”。

---

## 1) 一次性取证（先止损，再跑）

```bash
/home/qqxluca/projects/v2xreg_private/.micromamba/envs/py39/bin/python \
  tools/audit_opv2v_fullbench_run.py \
  --run-dir outputs/full_bench_opv2v_fullbench_fast_20260212
```

输出：
- `docs/operations/opv2v_fullbench_evidence_20260214.md`

这个报告会明确：
- run_state 最终完成情况（而不是靠扫日志猜）
- 早期失败的根因（如 CUDA fork）
- stage1 结构问题（camera test cache mismatch）
- pose_override / pose_solver.applied 证据

---

## 2) 预检 Gate（不通过就不允许开跑）

### 2.1 LiDAR stage1（应通过）

```bash
/home/qqxluca/projects/v2xreg_private/.micromamba/envs/py39/bin/python \
  tools/validate_stage1_cache.py \
  --stage1 data/OPV2V/detected/opv2v_lidar_v2xvit_stage1/test/stage1_boxes.json \
  --expected-samples 2170
```

### 2.2 Camera stage1（当前应失败，用于证明暂停 Camera 的依据）

```bash
/home/qqxluca/projects/v2xreg_private/.micromamba/envs/py39/bin/python \
  tools/validate_stage1_cache.py \
  --stage1 data/OPV2V/detected/opv2v_camera_v2xvit_stage1/test/stage1_boxes.json \
  --expected-samples 2170
```

---

## 3) Suite A：Pose-Noise（LiDAR）

> 核心：模型目录必须不含 `pose_override.enabled=true, mode=zero`。

```bash
/home/qqxluca/projects/v2xreg_private/.micromamba/envs/py39/bin/python \
  tools/run_opv2v_fullbench_fast.py \
  --run-id opv2v_lidar_posenoise_noise10_20260214 \
  --modalities lidar \
  --sweeps noise10 \
  --noise-list 0,1,2,3,4,5,6,7,8,9,10 \
  --rot-list 0,1,2,3,4,5,6,7,8,9,10 \
  --lidar-model HEAL/opencood/logs/freealign_repro_opv2v_baseline \
  --lidar-stage1 data/OPV2V/detected/opv2v_lidar_v2xvit_stage1/test/stage1_boxes.json \
  --gpus 0,1,2,3,4,5,6,7,8,9 \
  --max-per-gpu 2 \
  --num-workers 4
```

---

## 4) Suite B：No-Extr（LiDAR）

> 核心：显式允许 no-extr 语义（否则调度器会在 preflight 阶段拦截）。

```bash
/home/qqxluca/projects/v2xreg_private/.micromamba/envs/py39/bin/python \
  tools/run_opv2v_fullbench_fast.py \
  --run-id opv2v_lidar_noextr_noise10_20260214 \
  --modalities lidar \
  --sweeps noise10 \
  --noise-list 0,1,2,3,4,5,6,7,8,9,10 \
  --rot-list 0,1,2,3,4,5,6,7,8,9,10 \
  --lidar-model HEAL/opencood/logs/freealign_repro_opv2v_baseline_noextr_v2xregpp \
  --lidar-stage1 data/OPV2V/detected/opv2v_lidar_v2xvit_stage1/test/stage1_boxes.json \
  --allow-pose-override \
  --gpus 0,1,2,3,4,5,6,7,8,9 \
  --max-per-gpu 2 \
  --num-workers 4
```

---

## 5) YAML 汇总 + 自动有效性检查

> 默认会检查 pose-correction 的 `pose_solver.applied`，如果整条线全 0 会直接报错。

```bash
/home/qqxluca/projects/v2xreg_private/.micromamba/envs/py39/bin/python \
  tools/summarize_opv2v_fullbench_from_yaml.py \
  --run-dir outputs/full_bench_opv2v_lidar_posenoise_noise10_20260214
```

```bash
/home/qqxluca/projects/v2xreg_private/.micromamba/envs/py39/bin/python \
  tools/summarize_opv2v_fullbench_from_yaml.py \
  --run-dir outputs/full_bench_opv2v_lidar_noextr_noise10_20260214
```

输出：
- `results_ap50_from_yaml.json`（含 `ap30/ap50/ap70` 与 timing 字段）
- `plots_yaml/`（AP30/AP50/AP70 各模态/组合图）

---

## 6) 双 suite 合成图（同一交付）

```bash
/home/qqxluca/projects/v2xreg_private/.micromamba/envs/py39/bin/python \
  tools/plot_opv2v_dual_suite_from_yaml.py \
  --suite-a-run-dir outputs/full_bench_opv2v_lidar_posenoise_noise10_20260214 \
  --suite-b-run-dir outputs/full_bench_opv2v_lidar_noextr_noise10_20260214 \
  --suite-a-name "Pose-Noise (no pose_override)" \
  --suite-b-name "No-Extr (pose_override=zero)" \
  --modality lidar \
  --sweep noise10 \
  --noise-axis 0,1,2,3,4,5,6,7,8,9,10
```

输出：
- `plots_yaml_dual_suite/lidar_noise10_dual_suite_ap.png`
- `plots_yaml_dual_suite/lidar_noise10_dual_suite_timing.png`

---

## 7) 验收标准（必须同时满足）

1. `run_state.jsonl` 的“每个 task 最后一次 end code=0”覆盖全任务。  
2. Suite A baseline 的 AP50 对噪声有明显跨度（不应近似平线）。  
3. 校正方法 `pose_solver.applied` 非全 0；若全 0，此次结果判无效。  
4. Suite B 可允许 baseline 平，但图标题必须明确 No-Extr 语义。  
5. 交付图包含 AP30/AP50/AP70 + timing。  

