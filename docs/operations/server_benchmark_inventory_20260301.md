# Server Benchmark Inventory (2026-03-01)

这份清单是从 `outputs/` 自动扫描生成的（去掉了“只在脑子里/只在 tmux 里”的信息丢失）。

## 1) Fullbench Runs (OPV2V-style)

| run_id | timestamp | modalities | sweeps | comm_range_gating | solver/runtime | methods | run_dir |
| --- | --- | --- | --- | --- | --- | --- | --- |
| opv2v_autopilot_full_fixv2xregpp_20260225_065926_a1 | 2026-02-25T07:03:36 | camera,lidar | noise10,drop20 | noisy | online_box/register_and_fuse | v2xregpp,freealign,vips,cbm | `/home/qqxluca/projects/v2xreg_private/outputs/full_bench_opv2v_autopilot_full_fixv2xregpp_20260225_065926_a1` |
| opv2v_autopilot_smoke_fixv2xregpp_20260225_065926_a1 | 2026-02-25T06:59:32 | camera,lidar | noise10 | noisy | online_box/register_and_fuse | v2xregpp,freealign,vips,cbm | `/home/qqxluca/projects/v2xreg_private/outputs/full_bench_opv2v_autopilot_smoke_fixv2xregpp_20260225_065926_a1` |
| opv2v_autopilot_smoke_after_20260225_034525_20260225_062114_a2 | 2026-02-25T06:25:24 | camera,lidar | noise10 | noisy | online_box/register_and_fuse | v2xregpp,freealign,vips,cbm | `/home/qqxluca/projects/v2xreg_private/outputs/full_bench_opv2v_autopilot_smoke_after_20260225_034525_20260225_062114_a2` |
| opv2v_autopilot_smoke_after_20260225_034525_20260225_062114_a1 | 2026-02-25T06:21:19 | camera,lidar | noise10 | noisy | online_box/register_and_fuse | v2xregpp,freealign,vips,cbm | `/home/qqxluca/projects/v2xreg_private/outputs/full_bench_opv2v_autopilot_smoke_after_20260225_034525_20260225_062114_a1` |
| opv2v_autopilot_smoke_20260225_034525_a2 | 2026-02-25T03:53:47 | camera,lidar | noise10 | noisy | online_box/register_and_fuse | v2xregpp,freealign,vips,cbm | `/home/qqxluca/projects/v2xreg_private/outputs/full_bench_opv2v_autopilot_smoke_20260225_034525_a2` |
| opv2v_autopilot_smoke_20260225_034525_a1 | 2026-02-25T03:45:41 | camera,lidar | noise10 | noisy | online_box/register_and_fuse | v2xregpp,freealign,vips,cbm | `/home/qqxluca/projects/v2xreg_private/outputs/full_bench_opv2v_autopilot_smoke_20260225_034525_a1` |
| zz_cache_fullness_test_20260224 | 2026-02-24T02:50:17 | lidar | noise10 | noisy | online_box/register_and_fuse | hkust_teaser | `/home/qqxluca/projects/v2xreg_private/outputs/full_bench_zz_cache_fullness_test_20260224` |
| opv2v_autopilot_full_20260216_auto3_a1 | 2026-02-23T21:56:08 | camera,lidar | noise10,drop20 | auto | online_box/register_and_fuse | vips_prior,cbm_prior,imagematch_noinit,imagematch_current,lidarreg_ransac,hkust_teaser,hkust_fgr,hkust_quatro | `/home/qqxluca/projects/v2xreg_private/outputs/full_bench_opv2v_autopilot_full_20260216_auto3_a1` |
| opv2v_unified_smoke_20260223_fix1 | 2026-02-23T17:38:51 | camera,lidar | noise10 | noisy | online_box/register_and_fuse | imagematch_noinit,imagematch_current,lidarreg_ransac,hkust_teaser | `/home/qqxluca/projects/v2xreg_private/outputs/full_bench_opv2v_unified_smoke_20260223_fix1` |
| opv2v_camera_occhint_full_20260219_a1 | 2026-02-19T02:39:17 | camera | noise10,drop20 | None | online_box/register_and_fuse | v2xregpp,v2xregpp_occhint | `/home/qqxluca/projects/v2xreg_private/outputs/full_bench_opv2v_camera_occhint_full_20260219_a1` |
| opv2v_occhint_smoke100 | 2026-02-19T01:38:47 | camera | noise10 | None | online_box/register_and_fuse | v2xregpp_occhint | `/home/qqxluca/projects/v2xreg_private/outputs/full_bench_opv2v_occhint_smoke100` |
| opv2v_autopilot_smoke_20260216_auto3_a1 | 2026-02-16T20:02:38 | camera,lidar | noise10 | None | online_box/register_and_fuse |  | `/home/qqxluca/projects/v2xreg_private/outputs/full_bench_opv2v_autopilot_smoke_20260216_auto3_a1` |
| opv2v_autopilot_smoke_20260216_supervisor_test2_a1 | 2026-02-16T19:54:47 | camera,lidar | noise10 | None | online_box/register_and_fuse |  | `/home/qqxluca/projects/v2xreg_private/outputs/full_bench_opv2v_autopilot_smoke_20260216_supervisor_test2_a1` |
| opv2v_autopilot_smoke_20260216_auto2_a3 | 2026-02-16T19:28:29 | camera,lidar | noise10 | None | online_box/register_and_fuse |  | `/home/qqxluca/projects/v2xreg_private/outputs/full_bench_opv2v_autopilot_smoke_20260216_auto2_a3` |
| opv2v_autopilot_smoke_20260216_auto2_a2 | 2026-02-16T19:24:21 | camera,lidar | noise10 | None | online_box/register_and_fuse |  | `/home/qqxluca/projects/v2xreg_private/outputs/full_bench_opv2v_autopilot_smoke_20260216_auto2_a2` |
| opv2v_autopilot_smoke_20260216_auto2_a1 | 2026-02-16T19:18:14 | camera,lidar | noise10 | None | online_box/register_and_fuse |  | `/home/qqxluca/projects/v2xreg_private/outputs/full_bench_opv2v_autopilot_smoke_20260216_auto2_a1` |
| opv2v_smoke_contract_20260216 | 2026-02-16T18:31:24 | lidar | noise10 | None | offline_map/ |  | `/home/qqxluca/projects/v2xreg_private/outputs/full_bench_opv2v_smoke_contract_20260216` |
| smoke_args_check | 2026-02-15T16:51:56 | camera | noise10 | None | online_box/register_and_fuse |  | `/home/qqxluca/projects/v2xreg_private/outputs/full_bench_smoke_args_check` |
| opv2v_lidar_posenoise_noise10_20260214 | 2026-02-14T23:39:25 | lidar | noise10 | None | None/None |  | `/home/qqxluca/projects/v2xreg_private/outputs/full_bench_opv2v_lidar_posenoise_noise10_20260214` |
| opv2v_fullbench_fast_20260212 | 2026-02-14T00:02:07 | None | None | None | None/None |  | `/home/qqxluca/projects/v2xreg_private/outputs/full_bench_opv2v_fullbench_fast_20260212` |

