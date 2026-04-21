# LiDARReg/HKUST 退化为 No-op 的根因链路 + 复跑判定（2026-02-24）

这份文档回答你反复追问的核心点：

- 为什么一些 `lidarreg_* / hkust_*` 的曲线会 **完全等于 baseline**（看起来“配准没有意义”）？
- 这到底是方法本身不行，还是 wiring / dataloader / 版本混写导致的 **silent no-op**？
- 现在应不应该停、哪些结果应判无效、复跑以什么条件验收？

目标是给出**可验证的逻辑链**（代码路径 + 产物证据），并给出可执行的复跑判定标准。

---

## 1) 结论（你现在要做的判断）

1. **“曲线等于 baseline”本身不等于“方法本体无增益”**：它很可能是 **no-op**（根本没 apply pose update）。
2. **no-op 有两类常见成因**（可从产物验证）：
   - **A. payload 缺失 / 注入失败**：online `lidar_reg` corrector 拿不到 per-CAV raw points，直接早退；
   - **B. 安全门限拒绝 apply**：payload 有，但质量/门限导致 apply 率为 0（此时通常 `match_sec` 不会接近 0）。
3. 你之前拿来对比的 OPV2V `opv2v_autopilot_full_20260216_auto3_a1` run_id **确实存在 mixed-version + mixed-env**，且部分点呈现典型 no-op 证据（见第 2 节），因此**不应作为最终全矩阵对比的依据**。

---

## 2) 证据：哪些点是“典型 no-op”

### 2.1 旧 run_id 的“断档一致”样例（AP 完全相同 + `match_sec` 极小）

同一个噪声点（n=1.0），`lidarreg_ransac` 与 `hkust_teaser` 产出**完全一致**，且 `match_sec≈1e-3`：

- `HEAL/opencood/logs/freealign_repro_opv2v_baseline/AP030507_lidar_reg_initfree_opv2v_autopilot_full_20260216_auto3_a1_lidar_noise10_lidarreg_ransac_best_n1.0.yaml`
- `HEAL/opencood/logs/freealign_repro_opv2v_baseline/AP030507_lidar_reg_initfree_opv2v_autopilot_full_20260216_auto3_a1_lidar_noise10_hkust_teaser_best_n1.0.yaml`

这类现象符合“没真正跑注册 / 直接早退”的特征：  
若真的执行了 FPFH+全局法+ICP，`match_sec` 不应接近 0。

### 2.2 统一 smoke 的“确实跑起来”样例（`match_sec` 大 + applied>0）

在统一 smoke（同 run_id 合同快照）下，`hkust_teaser` 明显有较大的 `match_sec` 且 `pose_provider_applied_count>0`：

- `outputs/full_bench_opv2v_unified_smoke_20260223_fix1/config_snapshot.json`
- `HEAL/opencood/logs/freealign_repro_opv2v_baseline/AP030507_lidar_reg_initfree_opv2v_unified_smoke_20260223_fix1_lidar_noise10_hkust_teaser_best_n1.0.yaml`

这说明：在正确 wiring + 同口径条件下，`hkust_*` 并非“必然等于 baseline”；  
等于 baseline 的点应该首先怀疑 no-op，而不是先下“方法无效”结论。

---

## 3) 机制层面：从 batch 到 AP 的完整早退链路（可复核）

下面是你要的“验证过的逻辑链”，每一步都能在代码里定位到：

### Step 0: inference 运行时会启用 pose_provider（online backend）

入口（以 OPV2V fullbench 为例）：
- `tools/run_opv2v_fullbench_fast.py` 调用 `HEAL/opencood/tools/inference_w_noise.py`
- `HEAL/opencood/tools/inference_w_noise.py` 在 `--solver-backend online_*` 时写入 `hypes["pose_provider"]`

### Step 1: pose_provider runtime 构造 `base_data_dict`

代码：
- `HEAL/opencood/utils/pose_provider_runtime.py`：`_apply_online_solver_to_batch(...)`

它会根据 batch 的 `record_len/cav_id_list/lidar_pose/...` 构造：
- `base_data_dict[cav_id]["params"]["lidar_pose"]`
- （可选）`base_data_dict[cav_id]["lidar_np"]`（LiDAR raw points payload）

### Step 2: 当 method==`lidar_reg` 时，runtime 需要注入 per-CAV raw points

代码：
- `HEAL/opencood/utils/pose_provider_runtime.py`：`_maybe_attach_online_lidar_payload_from_vsa(...)`

