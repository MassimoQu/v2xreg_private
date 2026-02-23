# HEAL 无初值在线配准 + 异构协同融合一体化设计草案

Update Log (append new entries at top):
- 2026-02-20 (v1.1): Landed `online_feature_refiner.py` and connected `online_box_feat_refine` runtime path. Added refine timing output (`refine_sec`, `refine_attempted_count`, `refine_applied_count`) and smoke evidence in gate artifacts.
- 2026-02-09 (v1.0): Marked `online_box_solver.py` as landed (integrated in runtime as opt-in `gpu_stage1_solver` path with unit check). Kept `online_feature_refiner.py` as open milestone and clarified current parity risk.
- 2026-02-08 (v0.9): De-duplicated with execution playbook. Trimmed Section 4 to algorithm-only constraints and moved order/gates/rollback details to `heal_pose_fusion_execution_playbook.md`.
- 2026-02-08 (v0.8): Synced with doc split. Kept this file algorithm-focused and moved execution/cutover procedures to `heal_pose_fusion_execution_playbook.md`; added boundary notes for easier doc management.
- 2026-02-08 (v0.7): Review-fix round 3/3. Added final transition checklist (entry/exit/rollback) and clarified per-mode fallback semantics to avoid hidden behavior drift.
- 2026-02-08 (v0.6): Review-fix round 2/3. Added runtime switch state machine with legacy compatibility mapping and explicit fairness invariants for single/fusion/register comparison.
- 2026-02-08 (v0.5): Review-fix round 1/3. Expanded implementation order and phase handoff logic between GPU runtime foundation and no-init algorithm refinement.
- 2026-02-08 (v0.4): Review-fix pass. Cleaned section ordering (`9->10->11->12`) and removed duplicated heading to keep the document incrementally maintainable.
- 2026-02-08 (v0.3): Review-fix pass. Replaced parallel config concept with `pose_provider`-compatible schema, added code-grounded reuse/gap map, and introduced measurable acceptance matrix.
- 2026-02-08 (v0.2): Review-fix pass. Added fairness constraints for single/coop/shared detector path and clarified online/offline parity requirements.
- 2026-02-08 (v0.1): Initial draft. 将“全 GPU 化执行改造”和“无初值算法联合设计”拆分；本文件聚焦算法/系统一体化（在线单端检测 -> 检测框配准初值 -> 特征对齐细化 -> 协同融合）。

## 1. 背景与目标

你希望在 HEAL 内部实现一个统一在线系统，而不是“离线 stage1 cache + 离线配准 + 再融合”的串行流程。目标是：

- 输入原始多端传感器数据（车端/路端，支持异构模态）。
- 在线单端检测（同一个单端网络权重）得到检测框与中间特征。
- 基于检测框做无初值配准，得到初始外参。
- 在 HEAL 的中间特征对齐阶段继续优化外参（类似 SfM / direct alignment 思路）。
- 直接输出协同感知结果。
- 同一套图同时支持四种模式：
  - `single_only`
  - `register_only`
  - `fusion_only`
  - `register_and_fuse`

## 2. 设计边界

In-scope:
- 在线、统一、可切换模式的数据流和模型侧接口。
- 检测框驱动的无初值配准 + 特征级 refinement 的组合策略。
- 以 GPU 为主计算路径（CPU 仅数据解码、轻量预处理、日志）。

Out-of-scope (本阶段不做):
- 重新训练新的大型 backbone。
- 改写所有历史脚本；先保证主训练/主推理链路。
- 追求“所有方法一次到位最优”，而是先保证系统闭环、再做策略搜索。

## 3. 统一在线数据流（目标态）

```text
Raw Multi-Agent Sensors
  -> HEAL Encoders (per-agent, heterogeneous)
  -> Single-Agent Detection Head (per-agent boxes + scores)
  -> No-Init Box Pose Solver (SE(2) init)
  -> Feature Alignment Refiner (optimize SE(2) on BEV features)
  -> Pairwise T Builder
  -> HEAL Fusion (v2xvit / other)
  -> Fusion Detections
```

关键点：
- 配准初值来自“同一前向”的单端检测框，不依赖离线缓存。
- 特征细化使用“同一前向”的中间特征，避免跨流程统计偏移。
- 配准与融合不再拆两次 pipeline，而是在同一 runtime 中顺序执行。

