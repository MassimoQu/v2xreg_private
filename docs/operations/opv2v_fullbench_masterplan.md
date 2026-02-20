# OPV2V Full Benchmark Masterplan (2026-02-13)

更新: 2026-02-13 22:35 CST  
状态: AI 生成草案，需人工核验后执行/发布

## 0. 止损级硬门槛（不满足就禁止开跑）

> 你这次“跑完了但结果垃圾/平线/方法重合”的根因，本质都是缺少这些 gate。

1) **Stage1 cache 结构必须合法**（否则 pose solver 会 applied=0，方法曲线必然重合/无意义）  
   - camera: `data/OPV2V/detected/opv2v_camera_v2xvit_stage1_percav/test/stage1_boxes.json`  
   - lidar: `data/OPV2V/detected/opv2v_lidar_v2xvit_stage1/test/stage1_boxes.json`  
   - 运行校验：
     ```bash
     ./.micromamba/envs/py39/bin/python tools/validate_stage1_cache.py \
       --stage1 data/OPV2V/detected/opv2v_camera_v2xvit_stage1_percav/test/stage1_boxes.json \
       --expected-samples 2170 --require-contiguous-keys

     ./.micromamba/envs/py39/bin/python tools/validate_stage1_cache.py \
       --stage1 data/OPV2V/detected/opv2v_lidar_v2xvit_stage1/test/stage1_boxes.json \
       --expected-samples 2170 --require-contiguous-keys
     ```

2) **Suite 语义必须先选一个**（不要把 pose-noise robustness 和 no-extr 混在一张图里）  
   - A) pose-noise robustness：baseline 应随噪声下降；**禁止** `pose_override=zero`  
   - B) no-extr/calibration-free：允许 `pose_override=zero`；这时 baseline 平是合理现象

3) **Perception checkpoint 必须先过 sanity**（否则 AP≈0，曲线讨论无意义）  
   - 最低要求：baseline AP50 不应是 `1e-7` 量级（那是坏 ckpt / 配置错位）

4) **pose_solver.applied 必须非零**（至少在一部分样本上应用过）  
   - 汇总 YAML 时检查：`pose_solver_applied` 不得全 0（否则说明 stage1 / agent 对齐仍有问题）

## 1. 需求整理（明确“要做什么”）

1) 做一个公平、可复现的 OPV2V 全量 benchmark。  
2) 评测维度遵循 v2xreg++ 方式：成功率 / 精度 / 耗时；并包含 noise sweep 曲线。  
3) 包含 camera + lidar 两个模态；对比方法一致，仅外参求解方法不同。  
4) 必须包含 baseline / oracle / single 作为下界与上界。  
5) 结果必须可视化：  
   - 同一方法同色，不同策略用不同线型（best vs stable）。  
   - camera-only、lidar-only、camera+lidar 合并三张图。  
6) 不允许混入 GT 外参，除了 oracle 明确使用 GT 外参。  

## 2. 非可妥协的公平性约束

- 同一模态内：  
  - 同一 stage1 检测缓存  
  - 同一协同感知模型（V2XViT）  
  - 同一噪声设定、dropout 设定  
  - 仅“外参求解方法”不同  
- oracle 仅用于上限；baseline / single 作为下限。  

## 3. Benchmark 设计

### 数据集与任务
- 数据集: OPV2V (test split)
- 模态: camera / lidar
- Sweep:
  - noise10: pos/rot std = 1..10 (paired)
  - drop20: 同上 + dropout=0.2

### 方法
- v2xregpp (best/initfree + stable)
- freealign (best + stable)
- vips (best + stable)
- cbm (best + stable)
- baseline (no correction)
- oracle (GT pose)
- single (comm_range=0)

## 4. 执行计划（可复现步骤）

1) 准备 stage1 检测缓存  
   - camera: `data/OPV2V/detected/opv2v_camera_v2xvit_stage1_percav/test/stage1_boxes.json`  
   - lidar: `data/OPV2V/detected/opv2v_lidar_v2xvit_stage1/test/stage1_boxes.json`  
   - 必须先通过 `tools/validate_stage1_cache.py`（见 §0）
   - 若缓存不存在/不合法，先重建：
     ```bash
     ./scripts/build_opv2v_stage1_cache.sh
     ```

