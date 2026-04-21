# fully_fair_v2xvit_core_benchmark_plan vs coopVGGT eval_v2_1（差异表 + 对齐建议 + Action List）

更新：2026-03-04

## 0) 范围与 Source-of-Truth（先避免“同名但不同题”）

### 0.1 fully_fair_v2xvit_core_benchmark_plan（本文简称 **FF-plan**）

Source-of-truth：
- `docs/operations/fully_fair_v2xvit_core_benchmark_plan_v1_20260227.md`

核心诉求（FF-plan 的“Fully-Fair”）：
- **同一数据集内公平**：固定 `checkpoint(model_dir) + stage1 cache + noise schedule + comm-range 语义 + runtime 语义`，只替换 pose-correction 方法；
- **跨数据集也尽量公平**：三数据集尽量使用同一类 baseline 网络家族（V2XViT），降低“方法差异”与“网络差异”纠缠。

### 0.2 coopVGGT Track1 eval_v2_1（本文简称 **E21**）

E21 的 source-of-truth（在本机 `vggt_series_4_coop` 控制面仓库）：
- 协议：`/home/qqxluca/vggt_series_4_coop/configs/eval_protocol_v2_1.yaml`
- Gate：`/home/qqxluca/vggt_series_4_coop/configs/eval_gates_v2_1.yaml`
- Bundle 校验实现：`/home/qqxluca/vggt_series_4_coop/scripts/eval_utils.py`
- 入口脚本：`/home/qqxluca/vggt_series_4_coop/scripts/validate_eval_bundle.py`、`/home/qqxluca/vggt_series_4_coop/scripts/compute_gate_status.py`
- 看板同步：`/home/qqxluca/vggt_series_4_coop/scripts/project_sync_github.py`

E21 的“看板框架/执行闭环”（用来解释项目卡片为什么这样拆）：
- `/home/qqxluca/vggt_series_4_coop/docs/project_master_overview.md`
- `/home/qqxluca/vggt_series_4_coop/docs/unified_eval_governance_plan.md`

---

## 1) 差异表（重点是“可比性/是否换题/能否接入同一治理闭环”）

| 维度 | FF-plan（fully_fair_v2xvit_core_benchmark_plan） | E21（coopVGGT eval_v2_1） | 影响/风险（本质） | 最小对齐策略 |
|---|---|---|---|---|
| 研究问题 | V2X 数据集上比较 **pose-correction** 方法是否提升 coop det | 多端多视角输入下，评估 **no-init 协同几何恢复** 是否能迁移提升 coop det | 两者都关心“几何→检测”，但输入/指标体系不同，直接对齐容易换题 | 用“两层门禁”合并：FF 的 preflight/validity gate + E21 的 route-decision gate |
| 输入契约 | 以 HEAL/opencood pipeline 的 stage1/online runtime 为主；强调同一数据集内语义冻结 | 允许：RGB+端内相机参；禁止：GT 外参/GT 深度注入推理；M1 可用 GPS/里程计但需记录噪声 | 若把 FF 的结果硬塞进 E21，会出现“指标字段缺失/语义不一致”的不可比 | 先做到 E21 的 bundle/manifest 合规（G0），再讨论是否能过 G1/G2/G3 |
| Matrix 轴 | 0..10（pos/rot paired sweep）+ comm-range gating（clean/noisy）+ 方法集合 | pack（smoke10/dev100/report500）+ mode（M0/M1）+ noise（N0..N3, 含 outlier）+ dropout（D0..D2）+ seeds | 噪声分布与扰动轴不一致，会改变“鲁棒性曲线”与方法排序 | 明确一套映射（例如把 FF 的某些噪声点映射到 N0/N2/N3），并在 manifest 记录映射假设 |
| 可比性冻结强度 | 强：固定 checkpoint+stage1+runtime/comm-range 语义，只替换 pose-correction | E21 协议里写了 comparable_redlines，但 validator/gate 主要做字段/合法性/红线；不强制所有可比性项一致 | FF 强调“科研公平”；E21 强调“治理/可审计”。若只按 E21，仍可能出现 confound | 把 FF 的 freeze 字段补进 E21 manifest（额外字段可存在），并在看板 Task 中把 freeze 当作 DoD |
| 指标集合 | AP30/50/70 + rel_trans/rel_yaw/success@{xm} + timing；不含 depth/scale | 需要对象级 Pose/Depth/Scale + AP@0.5/0.7 + robust_score | v2xreg_private 当前缺 depth/scale → **不可能**过 E21 的 G1/G2（除非补齐计算） | 先做“validator-pass 的 legacy bundle（Blocked 但可追溯）”，再决定是否投入补 depth/scale |
| Gate 体系 | stage1 结构/语义 gate + no-op gate（applied_count） | G0 合规；G1 几何/深度/尺度阈值；G2 抗性阈值；G3 相对 baseline 的最小增益 | FF 的 gate 更像“跑法有效性”；E21 的 gate 更像“路线决策门槛” | 两套 gate 都保留：FF gate 作为本地 preflight；E21 gate 作为云端决策 |
| “no-init”语义 | FF 目标是 core(no-init/no-prior) pose-correction 对比 | E21 明确有 M1（GPS/odometry init） | 若把 M1 与 no-init 混合，会把 prior 收益误归因到方法 | 项目管理上把 M0 与 M1 视为两条路线；所有结论必须标注 M |
| 交付物/看板闭环 | 以本仓 `outputs/*` 为 SoT（manifest/results/plots） | 以标准 bundle 为 SoT：validate → gate → leaderboard → project sync | 只要没有 bundle，就无法进入 E21 的治理闭环（无法自动上板/上榜） | 增加 exporter，把本地结果导出为 E21 bundle（哪怕先是 legacy/Blocked） |

