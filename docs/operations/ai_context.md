# 项目上下文与准则（喂给 AI 用）

本文档用于让后续的 AI/自动化脚本在**不丢失上下文**的情况下，持续迭代本项目的“论文复现 + 公共仓库发布”工作。  
目标不是“尽可能多放出去”，而是 **public 叙事与论文一致、代码可复现、宁缺毋滥**；所有未对齐项在 private 里如实记录并推进。

---

## 1. 核心目标（最高优先级）

1) **以论文为准完全复现** `/root/v2xreg_private/static/V2X_Calib_TITS_pdfLaTeX2023_compiled.pdf` 的 **Table III（DAIR-V2X）** 指标。  
2) 将“与论文描述不冲突、可复现且可维护”的部分 **选择性迁移**到 public 仓库（https://github.com/MassimoQu/v2i-calib）。  
3) 对所有“暂时对不齐/不稳定”的行或模块：在 **private** 中明确写出原因假设、差距、待办；**public 不展示冲突结果**。

---

## 2. 评估口径（必须固定，不允许随意改）

### 2.1 评估集合

- Paper-aligned 子集：`data/data_info_dair_paper3737.json`（|S|=3737）
- 入口配置（private）：`configs/pipeline_paper_dair3737.yaml`
- public 侧对应配置：`configs/pipeline_paper3737.yaml`

### 2.2 SuccessRate@λ 口径（Table III 对齐关键）

- `SuccessRate@λ`: **同时满足** `RTE < λ (m)` **且** `RRE < λ (deg)`（λ 同数值）  
- `mRTE@λ / mRRE@λ`: **只在成功帧上**求均值  
- 代码实现：`calib/evaluation/metrics.py`

补充：`success_te_only_at_{λ}m` 仅作为 debug（仅按 TE），不作为论文对齐指标。

### 2.3 一键对照（private）

- `python tools/compare_table3.py --root outputs_paper_3737`

---

## 3. 当前复现进度（以 private 为准）

> 更新日期：2025-12-28（只用于内部；public 文案避免强调“最近补做实验的时间”）

### 3.1 已基本对齐（Table III 下半部分，无初值、GT 输入）

V2X-Reg++ GT 行（3737 帧子集）已与论文非常接近：

- `outputs_paper_3737/dair_v2xregpp_gt25/metrics.json`：Success@{1,2,3}m ≈ **32.41/67.19/81.75%**（论文 32.27/67.59/82.93）
- `outputs_paper_3737/dair_v2xregpp_gt15/metrics.json`：≈ **26.57/62.43/78.89%**（论文 26.79/61.17/78.75）
- `outputs_paper_3737/dair_v2xregpp_gt10/metrics.json`：≈ **20.10/54.46/71.13%**（论文 20.02/54.86/71.98）

### 3.2 部分对齐但仍有差距

- V2X-Reg（oIoU）行：`outputs_paper_3737/dair_v2xreg_oiou_gt15/metrics.json`  
  当前 `@2m/@3m` 可以接近论文，但 `@1m` 仍偏低，需要继续核对 oIoU 细节与筛选口径。

### 3.3 未对齐（重点风险项）

- **PP/SC 检测框行（V2X-Reg++PP15 / SC15）**：现有 detection cache 跑出接近 0% SuccessRate。  
  已修复过一个确定性 bug：部分 cache 的 `cav_id_list` 顺序会导致 infra/veh 框对调（已在 `calib/data/detection_adapter.py` 修正）。  
  但更可能的根因是：**检测输出源/坐标系/后处理与论文不一致**，需要拿到与论文一致的 PP/SECOND 输出或重新导出。
- **ICP / PICP（Table III 上半部分）**：当前脚本跑出的成功率与耗时口径与论文差距显著（尤其 noise=1/2）。需要统一噪声、计时口径与 ICP 参数/失败判据后重跑。
- **VIPS / CBM（Table III 上半部分）**：可跑通，但与论文对应行仍有明显差距，需要固定噪声档位与 gate/实现细节后全量对齐。

