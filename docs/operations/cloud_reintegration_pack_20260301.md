# Cloud Re-integration Pack (Server -> coopVGGT Project #2) — 2026-03-01

目标：把这台服务器上“真实存在的 benchmark/产物/阻塞”，去噪后整理成一组**可上云端 Project #2 追踪**的 Epic/Task/Run（不依赖你记忆、也不依赖旧文档是否写过）。

本 pack 只引用本机事实（`outputs/` 扫描结果）：`docs/operations/server_benchmark_inventory_20260301.md`。

---

## 1) 去噪后的“本机真实主线”（你现在到底做了哪些 bench）

### 1.1 OPV2V（fullbench：noise10 + drop20，camera+lidar）

**最关键的“全量”跑：**
- `outputs/full_bench_opv2v_autopilot_full_fixv2xregpp_20260225_065926_a1/`
  - 语义冻结：`solver_backend=online_box`, `runtime_mode=register_and_fuse`, `pose_source=noisy_input`, `comm_range_gating=noisy`（见 `config_snapshot.json`）
  - 方法集：`v2xregpp/freealign/vips/cbm`（含 baseline/oracle/single）

这条线在云端应当对应：
- **Run 卡片**：OPV2V canonical full（作为后续“结论引用”的证据入口）
- **Task 卡片**：把它导出成云端 eval_v2_1 bundle（否则云端无法自动审计/上榜/对比）

### 1.2 DAIR（core unified：0..10 + single ego-only）

**最关键的“统一 core”跑：**
- `outputs/dair_core_dair_core_unified_20260228/camera/`
- `outputs/dair_core_dair_core_unified_20260228/lidar/`
  - 噪声：0..10（含 0）
  - single：`--force-ego-input-only`（同 GT set 语义）
  - 方法集：`none/single/oracle + v2xregpp/freealign/vips/cbm`

这两条在云端应当对应：
- **Run 卡片 x2**：DAIR core unified (camera/lidar)

### 1.3 V2V4Real（stage1 per-CAV export + core runs）

**关键“前置阻塞被解决”的证据：**
- `outputs/v2v4real_stage1_export_v2v4real_stage1_full_20260226_221653/`
  - 输出目录指向 per-CAV stage1：`HEAL/opencood/logs/v2v4real_stage1_pointpillar_from_pastat_bestval17_percav`（见 manifest）

**关键 core 跑（noise10）：**
- `outputs/v2v4real_core_v2v4real_noise10_comm200_20260227_062938/`
- `outputs/v2v4real_core_v2v4real_noise10_comm70_20260227_062938/`

这组在云端应当对应：
- **Task 卡片**：V2V4Real stage1(per-CAV) 已完成（可引用证据）
- **Run 卡片 x2**：V2V4Real core noise10 (comm200/comm70)

---

## 2) 云端 Project #2 里应该出现什么（最小集合）

下面是“最少但够用”的上云集合；超过这个集合的历史跑法先不搬，避免云端噪声炸掉。

### 2.1 Runs（证据入口）

- OPV2V:
  - `full_bench_opv2v_autopilot_full_fixv2xregpp_20260225_065926_a1`
- DAIR:
  - `dair_core_unified_20260228 (camera)`
  - `dair_core_unified_20260228 (lidar)`
- V2V4Real:
  - `v2v4real_stage1_full_20260226_221653`（这是“前置产物”，也建议作为 Run 或 Doc）
  - `v2v4real_noise10_comm200_20260227_062938`
  - `v2v4real_noise10_comm70_20260227_062938`

### 2.2 Tasks（把“本机跑过”变成“云端可决策”的缺口）

1) **Export/Adapter：v2xreg_private -> eval_v2_1 bundle**
   - 目的：让上述 Runs 在云端可 validate/gate/上板（哪怕先 Blocked，也能变成“可审计事实”）。
2) **Protocol reconciliation（FF-plan vs eval_v2_1）**
   - 目的：明确“本机 noise 0..10”如何映射到云端 `N0..N3`，以及 depth/scale 缺失如何处理（补指标 or 协议扩展）。
3) **GitHub Project Sync 的 token/权限修复**
   - 目的：让自动写回 Project #2 可用；否则只能生成手工 TODO。

---

## 3) 执行结果回填（2026-03-04）

已按“先管理融合，再补评测链路”的过渡方案执行：

### 3.1 已导出并纳管的本机 run（5 个）

- `20260303_234522_v2xtransfullbencho009cad5bb2_dev100_M0_N2_D0_0`（OPV2V full）
- `20260303_234522_v2xtranscamera01c9cb60b1_dev100_M0_N2_D0_0`（DAIR camera）
- `20260303_234522_v2xtranslidar024da2675e_dev100_M0_N2_D0_0`（DAIR lidar）
- `20260303_234522_v2xtransv2v4realco03a5089ccf_dev100_M0_N2_D0_0`（V2V4Real comm200）
- `20260303_234522_v2xtransv2v4realco042473d27e_dev100_M0_N2_D0_0`（V2V4Real comm70）

导出器：`tools/export_transition_bundles_to_eval_v2_1.py`

本次（2026-03-04）对导出语义做了“去机器路径化 + 可比性占位”的修正（仍保持过渡期属性）：
- `dataset_root`：使用稳定 token（如 `data/DAIR-V2X`），避免落到本机 `HEAL/opencood/logs/...` 这类模型目录。
- `split_file=frames_proxy.json`：生成临时 proxy 文件用于描述 split 语义（真实 frames 列表待后续补齐）。
- `frames_json_sha256=sha256(frames_proxy.json)`：让 hash 对“评测输入集合/契约”更有意义，而不是 hash 结果文件本身。

### 3.2 Gate 结论（与预期一致）

- 5/5 均为 `Blocked`。
- validate：5/5 为 `VALID`（结构/字段满足 eval_v2_1）。
- gate：共性原因仍是 `legacy_geometry_proxy=true`（过渡标记，直接挡在 G0）+ `depth/scale` 占位未补齐（G1 不可能通过）。
- 这批 run 的定位是“过渡追踪证据”，不是路线定稿依据。

### 3.3 Project #2 同步结果

- 采用过渡态命令（低噪声 + 可追踪）：`--sync-mode minimal --gate-status-filter all --include-packs dev100 report500`
- 执行结果（2026-03-04）：先执行一次未限流同步 `updated=6, skipped=0`（额外带上了 gate report 目录里的 1 个历史 dev100）；随后按“只同步本批”补跑：`--limit 5`，结果 `updated=5, skipped=0`。

---

## 4) 后续最小增量（保持和 Key-Only 兼容）

1) 继续让重跑中的 dev100 作为 provisional canonical（同数据集最多 1 个）。  
2) 只要 report500 GatePassed 出来，替换 provisional canonical。  
3) depth/scale/robustness 指标链路补齐后，再切回稳定态（只保留 report500 + GatePassed 的 canonical Run）。
