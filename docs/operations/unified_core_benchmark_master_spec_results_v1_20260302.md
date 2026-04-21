# Unified Core Benchmark Contract + Results Status (DAIR / OPV2V / V2V4Real)

更新：2026-03-02 (CST)

本文件是 **core benchmark 的唯一合同**。它负责：
- 把题目定义（语义冻结）写死，避免 single/oracle/online/offline/gating/noise 轴漂移
- 定义“可引用”的 Definition-of-Done（DoD）与 gates（PASS/FAIL）
- 审计现有 `outputs/` 资产：哪些能引用（PASS），哪些只能内部看（PARTIAL），哪些必须复跑（FAIL）
- 给出最小止损实验，建立 best-state（尤其 compare-current）证据链

执行层（10×3090 跑满、容错/Slurm）请看：`docs/operations/unified_core_benchmark_execution_plan_v3_20260301.md`。

2026-03-05 补充：更短、更“可执行”的统一跑数规范已收口为 runbook：`docs/operations/core_benchmark_runbook_v1_20260305.md`（推荐作为入口阅读）。

依赖的语义证据链：
- `docs/operations/benchmark_semantics.md`
- `docs/operations/fair_core_benchmark_setting_v1_20260301.md`
- `docs/operations/dataset_comm_range_and_gating_analysis_20260228.md`

---

## 0) One-page Contract（Goal / Scope / Decision）

### 0.1 Goal / Decision
在 **同一题目（语义冻结）** 下，对比 core(no-init/no-prior) 配准方法对协同感知检测 AP 的影响；用 bounds（baseline/single/oracle）给出上下界，避免误读。

### 0.2 Scope
- 数据集：DAIR-V2X / OPV2V / V2V4Real
- 模态：camera + lidar（V2V4Real 当前仓库仅 LiDAR checkpoint；camera 是扩展 lane，见 §9.3）
- 评估：下游检测 AP30/50/70（主指标），以及 `rel_error_stats`（配准旁证，不可替代 AP）
- 方法集合：见 §3（必须全覆盖）

### 0.3 Non-goals
- 不做跨数据集 AP 绝对值硬横比（只在各自数据集内看增益/排序；跨集只解释“趋势/机制/坑位”）
- 不把 audit 方法（with-init/prior、HKUST、imagematch、lidar_reg 等）并入 core 主结论

---

## 1) Source of Truth（source of truth / 唯一口径 / 完成判定）

对每个 dataset × modality × track，一个 `run_dir` 的 source-of-truth 必须包含：
- `manifest.json`（DAIR/V2V4Real core）或 `config_snapshot.json`（OPV2V fullbench）：语义冻结项必须齐（能反推“到底跑了什么”）
- `results_ap50_from_yaml.json`：长格式曲线点（entries = noise×method×strategy）
- `plots_yaml/*.png`：AP30/AP50/AP70 主图（`ylim=[0,1]`）+ core zoom（排除 single）
- `summary.md`：人类可读索引 + gate 结论（PASS/FAIL）

**DoD（可交付/可引用）** = 上述产物齐全 + §4 gates 全 PASS。

### 1.1 `results_ap50_from_yaml.json` schema（当前 canonical）
该 JSON 的 `entries[]` 每条点包含（字段名以实际输出为准）：
- `method`: `baseline|single|oracle_gt|v2xregpp|freealign|vips|cbm`
  - `strategy`: `bounds|best|stable`
  - `noise`: 字符串（例如 `"0.0"..."10.0"`）
  - `ap30/ap50/ap70`
- `samples`：该 noise 点评估的样本数（必须跨方法一致）
- `pose_provider_applied_count`：该 noise 点中“应用 pose update”的比例（0..1）
- `mean_rel_trans_m / mean_rel_yaw_deg / success_at_2m`：来自 YAML `rel_error_stats` 的聚合（旁证）
- `source_yaml`：可追溯到具体 AP030507 YAML

注：`manifest.json` 必须能回放 core 语义冻结（至少包含：`fusion_method/solver_backend/runtime_mode/pose_source/comm_range/comm_range_gating/noise_axis/num_workers`，以及 compare-current 阈值）。

