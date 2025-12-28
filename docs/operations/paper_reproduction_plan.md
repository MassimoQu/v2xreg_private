# 论文基准复现计划（内部）

目标：在 **DAIR-V2X / Table III** 的评估口径下，尽可能复现论文中的 **SuccessRate / mRRE / mRTE / Time**（以论文为准），并将“可复现且不冲突”的部分逐步迁移到 public 仓库。

## 0. 已锁定口径（必须一致）

- **评估集合**：`data/data_info_dair_paper3737.json`（3737 帧）
- **SuccessRate@λ**：`RTE < λ(m)` 且 `RRE < λ(deg)`（同数值 λ），并在成功帧上统计 `mRTE/mRRE`
- 一键对照（内部）：`python tools/compare_table3.py --root outputs_paper_3737`

## 1. 当前已复现（可对外）

- V2X-Reg++（无初值、GT 输入）主力行（Table III 下半部分）：
  - `outputs_paper_3737/dair_v2xregpp_gt25/metrics.json`：Success@{1,2,3}m ≈ 32.41/67.19/81.75%
  - `outputs_paper_3737/dair_v2xregpp_gt15/metrics.json`：≈ 26.57/62.43/78.89%
  - `outputs_paper_3737/dair_v2xregpp_gt10/metrics.json`：≈ 20.10/54.46/71.13%

## 2. 待复现项与实施路径（按 ROI 排序）

### 2.1 ICP / PICP（Table III 上半部分）

现状：成功率显著高于论文、耗时显著低于论文（主要因为当前计时不含点云 I/O，且 ICP 参数/失败判据可能不同）。

计划：
1. **统一噪声注入**：按论文描述使用左乘 SE(3) 噪声（m & deg 同尺度），并固定随机种子（已完成代码层面的噪声形式）。
2. **统一计时口径**：将点云读取 + 下采样/法向估计纳入 `time_cost`（与其它 baseline 脚本保持一致）。
3. **统一 ICP 细节**：对齐点到点/点到面、`max_corr`、鲁棒核（Huber）、迭代终止条件；必要时引入失败判据（fitness / rmse / delta gate），失败则回退到初值（但仍计入耗时）。
4. 重跑 `noise=0/1/2` 三档并用 `tools/compare_table3.py` 验证。

### 2.2 VIPS / CBM（Table III 上半部分）

现状：可全量跑通，但与论文存在明显差距（噪声档位、匹配 gate、以及实现细节可能未对齐）。

计划：
1. 噪声统一为 `0/1/2 (m & deg)`（已具备对应实验脚本/输出目录）。
2. 固化 VIPS/CBM 的后处理 gate（例如 match distance / min_matches），以对齐论文 reimplementation 的策略。
3. 全量重跑 `noise=0/1/2` 并对照 Table III。

### 2.3 PP / SC 检测框行（Table III 下半部分）

现状：现有 cache 跑出接近 0% 的 SuccessRate；代码侧已修复 `cav_id_list` 顺序映射 bug，但根因更像是 **检测输出源/坐标系/后处理与论文不一致**。

计划：
1. 明确论文使用的 PP / SECOND 版本与输出格式（优先从 DAIR-V2X 官方 repo 重新导出）。
2. 写一个 **确定性的转换器**：将检测输出转换为仓库内部 `BBox3d` 输入口径（坐标系、yaw 定义、单位、过滤规则）。
3. 用少量帧做可视化/数值 sanity check（对齐 GT 坐标尺度与分布），再全量跑 Table III 的 PP15 / SC15。

### 2.4 V2X-Reg（oIoU）行（Table III 下半部分）

现状：`@2m/@3m` 可对齐，但 `@1m` 偏低。

计划：
1. 对齐 oIoU 的计数/归一化/阈值，并核对筛选策略（top-k、distance_m、filter_threshold）。
2. 用失败帧列表定位具体类别（小目标/远距离/遮挡）导致的系统性偏差。

## 3. 对外发布策略（public vs private）

- **public**：只发布“与论文叙述不冲突、可稳定复现”的入口（当前：GT 版本 + paper3737 subset）。
- **private**：保留所有对齐实验、缓存转换、失败案例与待办；每完成一块再决定是否迁移到 public。