---

## 2) “本质关系”怎么串（科研拆解 × 工程规范）

把两套体系放在一起，核心关系其实很简单：

1) **科研链路（What to prove）**：几何恢复（Pose/Depth/Scale）是否能稳定迁移到下游 coop det（AP），并在噪声/掉线下保持退化可控；  
2) **工程链路（How to trust）**：同一协议下可比（freeze/redline）→ 产物可审计（bundle）→ 门禁可复核（gates）→ 决策可回溯（leaderboard + project sync）。

FF-plan 更强在 (1) 的“公平对比设计”和本地 validity gate；E21 更强在 (2) 的“统一治理闭环”。

---

## 3) 可执行 Action List（按优先级；先“接入治理闭环”，再追求 GatePassed）

### A0) 明确你要的“融合”是哪一层

- **层 1（项目管理融合）**：把本机任务/阻塞/结论同步到 Track1 Project（Epic/Task/Run），不强求 GatePassed。  
- **层 2（评测协议融合）**：把本机产物导出为 E21 bundle，至少能 validate，通过 G0（ComparablePass=T1）。  
- **层 3（路线决策融合）**：补齐 E21 所需的对象级 Depth/Scale/Robustness 指标，使 run 有机会过 G1/G2/G3（DevDecisionPass=T2）。

### A1) 先做“可上板”的最小产物：export → validate → gate（预计 0.5~1 天）

在 `v2xreg_private` 用过渡 exporter（`tools/export_transition_bundles_to_eval_v2_1.py`），把本机的结果（例如 `outputs/*/results_ap50_from_yaml.json`）导出成：

```
<out>/<run_id>/
  manifest.yaml
  metrics_geometry.csv
  metrics_detection.csv
  metrics_robustness.csv
  summary.md
  visuals/html/scene_overview.html
  visuals/png/bev_overlay.png
  visuals/png/depth_fg_error.png
```

然后直接用 E21 官方脚本跑：

```bash
python /home/qqxluca/vggt_series_4_coop/scripts/validate_eval_bundle.py --bundle <out>/<run_id>
python /home/qqxluca/vggt_series_4_coop/scripts/compute_gate_status.py --bundle <out>/<run_id>
```

预期：由于缺 depth/scale，Run 很可能是 `Blocked`（这不是失败，而是“已纳管”）。

### A1.1 执行订正（2026-03-04，已完成）

已按上面的过渡方案完成一次本机到云端的“先纳管后补齐”（并对导出语义做了温和订正，使其更接近 E21 的可比性表达）：

- 本机导出并写入 `vggt_series_4_coop/eval_runs/inbox/local_transition/` 共 5 个 bundle（OPV2V 1 + DAIR 2 + V2V4Real 2）。
- 已完成 `validate -> gate`，5 个 run 都是 `Blocked`（原因符合预期：`legacy_geometry_proxy=true` + depth/scale 缺失 + 部分鲁棒阈值不满足）。
- 订正点（不改变“过渡期”定位）：`dataset_root` 避免机器路径；`split_file=frames_proxy.json`；`frames_json_sha256=sha256(frames_proxy.json)`，用于让 hash 表达“评测输入契约”而不是 hash 结果文件。
- 已按过渡命令同步到 Project #2：`--sync-mode minimal --gate-status-filter all --include-packs dev100 report500 --limit 5`，同步结果 `updated=5 skipped=0`（只同步本批 5 个）。

这表示：**当前“管理融合”已落地，且不会误导为“路线已通过定稿门禁”**。

### A2) 再做“能过 gate 的科研补齐”（这是是否值得投入的关键决策）

如果你希望本机路线真正进入 E21 的 T2/T3：
- 需要补齐 E21 的对象级 `depth_*` 与 `scale_err_*` 指标计算（或接入能产出这些指标的几何模型/评测管线）。  
- 同时要补齐鲁棒指标（`ap_drop_n3`、`pose_tail_obj_p95_n3` 与 degrade_ratio）并提供 baseline AP（用于 G3）。

这一步是实质性研发工作，不是“改格式”能解决的。

---

## 4) 一句话结论（方便贴到 Project/Issue）

FF-plan 是“把 pose-correction 在 V2X 数据集上做完全公平对比”的科研合同；E21 是“把 no-init coop perception 的评测做成可审计闭环”的治理合同。要做“上传融合”，先把本机结果导出成 E21 bundle 接入 validate/gate（哪怕先 Blocked），再决定是否投入补齐 depth/scale/robustness 以进入 T2/T3。
