# Docs Index (2026-02-13)

更新: 2026-02-20  
状态: 索引已人工补充；部分内容仍需核验  

## 说明

该索引列出 `docs/operations/` 下的文档与当前审阅状态。  
若未审阅，将标记为 `unreviewed`，避免误用。  

## 已审阅 / 相关

- `docs/operations/MASTER.md`
  - 当前仓库的“唯一入口”索引：目标链路、可信产物、与下一步 fullmatrix 收敛路径。
- `docs/operations/WORKTREE_STATE.md`
  - 私有工作树当前状态 + 可信入口（建议从这里开始）。
- `docs/operations/repo_hygiene.md`
  - 多仓库/子模块的 git 工作流与保存规范。
- `docs/operations/run_template.md`
  - 任何“真实 run”都建议按此模板记录，避免后续考古。
- `docs/operations/opv2v_fullbench_masterplan.md`  
  - OPV2V 全量 benchmark 需求、计划与当前进度（AI 草案，需人工核验）。
- `docs/operations/opv2v_fullbench_status_20260213.md`  
  - OPV2V 执行复盘与证据链摘要（AI 草案，需人工核验）。
- `docs/operations/opv2v_benchmark_repro.md`  
  - OPV2V benchmark 复现流程（环境/缓存/运行方式）。
- `docs/operations/benchmark_execution_status_20260219.md`
  - 最近一次 benchmark 执行状态（完成证据链 + 关键结果）。
- `docs/operations/config_experiment_map_20260220.md`
  - 配置簇 -> 实验目的 -> 最新结果 的统一索引。
- `docs/operations/unified_benchmark_contract_and_comparison_20260220.md`
  - 统一条件下的 AP+配准主对比（含覆盖校验与有/无初值分组）。
- `docs/operations/fullmatrix_init_noinit_hkust_benchmark_status_20260220.md`
  - 全矩阵（有初值/无初值/HKUST）补跑与统一出图执行状态。
- `docs/operations/opv2v_append_partial_results_20260222.md`
  - OPV2V append（init/no-init/HKUST）阶段性结果 + 关键 sanity checks（含 env 混用提示）。
- `docs/operations/imagematch_initfree_remote_audit_20260223.md`
  - 在远端统一条件下验证 imagematch_initfree 的“是否真正生效”与“断档领先是否为假象”。
- `docs/operations/opv2v_unified_fullbench_plan_20260223.md`
  - OPV2V 全矩阵最终版的 plan contract + preflight + smoke/full 启动记录。
- `docs/operations/experiment_progress.md`  
  - 大型实验进度汇总（较长，含历史结果与偏差分析）。
- `docs/operations/heal_pose_fusion_execution_playbook.md`  
  - HEAL pose+fusion 运行流程（执行手册）。
- `docs/operations/heal_pose_fusion_unified_arch.md`  
  - HEAL 架构方案（设计文档）。

## 未审阅（仅列出文件名）

- `docs/operations/_debug_head200_ap50.png`
- `docs/operations/code_inventory.md`
- `docs/operations/dataset_adaptation_non_invasive.md`
- `docs/operations/experiment_reproduction.md`
- `docs/operations/heal_detection_status.md`
- `docs/operations/heal_noinit_online_heter_fusion_design.md`
- `docs/operations/heal_pose_alignment_noise_robustness.md`
- `docs/operations/heal_pose_alignment_stable_noise_sweep.md`
- `docs/operations/heal_pose_fusion_docs_index.md`
- `docs/operations/heal_single_agent_report.md`
- `docs/operations/hkust_vs_v2icalib_report.md`
- `docs/operations/pose_registration_survey.md`
- `docs/operations/ppsc_paper3737_repro_20260111.md`
- `docs/operations/release_curation_plan.md`
- `docs/operations/repo_transfer.md`
- `docs/operations/svd_correspondence_supplement.md`
- `docs/operations/table3_paper3737_repro_status.md`
- `docs/operations/table3_paper3737_repro_status_te.md`
- `docs/operations/v2icalib_feature_extension.md`
- `docs/operations/v2v4real_comm200_ap50_noise_curve_mix.png`
- `docs/operations/v2v4real_comm200_ap50_noise_curve_stable.png`
- `docs/operations/v2v4real_extrinsic_sweep_comm200_paper_ap.png`
- `docs/operations/v2v4real_extrinsic_sweep_comm200_paper_ap50.png`
- `docs/operations/v2v4real_extrinsic_sweep_comm200_paper_ap50_stable.png`
- `docs/operations/v2v4real_noise_sweep_methods.md`
- `docs/operations/v2vloc_heal_repro.md`
- `docs/operations/v2x_factor_reval.md`
- `docs/operations/v2x_regpp_optimization.md`
- `docs/operations/v2xregpp_midfusion_occ_hint.md`

## 后续建议

1) 按主题合并与去重，避免“文档熵增”。  
2) 设定唯一入口文档，并在文档头部标注“最后更新时间 + 责任人”。  