## 2) Core Runs (DAIR/V2V4Real core pipeline)

| dataset | modality | tag | suite | noise_points | methods | run_dir |
| --- | --- | --- | --- | ---: | --- | --- |
| DAIR-V2X | camera | dair_core_unified_20260228 | core | 11 | none,single,oracle,v2xregpp_initfree,freealign_paper,vips_initfree,cbm_initfree | `/home/qqxluca/projects/v2xreg_private/outputs/dair_core_dair_core_unified_20260228/camera` |
| DAIR-V2X | lidar | dair_core_unified_20260228 | core | 11 | none,single,oracle,v2xregpp_initfree,freealign_paper,vips_initfree,cbm_initfree | `/home/qqxluca/projects/v2xreg_private/outputs/dair_core_dair_core_unified_20260228/lidar` |
|  |  | v2v4real_noise10_comm200_20260227_062938 | core_plus_stable | 11 | none,single,oracle,v2xregpp_initfree,freealign_paper,vips_initfree,cbm_initfree,v2xregpp_stable,freealign_paper_stable,vips_stable,cbm_stable | `/home/qqxluca/projects/v2xreg_private/outputs/v2v4real_core_v2v4real_noise10_comm200_20260227_062938` |
|  |  | v2v4real_noise10_comm70_20260227_062938 | core_plus_stable | 11 | none,single,oracle,v2xregpp_initfree,freealign_paper,vips_initfree,cbm_initfree,v2xregpp_stable,freealign_paper_stable,vips_stable,cbm_stable | `/home/qqxluca/projects/v2xreg_private/outputs/v2v4real_core_v2v4real_noise10_comm70_20260227_062938` |
|  |  | v2v4real_core_full_20260226_222033 | core_plus_stable | 5 | none,single,oracle,v2xregpp_initfree,freealign_paper,vips_initfree,cbm_initfree,v2xregpp_stable,freealign_paper_stable,vips_stable,cbm_stable | `/home/qqxluca/projects/v2xreg_private/outputs/v2v4real_core_v2v4real_core_full_20260226_222033` |
|  |  | v2v4real_stage1_full_20260226_221653 |  | 0 |  | `/home/qqxluca/projects/v2xreg_private/outputs/v2v4real_stage1_export_v2v4real_stage1_full_20260226_221653` |
|  |  | smoke_stage1_20260226_221551 |  | 0 |  | `/home/qqxluca/projects/v2xreg_private/outputs/v2v4real_stage1_export_smoke_stage1_20260226_221551` |
|  |  | 20260225_192705_corefix | core_plus_stable | 5 | none,oracle,v2xregpp_initfree,freealign_paper,vips_initfree,cbm_initfree,v2xregpp_stable,freealign_paper_stable,vips_stable,cbm_stable | `/home/qqxluca/projects/v2xreg_private/outputs/v2v4real_core_20260225_192705_corefix` |
|  |  | 20260225_034525 |  | 0 | none,oracle,v2xregpp_initfree,v2xregpp_stable,freealign_paper,freealign_paper_stable,vips_initfree,vips_stable,cbm_initfree,cbm_stable | `/home/qqxluca/projects/v2xreg_private/outputs/v2v4real_core_20260225_034525` |