它只会从以下字段尝试拿 points：
- `batch["lidar_np_by_cav"]`（最常用）
- 或 `batch["origin_lidar_for_vsa"]`（某些 2-stage/VSA 变体）

如果 points 没注入成功（且 require_payload=False），此函数会返回 False，runtime 继续走下去，但 corrector 将拿不到 `lidar_np`。

### Step 3: Stage1LidarRegPoseCorrector 在 `lidar_np` 缺失时会直接早退

代码：
- `HEAL/opencood/extrinsics/pose_correction/stage1_lidar_registration.py`：`Stage1LidarRegPoseCorrector.apply(...)`

关键早退条件：
- `ego_entry.get("lidar_np") is None` → `return False`
- 或任意 cav `cav_entry.get("lidar_np") is None` → 跳过该 cav，最终可能 `updated_any=False`

### Step 4: 没有 apply pose update → pairwise/融合不变 → AP 等于 baseline

当 corrector `apply(...)` 返回 False：
- runtime 不会写回更新后的 `lidar_pose`
- downstream 使用的 pairwise 仍来自 noisy pose（或原始 pose_source）

因此协同感知 AP 曲线会与 baseline 完全一致。

### Step 5: no-op 的“产物信号”

在新 schema 下（已落地）：
- `HEAL/opencood/utils/pose_provider_runtime.py` 会写入 `pose_timing.pose_provider_applied_count`（0/1）
- 聚合脚本会把它归一为 `pose_applied_count`，用于过滤/告警 no-op 线

在旧 schema 下缺失该字段时，可用 **`match_sec` 极小** + **AP/误差逐点完全一致** 作为强证据。

---

## 4) 为什么“points 注不进去”（你问的关键）

历史上至少有两种真实发生过的原因：

1) **老版本 dataloader 根本不导出 `lidar_np_by_cav`**
   - 这会导致 online `lidar_reg` payload 直接缺失 → corrector 早退 → no-op。

2) **导出语义错误地绑定在 `visualize` 上**
   - 某些脚本/评估链路默认 `visualize=False`，即使启用 online `lidar_reg` 也拿不到 points → silent no-op。
   - 该点已在 2026-02-24 修复：当 `pose_provider.enabled && online_method==lidar_reg` 时，
     即使 `visualize=False` 也会导出 `lidar_np_by_cav`。

对应代码修复（HEAL 子模块）：
- `HEAL/opencood/data_utils/datasets/intermediate_fusion_dataset.py`
- `HEAL/opencood/data_utils/datasets/intermediate_heter_fusion_dataset.py`

对应 commit（本仓）：
- HEAL：`8c17149`（datasets: export raw lidar payload for online lidar_reg）
- 主仓：`92d18fb`（docs+scripts: fix lidar_reg payload provenance + cache helper）

---

## 5) 复跑判定（你该不该“停/重来”）

如果你关心 canonical 全矩阵（init/no-init/HKUST + AP + 配准）：

### 5.1 立即判无效 / 必须重跑的条件

满足任一条，就应判该方法线在该条件下 **无效（no-op）**：
- `pose_provider_applied_count == 0`（或聚合后的 `pose_applied_count` 全 0）
- 且/或 `match_sec` 极小（~1e-3 量级），同时 AP/误差逐点与 baseline 完全一致
- 同一 run_id 内存在 mixed-env / mid-run 修复混写（无法保证同口径）

### 5.2 可以保留参考（但仍建议统一复跑）的条件

以下信号都满足时，该点至少不是 wiring no-op：
- `pose_provider_applied_count > 0`
- `match_sec` 显著 > 0（对 lidar_reg/hkust 往往是秒级）
- `config_snapshot.json` 显示 git/heal commit 与 env 冻结一致

---

## 6) 下一步建议（最省返工）

1) **先把 OPV2V lidar_reg/hkust cache 做成 full 版**
   - 目前 `data/OPV2V/lidar_reg_cache/opv2v_test_*.json` 仍是 smoke（meta 里 `max_samples=5`）。
   - fullbench 建议先缓存，否则 40 个噪声点会重复算同一份点云注册，成本爆炸。
   - 入口脚本：`scripts/precompute_opv2v_lidarreg_caches.sh`

2) **然后在 git clean + 冻结 comm-range gating 的条件下启动新的 unified run_id**
   - 调度器：`tools/run_opv2v_fullbench_fast.py`
   - 聚合/出图：`tools/build_fullmatrix_benchmark_report.py`