## 4. 四模式统一接口


### 4.1 与执行手册的边界（先看这里）

为减少文档管理负担，本文件只保留“算法设计与约束（what/why）”，不重复维护执行编排（how）：
- 执行顺序、阶段门槛、回滚策略统一维护在：
  - `docs/operations/heal_pose_fusion_execution_playbook.md`
- 本文件仅保留与算法正确性直接相关的依赖关系：
  1) 先有稳定在线 runtime（数据与计时口径固定）；
  2) 再做 `online_box` 无初值配准；
  3) 最后做 `online_box_feat_refine` 精度-时延权衡。

这样可以避免同一逻辑在两份文档中“双写双改”。

### 4.2 模式与兼容映射（摘要）

目标四模式：
- `runtime_mode=single_only`
- `runtime_mode=fusion_only`
- `runtime_mode=register_only`
- `runtime_mode=register_and_fuse`

兼容映射（当前代码）：
- `pose_provider.mode=gt_only` -> `fusion_only + pose_source=gt`
- `pose_provider.mode=register_only` -> `register_only`
- `pose_provider.mode=register_and_fuse` -> `register_and_fuse`
- no-fusion 推理入口 -> `single_only`（后续收敛）

解析优先级：
- `pose_provider.runtime_mode`（新）优先于 `pose_provider.mode`（旧）。

### 4.3 `register_and_fuse` 的算法内过渡规则

`register_and_fuse` 下建议固定如下顺序（算法语义，不是执行编排）：
1) Box solver 产出 `T_init` + `solver_conf`。
2) 若 `solver_conf < tau_low`：fallback（`keep_prev` 或 `identity`），禁止切 GT。
3) 若 `tau_low <= solver_conf < tau_high`：可跳过 L2 refine，仅用 `T_init`。
4) 若 `solver_conf >= tau_high`：执行 L2 refine 得到 `T_refined`。
5) 将最终 `T` 写入 pairwise，进入融合头。

公平性硬约束：
- `oracle/GT` 仅允许在 `fusion_only + pose_source=gt` 的上界实验出现。
- 正常方法比较（v2xreg++/freealign/vips/cbm）不得混入 GT fallback。

建议统一配置接口（与当前 HEAL 保持兼容，不新增并列 pose 顶层块）：

```yaml
pose_provider:
  enabled: true
  runtime_mode: register_and_fuse   # single_only | register_only | fusion_only | register_and_fuse
  solver_backend: online_box_feat_refine   # offline_map | online_box | online_box_feat_refine
  freeze_ego: true
  recompute_pairwise: true
  init_solver:
    name: box_noinit
    min_matches: 3
  refine_solver:
    name: feature_refine
    steps: 5
    optimizer: gauss_newton
fusion:
  core_method: v2xvit
  args:
    use_pose_confidence: true
```

模式语义：
- `single_only`: 输出主车单端检测结果（与协同融合评测使用同一检测范围和后处理参数）。
- `register_only`: 输出 pose metrics + timing，不跑融合头。
- `fusion_only`: 跳过求解，使用 GT pose 或 identity pose（可配置）进行融合。
- `register_and_fuse`: 先配准再融合，输出 pose + detection 全指标。

配置一致性原则：
- 只允许通过 `pose_provider.runtime_mode` 和 `pose_provider.solver_backend` 切模式。
- `fusion` 配置在四模式下保持一致，确保 benchmark 公平可比。

## 5. 算法分层设计

### 5.1 L0: 单端检测与中间特征导出（同一模型）

输入：每个 agent 的原始传感器数据。  
输出（每个 agent）：
- 单端 3D 检测框（corners / score / type）。
- BEV 中间特征（用于后续特征对齐）。

要求：
- 单端检测与协同融合共享同一 backbone/encoder，禁止“两个不同模型”。
- 输出范围与评测范围一致（便于 single vs fusion 公平比较）。

### 5.2 L1: 检测框无初值配准（Box Init Solver）

目标：给每个 non-ego agent 估计 `T_ego<-cav` 的初值（SE(2): x,y,yaw）。