---

## 2) 语义冻结（P0 红线）：baseline / single / oracle / online / gating / noise axis

任何 core 结论要可引用，必须满足本节。违反任意一条 = 变题 / 混语义（FAIL）。

### 2.1 baseline（coop，但不做 pose correction）
- baseline = `--pose-correction none`
- 仍然是 coop（多车融合），不是 single
- checkpoint/stage1/comm_range/gating/noise axis/solver_backend/runtime_mode 必须与 core 保持一致

### 2.2 single（唯一可比定义：single_ego_only）
- **唯一合法 single**：`single_ego_only = baseline + --force-ego-input-only`
- single **只跑 noise=0**，但出图时画成水平线
- 严禁 legacy：`--comm-range-override 0` 当 single（会改变 agent set/merged GT set，直接变题，甚至出现 `single > oracle`）
  - 证据：`docs/operations/benchmark_semantics.md#1-single`

### 2.3 oracle（必须精确命名是哪一种）
必须区分并在图例/表格中写死 token：
- `oracle_gt`：用 dataset `lidar_pose_clean` 覆盖非 ego pose；并在 online_box 路径显式 **禁噪** → **曲线应严格平线**
- `v2vloc_oracle_*`：从 stage1 cache 读 clean pose 覆盖（不一定禁噪/可能仍受裁剪抖动）→ **不保证平线**

禁止：图例/表格/results JSON 只写 “oracle”。

### 2.4 online vs offline（P0 红线）
core 主结论只允许：
- `--fusion_method intermediate --solver-backend online_box --runtime-mode register_and_fuse --pose-source noisy_input`

`offline_map` 只能用于 parity/调试（语义不同，可能把 noise 轴“禁噪”抹平）。

### 2.5 comm-range gating（必须显式 pin；禁止 auto）
通信范围裁剪（pruning）时用哪个 pose 计算距离：
- Track-D（Diagnostic）：`--comm-range-gating clean`（agent set 固定，更公平可解释）
- Track-S（System）：`--comm-range-gating noisy`（agent set 可能随噪声抖动，更贴近系统真实）

禁止：`--comm-range-gating auto` 用于 benchmark（会形成 cross-method confound）。

补充：gating 不仅影响输入 agent set，也会影响 merged GT（任务难度），并会影响 CBM/VIPS 的“可匹配 boxes 是否存在”。在**严格控制变量**（唯一差别=gating）的对照实验里，AP 差通常很小；历史观察到的“大差异”往往来自 confound（例如 `auto` 未 pin、V2V4Real head 子集偏置、compare gate 未 pin）。详见：  
`docs/operations/comm_range_gating_cbm_sensitivity_evidence_20260304.md`

### 2.6 noise axis（统一范围 + paired sweep + determinism）
- 统一噪声轴：`pos_std_list = rot_std_list = 0..10`（paired sweep）
  - canonical 离散点：`0,1,2,3,4,5,6,7,8,9,10`（任何更改都必须改 sweep 名称/单独 lane）
- `--sweep-mode paired --noise-target non-ego`
- 单位：`pos_std`=meters，`rot_std`=degrees（yaw）
- `HEAL/opencood/tools/inference_w_noise.py` 内部固定 seed=303（`random/np/torch`），理论上同 noise 点跨方法可比
- 为避免 dataloader/fork 污染随机序列：**必须 `--num-workers 0`**

### 2.7 Dataset freeze（comm_range 是题目的一部分）
同一张表/同一条曲线内，所有方法必须固定 comm_range：
- DAIR-V2X：100
- OPV2V：70
- V2V4Real（PASTAT checkpoint canonical）：70

若跑 V2V4Real `comm_range=200`（paper 常见），必须单独成一个 lane（标题/命名写死 `cr200`），禁止混入 canonical。

