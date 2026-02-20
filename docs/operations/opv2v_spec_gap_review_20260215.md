# OPV2V 规范缺口复盘（为什么“新规划”仍跑出垃圾结果）

Last updated: 2026-02-15

## 0) 结论（总）

不是你目标错，而是规范里少了 4 个“硬门槛”：

1) 没把 **camera stage1 结构合法性** 设为开跑前必过 gate。  
2) 没把 **suite 语义**（pose-noise vs no-extr）强制拆开。  
3) 没把 **checkpoint 健康度**（AP 下限）设为开跑前 gate。  
4) 没把 **offline_map vs online_box 语义** 显式写进运行命令和验收项。

结果就是：任务“跑完了”，但曲线在统计意义上是无效的。

---

## 1) 证据链（分层）

### A. 数据层（stage1 输入就不合法）

- camera stage1 校验失败：  
  `data/OPV2V/detected/opv2v_camera_v2xvit_stage1/test/stage1_boxes.json`  
  - samples=50（应为 2170）  
  - `len(cav_id_list)!=len(pred_corner3d_np_list)`（多样本）
- 直接命令证据：  
  `./.micromamba/envs/py39/bin/python tools/validate_stage1_cache.py --stage1 data/OPV2V/detected/opv2v_camera_v2xvit_stage1/test/stage1_boxes.json --expected-samples 2170 --require-contiguous-keys`

### B. 算法层（solver 实际没应用）

- camera pose solver 多方法 `applied==0`：  
  `HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/AP030507_v2xregpp_initfree_opv2v_fullbench_fast_20260212_camera_noise10_v2xregpp_best_n1.0.yaml`

### C. 实验语义层（噪声被设置抵消）

- LiDAR no-extr 模型带 `pose_override=zero`：  
  `HEAL/opencood/logs/freealign_repro_opv2v_baseline_noextr_v2xregpp/config.yaml:37`
- 这会让 pose-noise sweep 的 baseline 变平（不是画图 bug，是语义冲突）。

### D. 执行层（历史“完成度”口径不稳）

- 旧文档用 log grep 的 AP 行判定完成，重启+覆盖会误判。  
- 可信口径应为 `run_state.jsonl` 的 end/code=0（见 `docs/operations/opv2v_fullbench_evidence_20260214.md`）。

---

## 2) 规范修复（已落地）

已把规范与默认入口修到“更不容易再踩坑”：

1) `scripts/build_opv2v_stage1_cache.sh`
   - camera 默认改为 per-CAV 导出（`export_stage1_boxes_per_cav.py`）  
   - 导出后强制执行 `tools/validate_stage1_cache.py` gate  
   - lidar 默认模型改为非 no-extr：`freealign_repro_opv2v_baseline`

2) `scripts/run_opv2v_fullbench.sh`
   - 默认 camera stage1 改为 per-CAV 路径  
   - 默认 lidar model 改为非 no-extr 路径

3) `tools/run_opv2v_fullbench_fast.py`
   - 增加并透传 `--solver-backend/--runtime-mode/--pose-source` 到推理命令  
   - config snapshot 记录 backend 语义，避免“以为在线，实际离线”

4) 文档修订
   - `docs/operations/opv2v_fullbench_masterplan.md` 增加“止损级硬门槛”  
   - `docs/operations/opv2v_benchmark_repro.md` 更新默认路径与 gate  
   - `docs/operations/opv2v_fullbench_status_20260213.md` 补充口径风险说明

---

## 3) 止损执行单（下一轮按这个顺序）

1) 先重建并验证 stage1（camera/lidar 都必须过 2170+结构 gate）。  
2) 先做 1~2 个噪声点小样本 smoke（看 `applied` 是否非零）。  
3) 明确本轮是 A 还是 B：  
   - A: pose-noise robustness（禁止 no-extr）  
   - B: no-extr（不拿 noise sweep 解释鲁棒性）  
4) 再跑 fullbench，全程用 `run_state.jsonl` 作为完成判定。