## 3) Pose Sweep Results (DAIR-style)

| file | entries | pos_std_list | rot_std_list | example_model_dir |
| --- | ---: | --- | --- | --- |
| `/home/qqxluca/projects/v2xreg_private/outputs/pose_sweep_1to10_full_gpuvoxel20260218_results.jsonl` | 20 | 1,2,3,4,5,6,7,8,9,10 | 1,2,3,4,5,6,7,8,9,10 | `/home/qqxluca/projects/v2xreg_private/HEAL/opencood/logs/HeterBaseline_DAIR_camera_v2xvit_2023_09_09_11_27_38` |
| `/home/qqxluca/projects/v2xreg_private/outputs/pose_sweep_1to10_camera_percav_full_results.jsonl` | 10 | 1,2,3,4,5,6,7,8,9,10 | 1,2,3,4,5,6,7,8,9,10 | `/home/qqxluca/projects/v2xreg_private/HEAL/opencood/logs/HeterBaseline_DAIR_camera_v2xvit_2023_09_09_11_27_38` |
| `/home/qqxluca/projects/v2xreg_private/outputs/pose_sweep_1to10_full_results.jsonl` | 20 | 1,2,3,4,5,6,7,8,9,10 | 1,2,3,4,5,6,7,8,9,10 | `/home/qqxluca/projects/v2xreg_private/HEAL/opencood/logs/HeterBaseline_DAIR_camera_v2xvit_2023_09_09_11_27_38` |
| `/home/qqxluca/projects/v2xreg_private/outputs/pose_sweep_1to10_results.jsonl` | 20 | None | None | `/home/qqxluca/projects/v2xreg_private/HEAL/opencood/logs/HeterBaseline_DAIR_camera_v2xvit_2023_09_09_11_27_38` |

## 4) Aggregate Reports

- `/home/qqxluca/projects/v2xreg_private/outputs/benchmark_unified_20260220`
- `/home/qqxluca/projects/v2xreg_private/outputs/benchmark_fullmatrix_20260220`
- `/home/qqxluca/projects/v2xreg_private/outputs/benchmark_fullmatrix_audit_20260224`
- `/home/qqxluca/projects/v2xreg_private/outputs/benchmark_fullmatrix_mapping_20260223`