建议策略：
- 先做 bbox 过滤（score/type/top-k）保证鲁棒性。
- 匹配阶段输出匹配对 + 质量分数（precision/matched/stability）。
- SVD/weighted-SVD 求 `T_init`。
- 失败策略：若匹配不足，标记低置信，进入 fallback（identity / previous state / skip fusion）。

### 5.3 L2: 特征对齐细化（Feature Refiner, 类 SfM/direct）

核心思想：在 `T_init` 基础上，利用中间 BEV 特征做小步优化，得到 `T_refined`。

可执行目标函数（示例）：
- `L_feat`: warp 后特征余弦相似或 L1/L2 photometric-like 损失。
- `L_box`: warp 后 bbox 一致性（中心距离/IoU proxy）。
- `L_reg`: 对增量 `delta_T` 的正则（限制步长，防抖）。

总损失：
- `L = w_feat * L_feat + w_box * L_box + w_reg * L_reg`

优化变量：
- `delta = [dx, dy, dyaw]`（SE(2)）。

优化器建议：
- 推理时：固定步数（3~10步）的小规模 Gauss-Newton / Adam。
- 稳态模式：结合 EMA 与步长限制。

输出：
- `T_refined`
- `pose_confidence`（由残差下降量 + 匹配质量联合映射）

### 5.4 L3: 协同融合与检测输出

- 用 `T_refined` 重建 `pairwise_t_matrix`。
- 进入 HEAL 融合模块（如 v2xvit），输出协同融合检测结果。
- 对 `fusion_only` 模式，直接走融合但跳过 L1/L2。

## 6. 稳定性与无初值评测设计

### 6.1 无初值稳定性指标

除 AP 外，必须固定输出：
- pose success@{1,2,3,5,10}m
- median trans / median yaw
- update acceptance ratio（每帧成功更新比例）
- fallback ratio（回退比例）
- temporal jitter（相邻帧位姿抖动）

### 6.2 公平 benchmark 结构（单一 track）

同一检测范围、同一 backbone/ckpt、同一后处理：
- Lower bounds:
  - `single_only`
  - `fusion_only + identity/noisy init pose`（不做优化）
- Upper bound:
  - `fusion_only + GT pose`
- Normal runs:
  - `register_and_fuse(method)`，method = v2xreg++, freealign, vips, cbm ...

要求：
- 仅 pose backend 变化，其它配置固定。
- camera/lidar 的比较采用相同图例规范（同方法同色，不同策略不同线型）。

## 7. 与现有 HEAL 代码的落地映射

建议新增/改造模块：

1) `HEAL/opencood/utils/pose_provider_runtime.py`
- 扩展为在线 backend 调度器：`offline_map | online_box | online_box_feat_refine`。

2) `HEAL/opencood/extrinsics/pose_correction/online_box_solver.py`（已落地，实验开关）
- 已提供检测框无初值求解张量 API，并在 `pose_provider_runtime` 里以 `online_args.gpu_stage1_solver=true` 方式接入。
- 当前默认关闭（未过 parity gate 前不替换 reference lane）。

3) `HEAL/opencood/extrinsics/pose_correction/online_feature_refiner.py`（已落地）
- 封装 feature-level SE(2) local refinement（GPU 张量局部搜索 + 小步优化）。

4) `HEAL/opencood/models/heter_model_baseline.py`
- 明确导出 per-agent 单端检测输出与 BEV feature 句柄，避免二次前向。

5) `HEAL/opencood/tools/inference_w_noise.py` / `HEAL/opencood/tools/inference.py`
- 新增在线统一入口参数：`--runtime-mode`，去掉“必须先离线 stage1”的强依赖。

### 7.1 现有可复用能力 vs 关键缺口（code-grounded）

可复用：
- 模型前向后可注入 pose runtime：`HEAL/opencood/tools/train_utils.py:353`。
- 现有推理已在前向前调用 pose provider：`HEAL/opencood/tools/inference.py:172`、`HEAL/opencood/tools/inference_w_noise.py:782`。
- 融合主干已经依赖 `pairwise_t_matrix` 作为几何输入契约：`HEAL/opencood/models/heter_model_baseline.py:247`。