### 2.8 环境冻结（不写清就会“跑得出但结果不可信”）
- Python：必须用 `./.micromamba/envs/py39/bin/python`（系统 python 可能是 2.7）
- `PYTHONPATH=HEAL`（否则 `import opencood` 失败）
- 必须设置（建议在 sbatch/父进程 export；不要依赖“隐式默认”）：
  - `OPENCOOD_VOXEL_GPU=1`（否则在某些机器上会出现 inference 进入第一个 batch 直接崩掉的现象）
  - `OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1`, `OPENBLAS_NUM_THREADS=1`, `NUMEXPR_NUM_THREADS=1`（避免 CPU 线程数失控导致吞吐/稳定性问题）
  - OPV2V I/O 冻结：必须把 `inference_w_noise.py` 可视化落盘 **强降频**（默认 `--save_vis_interval=40` 会写大量 png，吞吐/配额风险）
    - 要求：命令包含 `--save_vis_interval 100000000`（每个 noise 仍会在 i=0 写 1 张；但不会爆盘/拖慢到不可用）
    - 如需“完全禁用”，需要补实现：当 `--save_vis_interval<=0` 时跳过写图逻辑
  - Slurm GPU 映射冻结：Slurm 常会重写父进程 `CUDA_VISIBLE_DEVICES`（slot->physical/UUID）
    - 要求：runner 内不要把 `CUDA_VISIBLE_DEVICES` 当“物理 GPU id”写死；job-array/部分 GPU 时必须做 slot->parent_visible 映射
    - 约定：runner 的 `--gpus` 默认语义是 **slot index**（0..N-1）；只有当你显式传入的值本来就在父进程 `CUDA_VISIBLE_DEVICES` 列表里时，才视为“物理/UUID”写法

---

## 3) 方法集合（core + bounds）与公平性约束

### 3.1 必跑清单（每个 dataset × modality × track）
- bounds：`baseline(none)` / `single_ego_only` / `oracle_gt`
- core(no-init/no-prior)：`v2xregpp_initfree` / `freealign_paper` / `vips_initfree` / `cbm_initfree`

### 3.2 no-init/no-prior 的硬定义
- VIPS/CBM：不启用 prior（`--vips-use-prior/--cbm-use-prior` 禁止开启）
- init_pose 只允许作为“缺失/遮挡时的附录对照”，不得混入 core 主表

### 3.3 方向一致性（cav->ego）
所有 stage1 corrector 约定：估计的相对变换 `T` 语义是 `(cav -> ego)`。方向错会系统性劣化。
已用回归测试锁死：
- `tools/tests/test_stage1_v2xregpp_compare_current.py`
- `tools/tests/test_stage1_freealign_compare_direction.py`
- `tools/tests/test_stage1_vips_cbm_direction.py`

---

## 4) Gates（Fail-fast：PASS/FAIL）

P0（阻塞 full canonical 的硬失败；FAIL=不可引用）
- G0 产物齐全：manifest/results/plots/summary
- G1 语义冻结：online_box + runtime_mode + pose_source + comm-range-gating pinned（非 auto）
- G2 single 合同：single 必须 `--force-ego-input-only` 且 noise=0 单点；禁止 comm_range=0
- G3 oracle 合同：oracle 必须标注具体 pose_correction；oracle_gt 应平线
- G4 noise axis：baseline/oracle/core 覆盖 0..10；single 仅 0
- G5 样本一致性：同 noise 点各方法 `samples` 一致
- G6 机制生效：非 bounds 方法在 noise>0 至少出现一次 `pose_provider_applied_count>0`（no-op gate）

P1（非阻塞但必须写进 summary.md 的显式标注）
- G7 best-state（noise=0 安全）：`ap50(method,0) >= ap50(baseline,0) - 0.01` 且 `success@2m >= 0.95`
- G8 V2V4Real smoke 抽样陷阱：若 `max_eval_samples` 子集几乎全是 record_len=1，会出现“所有方法曲线一样”的假阳性；对 `comm_range=70 & comm_range_gating=clean` 的 smoke200，必须加 `--eval-sample-start 294`（证据链：`docs/operations/comm_range_gating_cbm_sensitivity_evidence_20260304.md`）

---