1.5) 先做 smoke（小样本全链路）  
   - 目的：先验证语义/配置，不直接烧 full run  
   - 建议命令：`SMOKE=1 SOLVER_BACKEND=online_box RUNTIME_MODE=register_and_fuse ./scripts/run_opv2v_fullbench.sh`  
   - smoke 通过条件（最小 gate）：
     - `run_state.jsonl` 中 smoke 任务 `end code=0`
     - 非 oracle 方法 `pose_solver.applied` 不是全 0
     - baseline AP50 不在 `1e-7` 量级
   - smoke 失败就止损，不得进入 fullbench

2) 启动并行调度器  
   - `tools/run_opv2v_fullbench_fast.py`  
   - GPU: 0-9, max_per_gpu=3  
   - num_workers=4 (LiDAR GPU voxel 时会强制 0)  
   - 语义选择（必须显式写在命令里，避免“以为在线其实离线”）：
     - offline 口径：默认 `--solver-backend offline_map`
     - online 端到端：`--solver-backend online_box --runtime-mode register_and_fuse`

3) 监控与结果收集  
   - 任务日志: `outputs/full_bench_<run_id>/logs/*.log`  
   - 完成判定（唯一可信）: `outputs/full_bench_<run_id>/run_state.jsonl` 中出现 end 且 code=0  
     - 不要用 “日志里有没有 AP 行” 做完成判定（日志可能被覆盖/截断）

4) 汇总与作图  
   - `tools/summarize_opv2v_fullbench_from_yaml.py`（优先，避免 log 口径/覆盖）  
   - 输出 camera-only / lidar-only / combined  
   - 确保：同色同方法，线型区分 best/stable  

## 4.5 验收标准（Acceptance / DoD）

- 完成定义（Definition of Done）：
  1) `run_state.jsonl` 覆盖本轮 scope 的所有任务，且最终 code 全部为 0；  
  2) 汇总产物齐全：`results_ap50_from_yaml.json` + 三张 plot（camera/lidar/combined）；  
  3) 语义一致：命令与 `config_snapshot.json` 明确记录 `solver_backend/runtime_mode/pose_source`；  
  4) 有效性检查通过：  
     - pose-noise suite 下 baseline 随噪声下降（非平线）  
     - oracle 近似水平且为上界  
     - stage1-based 方法 `pose_solver.applied` 非全 0。

- 不满足以上任一条，结论标记为 `BLOCK`，不得用于最终报告。

## 5. 当前进度（2026-02-13 22:35 CST）

Run ID: `opv2v_fullbench_fast_20260212`  
输出目录: `outputs/full_bench_opv2v_fullbench_fast_20260212/`

完成度（AP 行判定）:
- 总任务: 404  
- 已完成: 172  
- 未完成: 232  

分解:
- camera / drop20: 101 / 101 完成  
- camera / noise10: 71 / 101 完成（剩 30 正在跑）  
- lidar / noise10: 0 / 101 完成（旧日志全失败）  
- lidar / drop20: 0 / 101 完成（同上）  

## 6. 关键问题与原因复盘（需人工确认）

现象: camera noise10 有 30 个任务当前显示“未完成”。  

证据链:
- `run_state.jsonl` 显示这 30 个任务在 2026-02-12 已正常结束（exit code=0）。  
- 2026-02-13 20:51 修复 LiDAR fork 后重启调度器，这 30 个任务被重新入队。  
- 调度器以 `open(log, "w")` 写日志，导致旧结果被覆盖。  

结论:  
**这不是算法失败，而是调度器“复用判定 + 覆盖写”导致的结果丢失。**  
（强烈建议人工确认：详见 `run_state.jsonl` + 日志 mtime）

## 7. 剩余工作

1) 等当前 30 个 camera noise10 跑完。  
2) 重新跑 LiDAR 全量（修复后应正常）。  
3) 完成汇总、绘图、写最终报告。  
4) 修复调度器的“复用判定/覆盖写”问题，避免再次发生。  

## 8. 风险与改进建议

- 风险: 调度器重启可能覆盖旧日志。  
  建议: 以 `run_state.jsonl` 的 code=0 为完成判定；或日志 append。  
- 风险: LiDAR 使用 GPU voxel 时 DataLoader fork 崩溃。  
  建议: 强制 num_workers=0 或改用 spawn。  
- 风险: 结果整合时混用旧 run 与新 run。  
  建议: 固化 run_id + 单目录结果，禁止跨目录拼接。  

## 9. 备注（必读）

本文件为 AI 生成草案，**必须由人工核验关键结论**（完成度、失败原因、日志覆盖风险）。  
未经核验不得作为最终结论或对外发布依据。
