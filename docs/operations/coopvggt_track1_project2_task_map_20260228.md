# coopVGGT Track1 Project #2（eval_v2_1）到底在做什么：任务关联图 + 本机接入方式

更新：2026-02-28

## 0) 一句话

Track1 Project #2 的本质是把“多端多视角 → 几何恢复 → 协同检测”做成**统一协议、统一产物、统一门禁、可回溯决策**的闭环；看板上的 Task 不是随意堆叠，而是围绕这条闭环拆出来的依赖链。

Source-of-truth（本机控制面仓库）：
- 协议：`/home/qqxluca/vggt_series_4_coop/configs/eval_protocol_v2_1.yaml`
- Gate：`/home/qqxluca/vggt_series_4_coop/configs/eval_gates_v2_1.yaml`
- 治理闭环：`/home/qqxluca/vggt_series_4_coop/docs/unified_eval_governance_plan.md`
- T0~T3 判据：`/home/qqxluca/vggt_series_4_coop/docs/project_master_overview.md`

---

## 1) 看板任务为什么这样拆（研究链路 × 工程链路）

### 1.1 研究链路（你要证明什么）

1) 合规（不作弊）：不注入 GT 外参/深度；M0/M1 语义清晰；同 pack 同 frames。
2) 能力（几何能不能用）：对象级 Pose/Depth/Scale 达到门槛（G1）。
3) 抗性（噪声/掉线下是否崩）：AP_drop 与 pose tail 退化可控（G2）。
4) 迁移（几何是否真的帮助 det）：相对 baseline 至少 +0.01（G3）。

### 1.2 工程链路（你怎么让结论可信）

bundle 标准化 → validate（结构/字段/红线）→ gate（G0..G3）→ leaderboard（只收 GatePassed）→ project sync（Run/指标/阻塞写回看板）。

---

## 2) Task 之间的关键依赖（DAG / 关键路径）

**关键路径（能产生路线决策的最短路径）**
- Freeze packs（dev100/report500）→ Redline checklist → Unified decision rule（T2 gate）
- N3 robustness pack + metrics（否则 G2 不可算）
- DET-BRIDGE（否则“几何→det”链路不闭合，G3 不可解释）
- Line-A 或 Line-B：dev100 grid → geometry gate conclusion
- Dense vs Query compare（在至少一个 line 过 G1/G2 后）→ AP + RobustScore decision rule

**并行但必须存在的“控制面”链路**
- Define submission bundle spec → Auto-eval runner + queue → Leaderboard publish + snapshot（+ Anti-leak checks）

（seed 结构见：`/home/qqxluca/vggt_series_4_coop/configs/project_seed_v2_1.json`）

---

## 3) “Done” 到底意味着什么（避免 smoke10/单次 AP 误当结论）

以 T0~T3 分档（简写）：
- T0 ExecutionPass：脚本无报错、产物完整、可复跑（但不可决策）。
- T1 ComparablePass：通过 G0（合约 + 可比性红线），可进入可比集合（仍不可决策）。
- T2 DevDecisionPass：dev100 上通过 G0+G1+G2，且 G3 满足最小增益（允许阶段决策）。
- T3 ReportPass：report500 上通过 G0..G3 + 显著性复核（允许最终结论）。

这也是为什么看板里会把任务拆成：packs 冻结 / 红线清单 / N3 指标补齐 / DET-BRIDGE / grid 运行 / gate 结论 / dense-vs-query。

---

## 4) “把本机任务上传融合”怎么落地（最小可行 → 可决策）

你当前这台服务器上的主要资产在 `v2xreg_private`（本仓），但它的产物/指标与 E21 不是同一套。
要接入 Project #2，有三档方案：

### 4.1 档 A：只做项目管理融合（最省时）

- 把本机的关键任务拆成 Project 的 Task/Doc（不要求 bundle/gate）。
- 适合：你想先把“噪声”变成结构化任务树与阻塞列表。

### 4.2 档 B：做协议融合（能 validate/gate，但可能 Blocked）

做一个 exporter，把本机结果导出成 E21 bundle，然后跑：

```bash
python /home/qqxluca/vggt_series_4_coop/scripts/validate_eval_bundle.py --bundle <bundle_dir>
python /home/qqxluca/vggt_series_4_coop/scripts/compute_gate_status.py --bundle <bundle_dir>
```

预期：如果缺 depth/scale（v2xreg_private 当前通常缺），会在 G1/G2 阶段 Blocked；但 Run 变成“可审计、可同步”的实体。

### 4.3 档 C：做路线决策融合（目标 T2/T3）

- 需要补齐 E21 所要求的对象级 Depth/Scale/Robustness 指标计算与 baseline gain（G3）。
- 这属于“补评测/补链路”的研发投入，不是改格式。

---

## 5) 与 GitHub Project #2 的同步方式（不要手动填字段）

说明：Project #2 页面在未认证时会 404；同步靠 GraphQL（脚本已实现）。

建议 token 放在文件里，避免出现在 shell history：
- `/home/qqxluca/vggt_series_4_coop/gh_secrets`（被 `.gitignore` 屏蔽）

常用命令（先 dry-run 再执行）：

```bash
python /home/qqxluca/vggt_series_4_coop/scripts/project_seed_structure.py \
  --org coopVGGT --project-number 2 \
  --seed-file /home/qqxluca/vggt_series_4_coop/configs/project_seed_v2_1.json \
  --token-file /home/qqxluca/vggt_series_4_coop/gh_secrets \
  --dry-run

python /home/qqxluca/vggt_series_4_coop/scripts/project_sync_github.py \
  --org coopVGGT --project-number 2 \
  --token-file /home/qqxluca/vggt_series_4_coop/gh_secrets \
  --dry-run
```

