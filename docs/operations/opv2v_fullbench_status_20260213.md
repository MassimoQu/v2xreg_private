# OPV2V Full Benchmark Context & Status (2026-02-13)

更新: 2026-02-13 22:25 CST

> 2026-02-15 补充：本文件中的“完成度”使用了 **log grep 是否出现 AP 行** 的口径，
> 该口径在调度器重启/日志覆盖场景下会误判。请以 `run_state.jsonl` 为唯一完成判定，
> 以及参见证据报告：`docs/operations/opv2v_fullbench_evidence_20260214.md`。

## 目的

沉淀当前 OPV2V 全量 benchmark 的上下文，便于后续 AI/同事直接接手并复现。

## 我做了什么（变更清单）

1) 增加“按噪声拆分的并行调度器”
- 新增: `tools/run_opv2v_fullbench_fast.py`
- 作用: 把原先 1 个 job 跑 10 个噪声点改成“每个噪声点一个 job”，显著提高并行度。
- 输出: `outputs/full_bench_<run_id>/run_state.jsonl` 记录 start/end 事件。

2) 增加结果汇总脚本
- 新增: `tools/summarize_opv2v_fullbench_fast.py`
- 作用: 扫描日志提取 AP，生成曲线图并验证完整性。

3) 修复 LiDAR 的 CUDA fork 崩溃
- 修改: `HEAL/opencood/tools/inference_w_noise.py`
- 变更: 检测到 GPU voxel 预处理时，强制 `num_workers=0`（避免 DataLoader fork + CUDA 冲突）。
- 目的: 解决 `RuntimeError: Cannot re-initialize CUDA in forked subprocess`。

4) 调度器启用 GPU voxel
- `tools/run_opv2v_fullbench_fast.py` 中设置 `OPENCOOD_VOXEL_GPU=1`。

## 当前运行实例

- Run ID: `opv2v_fullbench_fast_20260212`
- 输出目录: `outputs/full_bench_opv2v_fullbench_fast_20260212/`
- 配置快照: `outputs/full_bench_opv2v_fullbench_fast_20260212/config_snapshot.json`
- GPU: `0-9`，每卡 3 个并发（max_per_gpu=3）
- num_workers: 4
- noise: `1.0 ... 10.0`（paired）
- dropout: `0.2`（仅 drop20）

模型 / 缓存（来自 config_snapshot）:
- camera model: `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope`
- lidar model: `HEAL/opencood/logs/freealign_repro_opv2v_baseline_noextr_v2xregpp`
- camera stage1: `data/OPV2V/detected/opv2v_camera_v2xvit_stage1/test/stage1_boxes.json`
- lidar stage1: `data/OPV2V/detected/opv2v_lidar_v2xvit_stage1/test/stage1_boxes.json`

## 当前进度（基于“日志内是否含 AP 行”的完成判定）

截至 2026-02-13 22:25 CST:
- 总任务: 404
- 已完成（日志含 AP）: 172
- 未完成: 232

分解:
- camera / drop20: 101 / 101 完成
- camera / noise10: 71 / 101 完成（剩 30 正在跑）
- lidar / noise10: 0 / 101 完成（旧日志全为 fork 崩溃）
- lidar / drop20: 0 / 101 完成（同上）

## 关键问题复盘（为何出现 “camera noise10 有 30 个没完成”）

事实链:
1) `run_state.jsonl` 显示这些 camera noise10 任务在 2026-02-12 已正常结束（exit code=0）。
2) 2026-02-13 20:51 修复 LiDAR fork 后，我重启调度器。
3) 调度器默认不使用旧日志作为完成判定；重启后它把“无 AP 行”的任务重新入队。
4) 调度器以 `open(log, "w")` 启动任务，会截断旧日志。

结果:
- 已完成的 camera 任务被重新入队并覆盖旧日志 → 现在看起来像“没完成”。
- 这不是算法失败，是调度/日志复用逻辑问题。

证据路径:
- `outputs/full_bench_opv2v_fullbench_fast_20260212/run_state.jsonl`
- `tools/run_opv2v_fullbench_fast.py` (log 文件以 "w" 打开)

## 还需要做什么

1) 等当前 30 个 camera noise10 任务结束。
2) 开始跑 LiDAR（修复后应正常跑完）。
3) 汇总结果并画图:
   - `tools/summarize_opv2v_fullbench_fast.py`

## 建议的修复/改进（防止再发生）

优先级从高到低:
1) 调度器增加 “resume/reuse” 逻辑：
   - 若 `run_state` 中已有 `end code=0`，则认为完成。
2) 日志写入改为 append 或写入新文件，避免覆盖旧结果。
3) 明确记录 “实际完成判定” 规则到 README（避免误用）。