## 5) Best-state（compare-current）证据链与止损实验结论

### 5.1 为什么 compare-current 会成为“最佳状态”坑？
只给 `--pose-compare-current`、不显式 pin compare gate 时，当前实现会把缺省阈值补成 `minimp=0.0 / mm=0 / current_precision=-1.0`（等价于“几乎不设门槛”），很容易出现：
- noise=0 仍大量 apply（bad-apply，破坏 clean pose → AP 下降）
- best-state gate 不可审计：不同 runner/版本补值策略一变就变题

关键事实（证据链）：
- `inference_w_noise.py` 在 compare-current 打开时会补默认阈值：  
  证据：`HEAL/opencood/tools/inference_w_noise.py:541-547`
- 当前 core runners 默认只传 `--pose-compare-current`，不传 compare gate pins → 实际就是 0/0/-1：  
  证据：`tools/run_dair_core_benchmark.py:481`、`tools/run_v2v4real_core_benchmark.py:467`、`tools/run_opv2v_fullbench_fast.py:377`

结论：canonical benchmark **必须显式 pin compare-current 阈值**（至少 pin：`pose_min_precision_improvement / pose_min_matched_improvement / pose_current_precision_threshold`），并写入 manifest（否则 best-state 不可审计、不可复现）。

### 5.4 补充证据：仅靠 `pose_current_precision_threshold` 不能“自动保护 noise=0”
DAIR LiDAR（Track-D clean, noise=0, max_eval_samples=200）：
- `cur_quality_th=2.9` 基本无效（applied≈0.73，AP50≈0.4145）  
  证据：`HEAL/opencood/logs/HeterBaseline_DAIR_lidar_v2xvit_2023_09_09_11_19_26/AP030507_v2xregpp_initfree_dair_smoke_curqual29.yaml`
- `cur_quality_th=2.0` 可以显著抑制 noise=0 bad-apply（applied≈0.09，AP50≈0.4617）  
  证据：`.../AP030507_v2xregpp_initfree_dair_smoke_curqual20.yaml`
- `cur_quality_th=1.8` 进一步接近 baseline（applied≈0.05，AP50≈0.4674；满足 `baseline-0.01` gate）  
  证据：`.../AP030507_v2xregpp_initfree_dair_smoke_curqual18.yaml`

结论：noise=0 的“current precision”本身并不接近满分（受 stage1 boxes 噪声影响），因此 `cur_quality_th` 必须调到较低才会生效；这会影响 noise>0 的 apply 分布。最终仍建议以 `minimp/mm` 为主门槛，并把阈值作为协议的一部分 pin 住。

结论：canonical benchmark **必须显式 pin compare-current 阈值**，并写入 manifest（否则 best-state 不可审计）。

### 5.2 最小止损实验：DAIR LiDAR（Track-D clean, noise=0, max_eval_samples=200）
固定条件（证据路径都在对应 YAML 中）：
- model：`opencood/logs/HeterBaseline_DAIR_lidar_v2xvit_2023_09_09_11_19_26`
- stage1：`data/DAIR-V2X/detected/lidar_v2xvit_stage1_percav/test/stage1_boxes.json`
- `online_box + comm-range-gating=clean + seed=303`

观测结论：阈值越严格，noise=0 的 applied 越少，AP 越接近 baseline；但过严可能让某些数据集高噪点方法趋向 no-op（需要跨数据集再校准）。

v2xregpp（noise=0）关键点（YAML 位于上述 model_dir 内）：
- (0.0,0)：AP50≈0.4148，applied≈0.73（见 `outputs/dair_core_dair_smoke_fixcompare_20260302a/lidar/results_ap50_from_yaml.json`）
- (0.1,1)：AP50≈0.4237，applied≈0.515（`AP030507_v2xregpp_initfree_dair_comparegate_test_minimp_comm100_lidar_v2xregpp_initfree.yaml`）
- (0.2,2)：AP50≈0.4335，applied≈0.335（`...minimp02_mm2...yaml`）
- (0.5,3)：AP50≈0.4522，applied≈0.15（`...minimp05_mm3...yaml`）
- (1.0,5)：AP50≈0.4702，applied≈0.035（`...minimp10_mm5...yaml`）