---

## 4. public vs private 分工与叙事准则（必须遵守）

### 4.1 private（`v2xreg_private`）准则

- 允许保存：完整复现过程、debug 记录、失败案例、对齐假设、临时代码、脚本、内部文档。  
- 不允许：把大体积 `outputs*`、数据集副本、检测 cache 等误提交到 git（依赖 `.gitignore` + review）。
- 结论写法：**直接、可验证**（给出路径/命令/指标），不要“遮遮掩掩”；未对齐就明确写未对齐，并写下一步动作。

### 4.2 public（`v2i-calib`）准则

- 原则：**宁可少放出去，不乱放出去**。只发布：
  - 与论文描述不冲突、可稳定复现的核心代码与入口
  - 与论文 Table III 对齐的 GT 复现配置/子集（目前已发布）
- public README/文案：
  - 不罗列容易引起质疑的“状态/不稳定”细节（例如过度强调 status）
  - 更合适的表述是：**我们发布了哪些部分**；哪些仍在“整理/清理缓存/复现实验中”
  - 不展示与论文冲突的数字（尤其 PP/SC、HEAL、半成品检测融合等）
  - 避免暴露“近期补做实验的具体时间”；若必须提及，只以“2025 年初完成的复现实验设置”为叙事基准
- 安全与隐私：
  - 不把 private 的路径、内部数据、日志、缓存、未清理的 commit 记录带到 public
  - 如果发现泄露风险：**只对最近少量提交做 squash/合并**去除敏感内容；不要为了“消掉”而删除整个历史（需要保留工作量展示）

---

## 5. “迁移到 public”的发布门槛（Checklist）

某一行/模块要迁移到 public，至少满足：

1) **口径一致**：SuccessRate/mRTE/mRRE 与论文 Table III 定义一致（见第 2 节）。  
2) **数据可得**：public 不依赖 private cache；依赖项要么可重建、要么明确要求用户自己生成。  
3) **数值可对齐**：在 paper3737 子集上达到论文数值附近（建议以 SuccessRate 绝对差 < 1% 为目标）。  
4) **叙事不冲突**：README/Docs 不出现与论文冲突的结果或“半成品展示”。  
5) **可复现命令**：给出 1-2 条明确命令可跑通（不要求用户跑全量数据，但路径/配置必须自洽）。

---

## 6. 复现迭代循环（AI 工作方式）

每一轮迭代遵循：

1) **跑对照**：`python tools/compare_table3.py --root outputs_paper_3737`，定位差距最大的行/指标。  
2) **最小改动假设**：一次只改一个变量（噪声/计时/参数/坐标系转换之一）。  
3) **小样本验证**：先跑 50~200 帧验证趋势与失败原因，再全量 3737。  
4) **全量固化**：全量对齐后，把“口径/配置/脚本/日志路径”写入 `paper_alignment.md` / `paper_reproduction_plan.md`。  
5) **决定迁移**：对照第 5 节 Checklist，满足则迁移到 public；否则 private 记录原因与 TODO。

---

## 7. 接下来要做什么（private 主线，按 ROI）

1) **ICP/PICP 对齐**：把点云 I/O 纳入计时、对齐 ICP 参数/鲁棒核/失败判据，重跑 noise=0/1/2。  
2) **VIPS/CBM 对齐**：固定噪声档位与 gate（match distance / min_matches 等），全量对照 Table III。  
3) **PP/SC 对齐**：重新导出或转换与论文一致的 PP/SECOND 检测输出（坐标系与后处理必须可审计）。  
4) **oIoU 对齐**：定位 `@1m` 偏低来源（实现细节 vs 筛选口径），用失败帧列表驱动修正。

（详细步骤见：`docs/operations/paper_reproduction_plan.md`）

