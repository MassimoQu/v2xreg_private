# 论文结果对齐检查（内部）

本文件用于“以论文为准”检查当前代码/数据是否能复现论文指标，并记录差距与待办方向。  
注意：仓库内很多实验是**子集/快速跑**，与论文 Table III 的 **DAIR-V2X 全量统计**不一定一一对应，需要结合数据版本与筛选策略交叉验证。

> 另见：`docs/operations/ai_context.md`（public/private 发布准则 + 复现迭代工作流）。

## 1. 论文指标（PDF 基准）

来源：`static/V2X_Calib_TITS_pdfLaTeX2023_compiled.pdf`，Table III（DAIR-V2X）。

### 1.1 SuccessRate@λ 口径（重要）

论文正文中对 SuccessRate@λ 的定义文字更偏向 “RTE < λ”；但对齐 Table III 的数值时，
**更吻合的口径**是：

- `SuccessRate@λ`: `RTE < λ (m) 且 RRE < λ (deg)`
- `mRTE@λ / mRRE@λ`: 在 “成功帧” 上求均值

当前仓库按上述口径计算 `success_at_*`；同时保留了仅按 RTE 的旧口径 `success_te_only_at_*`
用于 debug（见 `calib/evaluation/metrics.py`）。

### 1.2 Table III 中关键 V2X-Reg++（GT）行

- `GT∞`：@1m 22.88%，@2m 48.03%，@3m 61.49%，Time 0.46s
- `GT25`：@1m 32.27%，@2m 67.59%，@3m 82.93%，Time 0.12s
- `GT15`：@1m 26.79%，@2m 61.17%，@3m 78.75%，Time 0.09s
- `GT10`：@1m 20.02%，@2m 54.86%，@3m 71.98%，Time 0.04s

（PP/SC 等检测框行、ICP/PICP/VIPS/CBM 等基线见 Table III 原表；此处略。）

## 2. 当前仓库复现口径（建议）

### 2.1 论文对齐（推荐）

- 使用论文评估子集（3737 帧）：`data/data_info_dair_paper3737.json`
- 入口配置：`configs/pipeline_paper_dair3737.yaml`
- 一键对比：`python tools/compare_table3.py --root outputs_paper_3737`

## 3. 当前状态（与论文差距）

### 3.1 已对齐（可复现）

- Table III 下半部分（无初值、GT 输入）主力行已复现（3737 帧）：
  - `outputs_paper_3737/dair_v2xregpp_gt25/metrics.json`：`success@{1,2,3}m ≈ 32.41/67.19/81.75%`
    （论文：32.27/67.59/82.93%）
  - `outputs_paper_3737/dair_v2xregpp_gt15/metrics.json`：`success@{1,2,3}m ≈ 26.57/62.43/78.89%`
    （论文：26.79/61.17/78.75%）
  - `outputs_paper_3737/dair_v2xregpp_gt10/metrics.json`：`success@{1,2,3}m ≈ 20.10/54.46/71.13%`
    （论文：20.02/54.86/71.98%）

### 3.2 未对齐 / 待办（不建议写入 public）

- **PP/SC 检测框行（V2X-Reg++PP15 / SC15）**：当前仓库内现有缓存跑出接近 0 的成功率，
  与论文不一致；大概率原因是检测源/坐标系/筛选口径与论文不一致（需要拿到与论文一致的 PP/SECOND
  输出或重新导出并校验坐标系）。
- 已确认并修复的一个具体坑：部分 detection cache 的 `cav_id_list` 顺序为
  `['vehicle','infrastructure']`，如果按 idx=0/1 固定映射会把 infra/veh 框对调并导致系统性失败；
  目前 `calib/data/detection_adapter.py` 已改为按 `cav_id_list` 映射。
- **ICP / PICP（初值法）**：现有 Open3D 版本实现结果明显高于论文、耗时明显低于论文，
  需要进一步对齐算法实现/参数/噪声模型与计时口径（详见 `tools/compare_table3.py` 输出差异）。
- **V2X-Reg（oIoU）**：`outputs_paper_3737/dair_v2xreg_oiou_gt15/metrics.json` 当前仍低于论文
  `25.54/55.93/72.31%`，需要继续核对 IoU 计数与过滤口径。
- **VIPS / CBM**：已可全量跑通（3737），但与论文 Table III 的对应行仍有明显差距
  （可能是 baseline 参数/噪声设定/实现差异导致“可跑但不可比”）。

## 4. 待办方向（ROI 优先）

1. **先统一口径**：明确论文使用的 DAIR-V2X 版本与评估集合（frame 列表）并在仓库里生成对应 `data_info_*.json`，保证“跑的就是论文那批帧”。
2. **对齐 Table III 配置**：把论文中 `GT∞/GT25/GT15/GT10` 的 box 排序规则、阈值（τ/τ1、α/β）与实现逐项核对。
3. **把 gap 量化到组件**：统计失败帧占比、无匹配帧占比、以及成功帧的误差分布（可从 `outputs/<tag>/matches.jsonl` 聚合）。
4. **检测框/HEAL 集成先降级为 WIP**：若无法稳定达到论文水平，public 只保留入口与工具，不在 README 里写“已复现论文表格数值”。