同条件下（noise=0, minimp=1.0/mm5）：
- freealign：applied=0 且 AP≈baseline（`AP030507_freealign_paper_dair_comparegate_noise0_minimp10_mm5_comm100_lidar_freealign_paper.yaml`）
- vips/cbm：applied 极低，AP 接近 baseline；但仍可能存在极少数长尾（mean 会被拉大，需看 `success@2m`/median/p90）

### 5.3 重要提醒：配准误差变小 ≠ AP 必然变好
DAIR LiDAR（Track-D clean, noise=10, max_eval_samples=200）：
- baseline：AP50≈0.2907，但 mean_rel_trans≈12.63m
- v2xregpp(minimp=1.0/mm5)：AP50≈0.2095，但 mean_rel_trans≈4.06m（更接近 clean）

结论：`rel_error_stats` 只能做旁证；core benchmark 结论必须以 AP 曲线为准。

---

## 6) 出图规范（DAIR/OPV2V/V2V4Real 统一）

### 6.1 轴与范围
- x 轴：0..10（必须含 0），`xlim=(0,10)`，`xticks=[0..10]`
- y 轴：主图固定 `ylim=(0,1)`
- 另输出 core zoom（排除 single 后自动缩放 y）

### 6.2 single/oracle 画法
- single：只跑 noise=0，但画成水平线
- oracle_gt：应严格平线；若不平，优先排查是否跑成 `v2vloc_oracle_*` 或混了 gating/noise 语义

### 6.3 plot 目录必须 clean
summarize 必须支持 `--clean-plot-dir`（避免旧图残留造成误导）。

---

## 7) 现有结果资产审计（PASS / PARTIAL / FAIL；带证据链）

### 7.1 DAIR-V2X

#### A) Track-S full（历史全量）
- run_dir：`outputs/dair_core_dair_core_unified_20260228/`
- 语义（从日志反推）：`online_box + comm-range-gating=noisy`  
  证据：`outputs/dair_core_dair_core_unified_20260228/lidar/logs/lidar_none_noise0.log:2`

PASS（可引用）
- camera/lidar：baseline / single_ego_only / oracle_gt  
  证据：`outputs/dair_core_dair_core_unified_20260228/*/manifest.json`

FAIL（不可引用）
- core：v2xregpp/freealign/vips/cbm（noise=0 安全 gate 未通过，且 noise=10 全面弱于 baseline）  
  证据：`outputs/dair_core_dair_core_unified_20260228/lidar/results_ap50_from_yaml.json`

#### B) Track-D smoke（止损验证）
- run_dir：`outputs/dair_core_dair_smoke_fixcompare_20260302a/lidar/`（gating=clean, noise=0, max_eval_samples=200）
- core 在 noise=0 仍退化（说明 compare-current 默认阈值过松 + 长尾问题真实存在）  
  证据：`outputs/dair_core_dair_smoke_fixcompare_20260302a/lidar/results_ap50_from_yaml.json`

### 7.2 V2V4Real
- run_dir：`outputs/v2v4real_core_v2v4real_noise10_comm70_20260227_062938/`（Track-S）

PASS / PARTIAL
- baseline/single：PASS（single=ego_only）  
  证据：`outputs/v2v4real_core_v2v4real_noise10_comm70_20260227_062938/manifest.json`
- oracle：PARTIAL（该 run 的 oracle 是 `v2vloc_oracle_initfree`，不是 oracle_gt）  
  证据：同上 manifest method_specs
- v2xregpp/freealign：PARTIAL（noise=10 有正增益；noise=0 仍有一定 drift，需要 best-state 定版后重跑 canonical）  
  证据：`outputs/v2v4real_core_v2v4real_noise10_comm70_20260227_062938/results_ap50_from_yaml.json`

FAIL
- vips/cbm（best/stable）存在明显长尾爆炸（mean 很大而 median≈0），不宜引用为“方法真实能力”  
  证据：同上 results_json + 对应 `source_yaml` 的 `rel_error_stats`