关键缺口：
- 当前 correction 仍是离线前处理并写 override map：`HEAL/opencood/tools/inference_w_noise.py:717`。
- `run_pose_solver` 仍是 sample-level Python 循环：`HEAL/opencood/extrinsics/pose_correction/pose_solver.py:201`。
- V2XReg++ 在线求解热点仍有 NumPy/SciPy/legacy Python 路径：`HEAL/opencood/extrinsics/pose_correction/stage1_v2xregpp.py:299`、`HEAL/opencood/extrinsics/pose_correction/stage1_v2xregpp.py:734`。
- 已有 GPU stage1 试验分支（`gpu_stage1_solver`）可将 box-solver 热点迁移到 torch，但当前精度/语义与 reference lane 仍需 parity 收敛。

## 8. 里程碑（建议）

### Milestone A: 在线闭环 MVP（2~3 周）
- 实现 `register_and_fuse` 在线串联（L0 + L1 + 融合）。
- 支持 `single_only` / `register_only` / `fusion_only` 模式切换。
- 与离线旧流程做 200-sample parity。
- 交付物：统一推理入口 + 四模式单命令切换样例配置。

### Milestone B: 特征细化接入（2 周）
- 接入 L2（Feature Refiner）并打通 timing 与 pose_confidence。
- 完成 no-init 稳定性基线测试（1m~10m + dropout）。
- 交付物：特征细化 ablation（steps/optimizer/loss 权重）曲线与推荐默认值。

### Milestone C: benchmark 固化（1~2 周）
- 输出统一表格 + 曲线 + 可复现实验脚本。
- 固化公平性检查清单（配置 hash、范围、后处理一致性）。
- 交付物：单车/下界/上界/正常方法一体化 benchmark 报告模板。

## 9. 主要风险与回退策略

风险 1：在线细化导致延迟过高。
- 回退：限制 refinement 步数；低置信帧仅用 L1 初值。

风险 2：无初值在稀疏检测帧不稳定。
- 回退：启用 temporal prior（stable 模式）+ 最小匹配门限。

风险 3：异构模态特征尺度不一致影响 refinement。
- 回退：先在 BEV 公共空间对齐后再优化；加入模态归一化层。

风险 4：与现有脚本生态冲突。
- 回退：保留 `offline_map` backend，在线功能通过新开关启用。

## 10. 当前待决策项

- refinement 优化器默认用 Gauss-Newton 还是 Adam？
- `pose_confidence` 是仅供融合加权，还是也用于动态跳过融合？
- 是否先只支持 SE(2) 在线优化，再扩展到 6DoF？
- camera/lidar 混合 pair 的细化损失是否共享同一权重。

## 11. 验收矩阵（v0.9）

- A1 在线一致性：`online_box` 相对 `offline_map`，AP30/50/70 差异 `<= 1e-3`（当前执行口径）。
- A2 姿态一致性：中位平移/偏航误差差异 `<= 1e-3`。
- A3 稳定性收益：`feature_refine` 相比仅 `box_noinit`，在 1m~10m sweep 上 median jitter 不恶化，且 AP50 不下降。
- A4 公平性：`single_only` / `fusion_only` / `register_only` / `register_and_fuse` 共用同一 detector 权重、同一检测范围、同一后处理参数（`register_only` 允许不产出融合检测，但前向与阈值配置必须一致）。
- A5 工程约束：除数据解码与日志外，热点路径无强制 CPU 回退。

## 12. Review-Fix 结论（v0.9）

本轮修复掉的主要问题：
- 配置冲突风险：已改为兼容 `pose_provider` 现有接口，不再引入并列顶层 pose 配置。
- 公平性定义不够硬：已加入显式验收矩阵和模式一致性约束。
- 落地可执行性不足：已补充“可复用能力/缺口”代码映射，避免纯概念描述。
- 文档角色边界不清：已把执行编排移交给 playbook，本文件聚焦算法语义与约束。
- 切换逻辑歧义：已加入 `runtime_mode`/`mode` 兼容映射与优先级，防止实验配置暗中漂移。

## 13. 文档边界（2026-02-08）

为避免和执行类文档重叠，本文件仅保留算法与系统协同设计（what/why）。

- 执行顺序、切换与回滚（how）统一维护在：
  - `docs/operations/heal_pose_fusion_execution_playbook.md`
- 架构契约与当前已验证事实统一维护在：
  - `docs/operations/heal_pose_fusion_unified_arch.md`
- 总导航入口：
  - `docs/operations/heal_pose_fusion_docs_index.md`
