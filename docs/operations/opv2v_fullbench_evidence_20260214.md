# OPV2V Fullbench Evidence Report (2026-02-14)

## 0) Executive Conclusions

- Run dir: `outputs/full_bench_opv2v_fullbench_fast_20260212`
- Run id: `opv2v_fullbench_fast_20260212`
- Source of truth: `outputs/full_bench_opv2v_fullbench_fast_20260212/run_state.jsonl` (NOT log grepping)

## 1) Run State (What Actually Finished)

- unique_tasks_started: 404
- unique_tasks_ended: 404
- final_end_codes: {0: 404}
- final_done_tasks: 404
- tasks_ever_failed (historical): 202

### task_summary.json (May Be Stale/Misleading)

- path: `outputs/full_bench_opv2v_fullbench_fast_20260212/task_summary.json`
```json
{
  "done_from_reuse": 0,
  "done_from_state": 202,
  "in_progress": 0,
  "pending": 202,
  "total_tasks": 202
}
```

## 2) Historical Failures (Why It Failed Before)

- Failure signatures (count tasks that *ever* saw a non-zero exit):
  - cuda_fork_reinit: 202

### Example: cuda_fork_reinit

- task: `lidar/drop20/baseline/bounds/1.0`
- log: `outputs/full_bench_opv2v_fullbench_fast_20260212/logs/lidar_drop20_baseline_bounds_n1.0.log`
```
Traceback (most recent call last):
  File "/home/qqxluca/projects/v2xreg_private/HEAL/opencood/tools/inference_w_noise.py", line 1073, in <module>
    main()
  File "/home/qqxluca/projects/v2xreg_private/HEAL/opencood/tools/inference_w_noise.py", line 876, in main
    for i, batch_data in enumerate(data_loader):
  File "/home/qqxluca/projects/v2xreg_private/.micromamba/envs/py39/lib/python3.9/site-packages/torch/utils/data/dataloader.py", line 708, in __next__
    data = self._next_data()
  File "/home/qqxluca/projects/v2xreg_private/.micromamba/envs/py39/lib/python3.9/site-packages/torch/utils/data/dataloader.py", line 1480, in _next_data
    return self._process_data(data)
  File "/home/qqxluca/projects/v2xreg_private/.micromamba/envs/py39/lib/python3.9/site-packages/torch/utils/data/dataloader.py", line 1505, in _process_data
    data.reraise()
  File "/home/qqxluca/projects/v2xreg_private/.micromamba/envs/py39/lib/python3.9/site-packages/torch/_utils.py", line 733, in reraise
    raise exception
RuntimeError: Caught RuntimeError in DataLoader worker process 0.
Original Traceback (most recent call last):
  File "/home/qqxluca/projects/v2xreg_private/.micromamba/envs/py39/lib/python3.9/site-packages/torch/utils/data/_utils/worker.py", line 349, in _worker_loop
    data = fetcher.fetch(index)  # type: ignore[possibly-undefined]
  File "/home/qqxluca/projects/v2xreg_private/.micromamba/envs/py39/lib/python3.9/site-packages/torch/utils/data/_utils/fetch.py", line 52, in fetch
    data = [self.dataset[idx] for idx in possibly_batched_index]
  File "/home/qqxluca/projects/v2xreg_private/.micromamba/envs/py39/lib/python3.9/site-packages/torch/utils/data/_utils/fetch.py", line 52, in <listcomp>
    data = [self.dataset[idx] for idx in possibly_batched_index]
  File "/home/qqxluca/projects/v2xreg_private/HEAL/opencood/data_utils/datasets/intermediate_fusion_dataset.py", line 407, in __getitem__
    selected_cav_processed = self.get_item_single_car(
  File "/home/qqxluca/projects/v2xreg_private/HEAL/opencood/data_utils/datasets/intermediate_fusion_dataset.py", line 169, in get_item_single_car
    processed_lidar = self.pre_processor.preprocess(lidar_np)
```