### 7.3 OPV2V
- run_dir：`outputs/full_bench_opv2v_autopilot_full_fixv2xregpp_20260225_065926_a1/`（Track-S）

PARTIAL（不满足 canonical 合同，但可用于内部趋势）
- 缺 noise=0：`outputs/full_bench_opv2v_autopilot_full_fixv2xregpp_20260225_065926_a1/config_snapshot.json`（noise_list=1..10）
- single 语义错误：single 实际是 legacy comm_range=0（不是 ego_only）  
  证据：`outputs/full_bench_opv2v_autopilot_full_fixv2xregpp_20260225_065926_a1/logs/lidar_noise10_single_bounds_n0.0.log:3`

---

## 8) 典型坑位：现象 -> 证据链 -> 修复

### 8.1 `single > oracle`（几乎必然是变题）
根因：把 `comm_range=0` 当 single，会改变 merged GT/agent set，使任务变容易。  
证据：OPV2V single log 明确 `--comm-range-override 0` 且无 `--force-ego-input-only`（见 §7.3）。

### 8.2 oracle 不平
若 oracle_gt 不平，优先判定为：
- 实际跑成了 `v2vloc_oracle_*`（不禁噪）  
- 或混入 `comm-range-gating auto`（cross-method confound）

### 8.3 三数据集 noisy gating 抖动程度差很多
根因：距离分布相对 comm_range 边界不同（near-boundary rate / dropout rate 不同）。  
证据：`docs/operations/dataset_comm_range_and_gating_analysis_20260228.md`

### 8.4 V2V4Real smoke “全线一样”
根因：抽样子集几乎全是 record_len=1（无邻居）→ coop 与 single 等价，pose correction 不会起效。  
证据：`outputs/v2v4real_core_v2v4real_smoke_fixcompare_20260302a/`

### 8.5 手跑 inference 直接崩掉（只打印到 Noise Added 就退出）
常见根因：没设置 `OPENCOOD_VOXEL_GPU=1`，触发某些 voxelization 路径不稳定。  
解决：按 §2.8 冻结环境（runner 已做；手跑必须对齐）。

---

## 9) 下一步：生成真正 canonical 的三数据集 core 曲线

1) 补 OPV2V canonical bounds：补 noise=0 + single_ego_only（禁止 comm_range=0）  
2) 三数据集统一生成 Track-D + Track-S（clean/noisy gating 分开跑、分开表）  
3) compare-current 阈值策略定版：  
   - 方案A：固定一套阈值（简单，但可能牺牲某些数据集高噪点增益）  
   - 方案B：每数据集先跑 calibration smoke（noise=0/10）选阈值，再全量（更稳；阈值必须写入 manifest 以便审计）  
4) 生成最终 plots + results_ap50_from_yaml.json + summary.md，并跑 gates（FAIL 则止损回滚到上一步）

### 9.1 推荐入口脚本（按数据集隔离，失败互不影响）
- DAIR：`tools/run_dair_core_benchmark.py`（已内置 summarize）
- V2V4Real：`tools/run_v2v4real_core_benchmark.py`（建议在 runner 末尾也内置 summarize）
- OPV2V：`tools/opv2v_benchmark_autopilot.py`（需要把 noise_list 包含 0，并启用 single_ego_only）

### 9.2 统一可视化脚本
- core curves：`tools/summarize_v2v4real_core_from_yaml.py`（DAIR runner 已复用同风格）
- OPV2V fullbench：`tools/summarize_opv2v_fullbench_from_yaml.py`

### 9.3 扩展 lane：V2V4Real backbone 对齐（可选）
如果你要求 DAIR/OPV2V/V2V4Real 尽量同 backbone（例如都用 V2XViT），需要：
- 在 V2V4Real 上补训/迁移 V2XViT（至少 LiDAR；camera 视实现与数据而定）
- 导出对应 per-CAV stage1 cache
- 在同一套语义合同下重跑 Track-D/Track-S
