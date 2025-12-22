# 论文结果对齐检查（内部）

本文件用于“以论文为准”检查当前代码/数据是否能复现论文指标，并记录差距与待办方向。  
注意：仓库内很多实验是**子集/快速跑**，与论文 Table III 的 **DAIR-V2X 全量统计**不一定一一对应，需要结合数据版本与筛选策略交叉验证。

## 1. 论文指标（PDF 基准）

来源：`static/V2X_Calib_TITS_pdfLaTeX2023_compiled.pdf`，Table III（DAIR-V2X）。

V2X-Reg++（GT）SuccessRate@λ（仅按 RTE 阈值 λ 统计）：
- `GT∞`：@1m 22.88%，@2m 48.03%，@3m 61.49%，Time 0.46s
- `GT25`：@1m 32.27%，@2m 67.59%，@3m 82.93%，Time 0.12s
- `GT15`：@1m 26.79%，@2m 61.17%，@3m 78.75%，Time 0.09s
- `GT10`：@1m 20.02%，@2m 54.86%，@3m 71.98%，Time 0.04s

（PP/SC 等检测框行、ICP/PICP/VIPS/CBM 等基线见 Table III 原表；此处略。）

## 2. 当前仓库复现口径（建议）

- **GT sweeps 推荐入口**：`python tools/run_dair_pipeline_experiments.py --config configs/pipeline_top3000.yaml`
  - 它会跑 `dair_v2xregpp_gt_inf / gt25 / gt15 / gt10` 等 tag，并落盘到 `outputs/<tag>/metrics.json`。
- **注意子集**：`configs/pipeline_top3000.yaml` 默认使用 `data/data_info_top3000.json`（Top-3000 子集），这与论文的全量 DAIR-V2X 统计口径可能不同。

## 3. 当前状态（与论文差距）

截至本次整理，仓库在 Top-3000 子集上（`filters.top_k=25`）可稳定跑通并达到：
- `success@2m ≈ 0.54`（示例：一次 3000 帧 GT25 跑出来约 0.543，`avg_time ≈ 0.034s`）

与论文 Table III 的 `GT25 @2m = 0.6759` 仍有差距，需进一步定位是：
1) 数据版本/筛选口径不同（论文“3737 帧” vs 本仓库“Top-3000 子集”等），还是  
2) 算法实现/参数未完全对齐（例如阈值、匹配过滤、评估集合定义）。

## 4. 待办方向（ROI 优先）

1. **先统一口径**：明确论文使用的 DAIR-V2X 版本与评估集合（frame 列表）并在仓库里生成对应 `data_info_*.json`，保证“跑的就是论文那批帧”。
2. **对齐 Table III 配置**：把论文中 `GT∞/GT25/GT15/GT10` 的 box 排序规则、阈值（τ/τ1、α/β）与实现逐项核对。
3. **把 gap 量化到组件**：统计失败帧占比、无匹配帧占比、以及成功帧的误差分布（可从 `outputs/<tag>/matches.jsonl` 聚合）。
4. **检测框/HEAL 集成先降级为 WIP**：若无法稳定达到论文水平，public 只保留入口与工具，不在 README 里写“已复现论文表格数值”。