- task: `lidar/drop20/baseline/bounds/10.0`
- log: `outputs/full_bench_opv2v_fullbench_fast_20260212/logs/lidar_drop20_baseline_bounds_n10.0.log`
```
Traceback (most recent call last):
  File "/home/qqxluca/projects/v2xreg_private/HEAL/opencood/tools/inference_w_noise.py", line 1073, in <module>
    main()
  File "/home/qqxluca/projects/v2xreg_private/HEAL/opencood/tools/inference_w_noise.py", line 876, in main
    for i, batch_data in enumerate(data_loader):
  File "/home/qqxluca/projects/v2xreg_private/.micromamba/envs/py39/lib/python3.9/site-packages/torch/utils/data/dataloader.py", line 708, in __next__
    data = self._next_data()
  File "/home/qqxluca/projects/v2xreg_private/.micromamba/envs/py39/lib/python3.9/site-packages/torch/utils/data/dataloader.py", line 1480, in _next_data
    return self._process_data(data)
  File "/home/qqxluca/projects/v2xreg_private/.micromamba/envs/py39/lib/python3.9/site-packages/torch/utils/data/dataloader.py", line 1505, in _process_data
    data.reraise()
  File "/home/qqxluca/projects/v2xreg_private/.micromamba/envs/py39/lib/python3.9/site-packages/torch/_utils.py", line 733, in reraise
    raise exception
RuntimeError: Caught RuntimeError in DataLoader worker process 0.
Original Traceback (most recent call last):
  File "/home/qqxluca/projects/v2xreg_private/.micromamba/envs/py39/lib/python3.9/site-packages/torch/utils/data/_utils/worker.py", line 349, in _worker_loop
    data = fetcher.fetch(index)  # type: ignore[possibly-undefined]
  File "/home/qqxluca/projects/v2xreg_private/.micromamba/envs/py39/lib/python3.9/site-packages/torch/utils/data/_utils/fetch.py", line 52, in fetch
    data = [self.dataset[idx] for idx in possibly_batched_index]
  File "/home/qqxluca/projects/v2xreg_private/.micromamba/envs/py39/lib/python3.9/site-packages/torch/utils/data/_utils/fetch.py", line 52, in <listcomp>
    data = [self.dataset[idx] for idx in possibly_batched_index]
  File "/home/qqxluca/projects/v2xreg_private/HEAL/opencood/data_utils/datasets/intermediate_fusion_dataset.py", line 407, in __getitem__
    selected_cav_processed = self.get_item_single_car(
  File "/home/qqxluca/projects/v2xreg_private/HEAL/opencood/data_utils/datasets/intermediate_fusion_dataset.py", line 169, in get_item_single_car
    processed_lidar = self.pre_processor.preprocess(lidar_np)
```

## 3) Stage1 Cache Integrity (Hard Requirement for Pose-Correction)

- camera stage1: `/home/qqxluca/projects/v2xreg_private/data/OPV2V/detected/opv2v_camera_v2xvit_stage1/test/stage1_boxes.json` samples=50 len_mismatch=50
- lidar stage1: `/home/qqxluca/projects/v2xreg_private/data/OPV2V/detected/opv2v_lidar_v2xvit_stage1/test/stage1_boxes.json` samples=2170 len_mismatch=0

## 4) Pose Override (Can Cancel Noise Sweeps)

- camera model config: `/home/qqxluca/projects/v2xreg_private/HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope/config.yaml` pose_override_found=False enabled=None mode=None
- lidar model config: `/home/qqxluca/projects/v2xreg_private/HEAL/opencood/logs/freealign_repro_opv2v_baseline_noextr_v2xregpp/config.yaml` pose_override_found=True enabled=True mode=zero

## 5) YAML-Derived Sanity Stats (AP Span + pose_solver.applied)

- AP50 span lidar/noise10/baseline/bounds: n=10 min=0.274414 max=0.274674 span=0.000260
- AP50 span lidar/noise10/oracle/bounds: n=10 min=0.959373 max=0.959442 span=0.000068
- AP50 span camera/noise10/v2xregpp/best: n=10 min=0.083589 max=0.205988 span=0.122399

- pose_solver.applied all-zero lines (these pose-correction methods likely did NOT apply):
  - camera/drop20/cbm/best: applied_min=0 applied_max=0
  - camera/drop20/cbm/stable: applied_min=0 applied_max=0
  - camera/drop20/freealign/best: applied_min=0 applied_max=0
  - camera/drop20/freealign/stable: applied_min=0 applied_max=0
  - camera/drop20/v2xregpp/best: applied_min=0 applied_max=0
  - camera/drop20/v2xregpp/stable: applied_min=0 applied_max=0
  - camera/drop20/vips/best: applied_min=0 applied_max=0
  - camera/drop20/vips/stable: applied_min=0 applied_max=0
  - camera/noise10/cbm/best: applied_min=0 applied_max=0
  - camera/noise10/cbm/stable: applied_min=0 applied_max=0
  - camera/noise10/freealign/best: applied_min=0 applied_max=0
  - camera/noise10/freealign/stable: applied_min=0 applied_max=0
  - camera/noise10/v2xregpp/best: applied_min=0 applied_max=0
  - camera/noise10/v2xregpp/stable: applied_min=0 applied_max=0
  - camera/noise10/vips/best: applied_min=0 applied_max=0
  - camera/noise10/vips/stable: applied_min=0 applied_max=0

