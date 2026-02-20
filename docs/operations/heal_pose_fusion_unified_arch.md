# HEAL Pose + Cooperative Perception Unified Dataflow Design

Update Log (append new entries at top):
- 2026-02-09 (Round 20): Enabled deterministic seed/cudnn settings for parity checks and reran strict oracle online parity at 100 samples; AP drift reduced to `~2.93e-4` but still fails hard gate.
- 2026-02-09 (Round 19): Added online-oracle no-noise compatibility path in `inference_w_noise` and re-ran strict oracle parity (initial max20 check). AP drift was reduced but remained above hard gate; pose parity remained within threshold.
- 2026-02-09 (Round 18): Added opt-in GPU stage1 runtime path (`pose_provider.online_args.gpu_stage1_solver`) + synthetic parity unit check, ingested `cpu_fallback_count` into `inference_w_noise` timing summaries, and published non-fixture gate artifacts (`run_id=20260209_real_runtime_gate`).
- 2026-02-08 (Round 17): De-fragmented this document. Moved execution-order / switch / cutover content to `heal_pose_fusion_execution_playbook.md` and kept this file as architecture contract + validated baseline only.
- 2026-02-08 (Round 16): Review-fix loop round 3/3 on execution sequencing. Added final cutover checklist (entry/exit/rollback) and a no-gap acceptance map so mode transitions can be audited before default switch.
- 2026-02-08 (Round 15): Review-fix loop round 2/3. Added canonical mode state machine and compatibility aliases (`mode` -> `runtime_mode`) to remove naming ambiguity during migration.
- 2026-02-08 (Round 14): Review-fix loop round 1/3. Added detailed implementation order, handoff gates, and per-stage transition logic between offline-map and online GPU runtime.
- 2026-02-08 (Round 13): Review-fix loop on Round 12 plan. Fixed mode naming consistency (`register_and_fuse`), anchored runtime modes to existing `pose_provider` config path, and added measurable validation gates for online/full-GPU migration.
- 2026-02-08 (Round 12): Added full-GPU real-time execution roadmap (code-grounded bottleneck map, work packages, mode-unified online runtime plan, and acceptance gates), and linked the algorithm-co-design document for no-init + heter-fusion.
- 2026-02-08 (Round 11): Vectorized `get_pairwise_transformation_torch` (removed per-agent nested solve loops), added `HEAL/opencood/tools/bench_pairwise_vectorization.py`, re-ran runtime/unit parity checks (including full OPV2V provider regression), and added CPU-vs-CUDA 200-sample DAIR check for `v2xregpp_initfree` (`--pose-device cpu|cuda`) with matched AP but no end-to-end speedup yet.
- 2026-02-08 (Round 10): Completed full-test execution for documented commands (OPV2V full parity + DAIR full 1m/1deg runs). Replaced smoke numbers with full-set results and added PoseProvider runtime timing from full OPV2V run.
- 2026-02-08 (Round 9): Review-fix loop pass. Added reproducibility prep commands, acceptance-criteria status matrix (pass/partial), and explicit stable-run evidence + limitation notes.
- 2026-02-08 (Round 8): Finished executable E2E checks (OPV2V parity + DAIR noise runs). Added exact commands, artifact paths, and criterion-by-criterion pass/fail notes.
- 2026-02-08 (Round 7): Unblocked py39 runtime issues (`torchvision` import crash, `pypcd`/NumPy2 compatibility) and added executable tests for dropout reuse + pose confidence semantics.
- 2026-02-08 (Round 6): Added concrete `pose_provider` config example and clarified fallback behavior from `fusion.args.proj_first` + `train_params.max_cav`.
- 2026-02-08 (Round 5): Added fallback-parse test (`fusion.args.proj_first`, `train_params.max_cav`) and aligned doc test map.
- 2026-02-08 (Round 4): Fixed implementation gap by parsing `proj_first`/`max_cav` fallback from hypes when `pose_provider` block omits them.
- 2026-02-08 (Round 3): Clarified current runtime semantics for `register_only` and added automated-vs-E2E test mapping.
- 2026-02-08 (Round 2): Expanded executable test coverage (`proj_first`, multi-batch override, label_dict sync, legacy config parse).
- 2026-02-08 (Round 1): Synced document with landed code. Added model-side PoseProvider runtime status and executable validation entry.
- 2026-02-07: Iterative review refresh. Baseline now references dataset/pose_utils/inference_w_noise behavior, documented noise/dropout + pose_confidence, clarified comm-range + proj_first identity, added GPU pairwise builder note, added testing standard.
- 2026-02-07: Filled baseline references to current code paths.
- 2026-02-07: Initial draft. Defined unified dataflow, PoseProvider modes, GPU/CPU boundaries, and migration plan.

## Purpose
Define a single, internal HEAL architecture that unifies pose alignment and cooperative perception under one dataflow.
Current implementation must keep compatibility with three legacy modes (`register_only`, `gt_only`, `register_and_fuse`) while the target runtime converges to four explicit benchmark modes (`single_only`, `fusion_only`, `register_only`, `register_and_fuse`).
Core computation should stay on GPU in both compatibility and target states.

## Scope / Non-goals
In scope:
- A unified runtime dataflow for pose correction + fusion.
- A single HEAL-side config surface for pose + fusion.
- GPU-first pose solving and pairwise transform generation.

Out of scope (for this doc):
- Re-designing individual pose solvers (FreeAlign/V2XReg++/VIPs/CBM/etc).
- New datasets or new training recipes.
- Changing detection head post-processing semantics.

## Current Baseline (What Exists Today)

### Dataset-side behavior (intermediate_fusion_dataset + intermediate_heter_fusion_dataset)
- Noise & dropout injection happens inside __getitem__ via `add_noise_data_dict`.
  - `lidar_pose_clean` is set from the original pose.
  - Noise is added to `lidar_pose`.
  - Optional `dropout_prob` reuses the last pose for the entire frame and sets `pose_confidence=0.0`.
  - Dropout uses a static in-function state (`add_noise_data_dict._dropout_state`), so it is not sequence-aware.
  - Reference: `HEAL/opencood/utils/pose_utils.py` (`add_noise_data_dict`).
- Pose overrides are applied inside __getitem__.
  - `pose_override` config can enable override by map (`pose_override_map`) or by mode (`pose_override_mode`).
  - `apply_pose_overrides` supports per-sample override entries; `override_lidar_poses` supports `mode=ego|zero` and `apply_to=non-ego|all`.
  - `pose_override` also carries `pose_field`/`confidence_field` names (defaults `lidar_pose_pred_np`, `pose_confidence_np`).
  - Reference: `HEAL/opencood/data_utils/datasets/intermediate_fusion_dataset.py` and `.../intermediate_heter_fusion_dataset.py`.
- Communication range gating happens before fusion.
  - `comm_range_use_clean_pose` controls whether gating uses clean or noisy pose (defaults to True when override is enabled).
- `pose_confidence` is attached if missing, computed from XY error between `lidar_pose` and `lidar_pose_clean` (1 / (1 + eps^2)).
  - Reference: `HEAL/opencood/utils/pose_utils.py` (`attach_pose_confidence`).
- Pairwise transforms are computed on CPU inside the dataset:
  - `pairwise_t_matrix = get_pairwise_transformation(base_data_dict, max_cav, proj_first)`.
  - If `proj_first=True`, the pairwise matrix is identity.
  - Shape: `(L, L, 4, 4)` where `L=max_cav`.
  - Reference: `HEAL/opencood/utils/transformation_utils.py` (`get_pairwise_transformation`).
- Collate moves `pairwise_t_matrix` into `label_dict` and `output_dict` for model forward.
  - Reference: `HEAL/opencood/data_utils/datasets/intermediate_fusion_dataset.py` (collate_batch_*).
- Heterogeneous inference datasets (`intermediate_heter_fusion_dataset` + `heter_infer`) follow the same override/gating/pairwise path.

### Offline pose correction + injection
- `run_pose_solver` runs offline pose correction over `dataset.retrieve_base_data`.
  - Can inject noise, apply `override_lidar_poses`, and consume stage1 caches.
  - Produces a `pose_override_map` + metrics, later injected via `apply_pose_overrides`.
  - Reference: `HEAL/opencood/extrinsics/pose_correction/pose_solver.py`.
- `inference_w_noise.py` uses `run_pose_solver`, then sets `pose_override_map` on the dataset.
  - For correction/stable modes, it forces `num_workers=0` to avoid copying large stage1 maps.
  - Reference: `HEAL/opencood/tools/inference_w_noise.py`.

### GPU-ready utilities already present
- `get_pairwise_transformation_torch` builds pairwise transforms on GPU from `lidar_pose` + `record_len`.
  - Wired through model-side PoseProvider runtime when `pose_provider.enabled=true`.
  - Reference: `HEAL/opencood/utils/transformation_utils.py`.

### Model-side runtime path (already implemented)
- `PoseProviderConfig` + `apply_pose_provider` exist and support `register_only` / `gt_only` / `register_and_fuse`.
  - Reference: `HEAL/opencood/utils/pose_provider_runtime.py`.
- Runtime hook `maybe_apply_pose_provider` is integrated after `to_device` in train/inference entries.
  - Reference: `HEAL/opencood/tools/train_utils.py`.
- `proj_first` and `max_cav` support config fallback from baseline hypes:
  - `proj_first` falls back to `fusion.args.proj_first` if `pose_provider.proj_first` is unset.
  - `max_cav` falls back to `train_params.max_cav` if `pose_provider.max_cav` is unset.
  - Reference: `HEAL/opencood/utils/pose_provider_runtime.py`.
- Integrated scripts include:
  - `HEAL/opencood/tools/train.py`
  - `HEAL/opencood/tools/train_ddp.py`
  - `HEAL/opencood/tools/train_w_kd.py`
  - `HEAL/opencood/tools/inference.py`
  - `HEAL/opencood/tools/inference_w_noise.py`
  - `HEAL/opencood/tools/inference_heter_in_order.py`
  - `HEAL/opencood/tools/eval_calibfree_align.py`
- Not all utility scripts are wired yet (e.g., some cache-export / profiler paths), so this is "mainline train+infer path complete" rather than "every tool complete".

Current runtime semantics note:
- In generic train/inference entrypoints, `register_only` currently means "apply pose override + rebuild pairwise".
- It does not forcibly short-circuit model fusion forward in all models; pure registration benchmarking should still use pose-solver/eval tools.

### Baseline limitations
- Legacy path is still dataset-side/two-stage by default, so behavior depends on whether `pose_provider.enabled` is set.
- Some correction methods remain CPU/NumPy heavy; model-side runtime currently consumes their outputs and performs GPU pairwise rebuild.
- Dropout state is global and not sequence-aware, which can affect reproducibility with multi-worker loaders.
- Auxiliary scripts not yet migrated can bypass PoseProvider runtime.

## Target Outcomes
1) Unified dataflow that loads data once and supports:
   - legacy-compatible modes: `register_only`, `gt_only`, `register_and_fuse`
   - target benchmark modes: `single_only`, `fusion_only`, `register_only`, `register_and_fuse`
   - where `gt_only` is treated as compatibility alias of `fusion_only + pose_source=gt`
2) HEAL internal-only: no external calib/legacy entry points required for pose.
3) Core computation on GPU; CPU only for IO and preprocessing.

## Proposed Unified Architecture

### High-Level Dataflow
RawDataset (CPU IO)
  -> PoseInputsBuilder (CPU, schema normalization)
  -> Collate
  -> Model.forward
     -> PoseProvider (GPU, pose solver + update)
     -> Pairwise T builder (GPU; uses get_pairwise_transformation_torch)
     -> Fusion model (GPU)
  -> Outputs (pose metrics + detection metrics)

Key change: pose correction and pairwise transform generation move from dataset-side to model-side.

### Core Components

1) PoseInputs (unified schema)
Minimum fields:
- sample_idx
- cav_id_list
- record_len
- lidar_pose (raw)
- lidar_pose_clean (GT)
- pose_confidence (optional)
- proj_first (bool)
- comm_range (float) + comm_range_use_clean_pose (bool)
- boxes (pred corners or features)
- descriptors / occ maps (optional)
- raw lidar points (optional)

2) PoseInputsBuilder (CPU)
- Reads stage1 cache or online detections.
- Produces PoseInputs in consistent schema.
- Does not compute pairwise_t_matrix.

3) PoseProvider (GPU)
Interface:
- apply(batch) -> updated_batch, pose_metrics

Responsibilities:
- Selects mode (register_only / gt_only / register_and_fuse).
- Runs pose solver on GPU (or GPU-first hybrid).
- Updates lidar_pose + pose_confidence.
- Builds pairwise_t_matrix on GPU (use get_pairwise_transformation_torch).

4) Fusion Model (GPU)
- Uses pairwise_t_matrix produced by PoseProvider.

### Modes
- register_only:
  Output pose metrics; skip fusion.
  Used for alignment benchmarks.
- gt_only:
  Use lidar_pose_clean to generate pairwise_t_matrix.
  No pose solver.
  Used to define upper bound.
- register_and_fuse:
  PoseProvider solves pose; fusion uses updated pairwise_t_matrix.

### Failure Policy
If pose solver fails (no matches or low confidence):
- Option A: keep current pose (no update)
- Option B: disable fusion for this sample
- Option C: fall back to GT (only in gt_only mode)
This policy is configured inside PoseProvider.

### State and Stability
- Stable mode requires temporal state (EMA or solver cache).
- Current dropout uses a global static state; the unified pipeline should isolate state per sequence or reset on `sample_idx` rewind.
- DataLoader should use num_workers=0 for stable modes unless state is partitioned by worker.

### Configuration Strategy
Unify into a single HEAL-side config with three blocks:
- pose_provider:
  - mode
  - solver name
  - failure policy
- pose_solver:
  - matching parameters
  - solver thresholds
- fusion:
  - fusion method

Map legacy `pose_override` config into `pose_provider` (keep backward compatibility in Phase 0).

Example (recommended current usage):
```yaml
pose_provider:
  enabled: true
  mode: register_and_fuse  # or gt_only / register_only
  recompute_pairwise: true
  # optional; if unset, fallback to fusion.args.proj_first
  proj_first: false
  # optional; if unset, fallback to train_params.max_cav
  max_cav: 5
  # optional override source
  pose_override_path: /path/to/pose_override.json
```

## Migration Plan (Incremental)
Phase 0: Compatibility Layer
- Keep legacy dataset override path; add a new model-side path gated by a flag.

Phase 1: PoseInputsBuilder
- Dataset outputs PoseInputs but still returns pairwise_t_matrix for legacy models.

Phase 2: PoseProvider + GPU pairwise_t_matrix
- Model uses PoseProvider and ignores dataset pairwise_t_matrix.

Phase 3: Remove legacy pose_override
- Dataset no longer supports pose override map.

Phase 4: Remove external calib/legacy dependency
- All pose solvers live inside HEAL.

## Testing Standard (Acceptance Criteria)

1) Pairwise transform parity (CPU vs GPU)
- For identical `lidar_pose` and `record_len`, GPU builder must match CPU builder:
  - max abs diff <= 1e-5 for all elements.
  - shape matches `(B, L, L, 4, 4)`.
- If `proj_first=True`, pairwise_t_matrix must be identity.

2) Pose override semantics
- `apply_pose_overrides` must honor sample_idx keys (int or str).
- `override_lidar_poses` must:
  - keep ego pose intact when `apply_to=non-ego`.
  - set non-ego poses to zero for `mode=zero`.
- `pose_confidence`:
  - default to 1.0 if pose_clean missing.
  - set to 0.0 for dropout frames.

3) Noise + dropout reproducibility
- With fixed seed, dropout applies uniformly to all agents in a frame.
- Last pose reuse on dropout must match current `add_noise_data_dict` behavior.

4) End-to-end parity (no solver)
- `register_and_fuse` with solver disabled must match baseline metrics:
  - AP@{0.3,0.5,0.7} difference <= 1e-4.
  - Detection count and NMS outputs identical within float tolerance.

5) End-to-end improvement (with solver)
- Pose correction must reduce median RTE/RRE vs noisy baseline by a non-trivial margin (target: >= 20% relative improvement).
- Fusion AP should not regress vs baseline under same noise settings.

6) Performance and stability
- Overall inference throughput should not regress by >5% vs baseline.
- PoseProvider GPU path should reduce CPU time in `pose_timing` vs legacy (track in metrics).

### Automated Test Coverage (Current)
- Implemented script: `HEAL/opencood/tools/test_pose_provider_runtime.py`
- Covered checks:
  - CPU/GPU pairwise parity (`test_pairwise_parity`)
  - Non-ego override behavior (`test_override_non_ego`)
  - GT-only pairwise generation (`test_gt_only_pairwise`)
  - `proj_first` identity + `label_dict` synchronization (`test_proj_first_identity_and_label_sync`)
  - Multi-batch `sample_idx`/string-key override correctness (`test_multibatch_override_with_string_keys`)
  - Legacy `pose_override` config compatibility parsing (`test_legacy_pose_override_config_parse`)
  - `fusion.args.proj_first` and `train_params.max_cav` fallback parsing (`test_fusion_and_trainparams_fallback_parse`)
  - `pose_confidence` semantics (`test_attach_pose_confidence_defaults_and_formula`)
  - Dropout last-pose reuse + per-frame confidence behavior (`test_dropout_uniform_and_last_pose_reuse`)

### E2E Validation Mapping (Dataset/Checkpoint Required)
- Detection parity and AP regression checks remain E2E tasks and require dataset + checkpoints.
- Recommended E2E path:
  - `HEAL/opencood/tools/inference.py`
  - `HEAL/opencood/tools/inference_w_noise.py`
- Pass criteria follow the "Testing Standard" thresholds above.

Recommended harness:
- Use `opencood/tools/inference_w_noise.py` for detection metrics + timing.
- Use `opencood/extrinsics/pose_correction/pose_solver.py` metrics for RTE/RRE.

Validation entry (current codebase):
- Unit-style runtime validation: `PYTHONPATH=HEAL .micromamba/envs/py39/bin/python HEAL/opencood/tools/test_pose_provider_runtime.py`

### Executed Validation (2026-02-08)

0) Repro prep (needed in this py39 environment)
- Install runtime deps (if missing):
  - `../.micromamba/envs/py39/bin/pip install cython h5py`
  - `../.micromamba/envs/py39/bin/pip install --no-deps einops tensorboardX termcolor efficientnet_pytorch==0.7.1 timm`
  - Optional: `../.micromamba/envs/py39/bin/pip install pypcd==0.1.1` (runtime has fallback in `pcd_utils.py` when pypcd is unavailable/incompatible).
- Build Cython overlap op:
  - `PYTHONPATH=. ../.micromamba/envs/py39/bin/python opencood/utils/setup.py build_ext --inplace`
- Create PoseProvider parity eval model_dir (copy baseline config + append `pose_provider` block + symlink checkpoint):
  - `tmp_dir="opencood/logs/_tmp_poseprovider_doc_tests/opv2v_baseline_poseprovider"; src_dir="opencood/logs/freealign_repro_opv2v_baseline"; mkdir -p "$tmp_dir"; cp "$src_dir/config.yaml" "$tmp_dir/config.yaml"; ln -sfn "$(realpath "$src_dir/net_epoch_bestval_at27.pth")" "$tmp_dir/net_epoch_bestval_at27.pth"; cat >> "$tmp_dir/config.yaml" <<"YAML"`
  - `pose_provider:`
  - `  enabled: true`
  - `  mode: register_and_fuse`
  - `  apply_to: non-ego`
  - `  freeze_ego: true`
  - `  recompute_pairwise: true`
  - `YAML`

1) Unit/runtime tests
- Command:
  - `PYTHONPATH=HEAL .micromamba/envs/py39/bin/python HEAL/opencood/tools/test_pose_provider_runtime.py`
- Result:
  - `OK`

2) E2E parity (no solver, `register_and_fuse` path, OPV2V full test)
- Baseline command:
  - `PYTHONPATH=. ../.micromamba/envs/py39/bin/python opencood/tools/inference.py --model_dir opencood/logs/freealign_repro_opv2v_baseline --fusion_method intermediate --num_workers 0 --note _poseprovider_doc_baseline_full`
- PoseProvider command:
  - `PYTHONPATH=. ../.micromamba/envs/py39/bin/python opencood/tools/inference.py --model_dir opencood/logs/_tmp_poseprovider_doc_tests/opv2v_baseline_poseprovider --fusion_method intermediate --num_workers 0 --note _poseprovider_doc_withprovider_full`
- Artifacts:
  - `HEAL/opencood/logs/freealign_repro_opv2v_baseline/eval_intermediate_poseprovider_doc_baseline_full_epoch27.yaml`
  - `HEAL/opencood/logs/_tmp_poseprovider_doc_tests/opv2v_baseline_poseprovider/eval_intermediate_poseprovider_doc_withprovider_full_epoch27.yaml`
- Result (PoseProvider - baseline):
  - AP@0.3: `+1.05e-06`
  - AP@0.5: `+8.33e-07`
  - AP@0.7: `-5.77e-05`
  - Meets parity threshold `<= 1e-4`.

3) E2E correction runs under noise (`pos_std=1m`, `rot_std=1deg`, DAIR full test: 1789 samples)
- Baseline (no correction):
  - `PYTHONPATH=. ../.micromamba/envs/py39/bin/python opencood/tools/inference_w_noise.py --model_dir opencood/logs/freealign_repro_dair_baseline --fusion_method intermediate --pose-correction none --pos-std-list 1 --rot-std-list 1 --sweep-mode paired --num-workers 0 --note _poseprovider_doc_dair_baseline_full`
- V2XReg++ initfree:
  - `PYTHONPATH=. ../.micromamba/envs/py39/bin/python opencood/tools/inference_w_noise.py --model_dir opencood/logs/freealign_repro_dair_baseline --fusion_method intermediate --pose-correction v2xregpp_initfree --stage1-result opencood/logs/freealign_repro_dair_stage1/merged_stage1_val.json --v2xregpp-config /home/qqxluca/projects/v2xreg_private/configs/dair/midfusion/pipeline_midfusion_detection_occ.yaml --pos-std-list 1 --rot-std-list 1 --sweep-mode paired --num-workers 0 --note _poseprovider_doc_dair_v2xregpp_full`
- Oracle GT:
  - `PYTHONPATH=. ../.micromamba/envs/py39/bin/python opencood/tools/inference_w_noise.py --model_dir opencood/logs/freealign_repro_dair_baseline --fusion_method intermediate --pose-correction oracle_gt --pos-std-list 1 --rot-std-list 1 --sweep-mode paired --num-workers 0 --note _poseprovider_doc_dair_oracle_full`
- V2XReg++ stable (extra check):
  - `PYTHONPATH=. ../.micromamba/envs/py39/bin/python opencood/tools/inference_w_noise.py --model_dir opencood/logs/freealign_repro_dair_baseline --fusion_method intermediate --pose-correction v2xregpp_stable --stage1-result opencood/logs/freealign_repro_dair_stage1/merged_stage1_val.json --v2xregpp-config /home/qqxluca/projects/v2xreg_private/configs/dair/midfusion/pipeline_midfusion_detection_occ.yaml --pos-std-list 1 --rot-std-list 1 --sweep-mode paired --num-workers 0 --note _poseprovider_doc_dair_v2xregpp_stable_full`
- Artifacts:
  - `HEAL/opencood/logs/freealign_repro_dair_baseline/AP030507_none_poseprovider_doc_dair_baseline_full.yaml`
  - `HEAL/opencood/logs/freealign_repro_dair_baseline/AP030507_v2xregpp_initfree_poseprovider_doc_dair_v2xregpp_full.yaml`
  - `HEAL/opencood/logs/freealign_repro_dair_baseline/AP030507_oracle_gt_poseprovider_doc_dair_oracle_full.yaml`
  - `HEAL/opencood/logs/freealign_repro_dair_baseline/AP030507_v2xregpp_stable_poseprovider_doc_dair_v2xregpp_stable_full.yaml`
- Key outcomes:
  - Baseline AP@0.3/0.5/0.7: `0.4257 / 0.2952 / 0.1676`
  - V2XReg++ initfree AP@0.3/0.5/0.7: `0.4830 / 0.3588 / 0.1997`
  - V2XReg++ stable AP@0.3/0.5/0.7: `0.4380 / 0.3106 / 0.1705`
  - Oracle GT AP@0.3/0.5/0.7: `0.5152 / 0.3801 / 0.2072`
  - Baseline rel median (trans/yaw): `1.1783m / 0.6761deg`
  - V2XReg++ initfree rel median (trans/yaw): `1.1085m / 0.7689deg` (translation improves, yaw worsens)
  - V2XReg++ stable rel median (trans/yaw): `1.4448m / 0.8293deg`
  - Oracle GT rel median (trans/yaw): `7.15e-07m / 8.43e-08deg`
  - Oracle GT provides >20% relative median error reduction and no AP regression.

4) Throughput check
- From `timing_stats` in the DAIR full runs:
  - Baseline infer_fps: `1.7315`
  - Oracle GT infer_fps: `1.7716`
  - V2XReg++ initfree infer_fps: `1.7554`
  - V2XReg++ stable infer_fps: `1.7519`
- No >5% regression observed in these full runs.

5) PoseProvider runtime timing (OPV2V full provider run)
- From `HEAL/opencood/logs/_fulltest_poseprovider/opv2v_provider_full.log`:
  - `pose_provider_total_sec`: mean `0.002376s`, median `0.001747s`
  - `pose_override_sec`: mean `0.000003s`
  - `pairwise_rebuild_sec`: mean `0.002370s`, median `0.001741s`

6) CUDA runtime check + pose-device comparison (`v2xregpp_initfree`, DAIR 200 samples)
- CUDA visibility in current py39 env:
  - `PYTHONPATH=HEAL .micromamba/envs/py39/bin/python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.version.cuda)"`
  - Output: `2.6.0+cu124 True 12.4`
- CPU pose solver run:
  - `PYTHONPATH=. ../.micromamba/envs/py39/bin/python opencood/tools/inference_w_noise.py --model_dir opencood/logs/freealign_repro_dair_baseline --fusion_method intermediate --pose-correction v2xregpp_initfree --pose-device cpu --stage1-result opencood/logs/freealign_repro_dair_stage1/merged_stage1_val.json --v2xregpp-config /home/qqxluca/projects/v2xreg_private/configs/dair/midfusion/pipeline_midfusion_detection_occ.yaml --pos-std-list 1 --rot-std-list 1 --sweep-mode paired --num-workers 0 --max-eval-samples 200 --pose-timing --note _poseprovider_doc_gpucheck_cpu200`
- CUDA pose solver run:
  - `PYTHONPATH=. ../.micromamba/envs/py39/bin/python opencood/tools/inference_w_noise.py --model_dir opencood/logs/freealign_repro_dair_baseline --fusion_method intermediate --pose-correction v2xregpp_initfree --pose-device cuda --stage1-result opencood/logs/freealign_repro_dair_stage1/merged_stage1_val.json --v2xregpp-config /home/qqxluca/projects/v2xreg_private/configs/dair/midfusion/pipeline_midfusion_detection_occ.yaml --pos-std-list 1 --rot-std-list 1 --sweep-mode paired --num-workers 0 --max-eval-samples 200 --pose-timing --note _poseprovider_doc_gpucheck_cuda200`
- Artifacts:
  - `HEAL/opencood/logs/freealign_repro_dair_baseline/AP030507_v2xregpp_initfree_poseprovider_doc_gpucheck_cpu200.yaml`
  - `HEAL/opencood/logs/freealign_repro_dair_baseline/AP030507_v2xregpp_initfree_poseprovider_doc_gpucheck_cuda200.yaml`
- Result:
  - AP parity: exact match (`AP50=0.3569966`, same median pose errors)
  - End-to-end throughput: effectively unchanged (`1.9734 fps` CPU vs `1.9698 fps` CUDA)
  - Pose solver avg time inside `pose_solver`: CPU `0.0303s` vs CUDA `0.1180s` per applied sample
  - Interpretation: current V2XReg++ pipeline remains hybrid/CPU-heavy; toggling `--pose-device cuda` alone does not yet provide wall-clock speedup.

6.1) Regression check after pairwise-torch vectorization (`get_pairwise_transformation_torch`)
- Baseline command (OPV2V, 100 samples):
  - `PYTHONPATH=. ../.micromamba/envs/py39/bin/python opencood/tools/inference.py --model_dir opencood/logs/freealign_repro_opv2v_baseline --fusion_method intermediate --num_workers 0 --max_samples 100 --note _poseprovider_doc_regcheck_base100`
- PoseProvider command (same checkpoint/config with `pose_provider.enabled=true`, 100 samples):
  - `PYTHONPATH=. ../.micromamba/envs/py39/bin/python opencood/tools/inference.py --model_dir opencood/logs/_tmp_poseprovider_doc_tests/opv2v_baseline_poseprovider --fusion_method intermediate --num_workers 0 --max_samples 100 --note _poseprovider_doc_regcheck_provider100`
- Artifacts:
  - `HEAL/opencood/logs/freealign_repro_opv2v_baseline/eval_intermediate_poseprovider_doc_regcheck_base100_epoch27.yaml`
  - `HEAL/opencood/logs/_tmp_poseprovider_doc_tests/opv2v_baseline_poseprovider/eval_intermediate_poseprovider_doc_regcheck_provider100_epoch27.yaml`
- Result (PoseProvider - baseline):
  - AP@0.3: `-1.28e-05`
  - AP@0.5: `-6.24e-06`
  - AP@0.7: `-5.47e-06`
  - Still within parity threshold (`<= 1e-4`).
- Full-set provider recheck (OPV2V, 2170 samples):
  - Command:
    - `PYTHONPATH=. ../.micromamba/envs/py39/bin/python opencood/tools/inference.py --model_dir opencood/logs/_tmp_poseprovider_doc_tests/opv2v_baseline_poseprovider --fusion_method intermediate --num_workers 0 --note _poseprovider_doc_provider_full_r11`
  - Artifact:
    - `HEAL/opencood/logs/_tmp_poseprovider_doc_tests/opv2v_baseline_poseprovider/eval_intermediate_poseprovider_doc_provider_full_r11_epoch27.yaml`
  - Result vs baseline full (`eval_intermediate_poseprovider_doc_baseline_full_epoch27.yaml`):
    - AP@0.3: `-3.53e-05`
    - AP@0.5: `-3.50e-06`
    - AP@0.7: `+7.95e-06`
    - All within parity threshold (`<= 1e-4`).
  - Runtime printout from this run:
    - `pairwise_rebuild_sec` mean `0.001643s`, median `0.001100s`.

6.2) Component benchmark: old vs vectorized pairwise-torch kernel
- Command:
  - `PYTHONPATH=HEAL .micromamba/envs/py39/bin/python HEAL/opencood/tools/bench_pairwise_vectorization.py`
  - The benchmark script compares previous nested-loop GPU implementation vs current vectorized implementation under the same random poses.
- Result:
  - `B=1, L=5`: `3.92x` speedup (`old=11.99s`, `new=3.06s`, `max diff=4.77e-07`)
  - `B=8, L=5`: `4.06x` speedup (`old=46.60s`, `new=11.48s`, `max diff=4.77e-07`)
  - `B=16, L=5`: `4.07x` speedup (`old=46.37s`, `new=11.40s`, `max diff=4.77e-07`)
- Interpretation:
  - Pairwise rebuild itself is significantly faster and numerically consistent.
  - End-to-end DAIR runtime still does not improve because pose-correction pipeline remains dominated by non-pairwise (CPU/hybrid) stages.

7) Runtime compatibility fixes required for executable E2E in this environment

- `torchvision` import crash (`operator torchvision::nms does not exist`) is handled with guarded/fallback imports in:
  - `HEAL/opencood/utils/camera_utils.py`
  - `HEAL/opencood/models/sub_modules/feature_alignnet_modules.py`
  - `HEAL/opencood/models/heter_model_baseline.py`
  - `HEAL/opencood/models/heter_encoders.py`
- `pypcd` + NumPy2 compatibility issues were addressed in:
  - `HEAL/opencood/utils/pcd_utils.py`

### Acceptance Criteria Status (2026-02-09 snapshot)
- Pairwise parity (CPU vs GPU): **PASS** (`<= 1e-5`, unit test).
- Pose override semantics + config fallback: **PASS** (unit tests).
- Noise + dropout reproducibility semantics: **PASS** (unit tests for last-pose reuse + confidence behavior).
- End-to-end parity (no solver): **PASS** (max AP diff `5.77e-05` <= `1e-4`).
- End-to-end solver improvement (>=20% median RTE/RRE + AP non-regression): **PARTIAL**.
  - `oracle_gt`: **PASS**.
  - `v2xregpp_initfree`: translation median improves (`+5.92%`), yaw median worsens (`-13.74%`) on full test.
  - `v2xregpp_stable`: median translation/yaw both regress on full test.
- Throughput regression <=5%: **PASS** on full runs.
- PoseProvider runtime timing availability (`pose_timing` payload): **PASS**.
- PoseProvider GPU-path-vs-legacy CPU-time reduction: **PARTIAL / NOT MET**.
  - CUDA is available in py39 (`torch.cuda.is_available()==True`), and pairwise runtime is on torch path.
  - But end-to-end DAIR 200-sample check (`v2xregpp_initfree`) shows no speedup when switching `--pose-device cpu -> cuda`; solver time is slower on CUDA in current implementation.
- Experimental `gpu_stage1_solver` path now exists and can drive `cpu_fallback_count` to 0 for stage1 solve, but 20-sample DAIR check currently shows large AP drift vs reference (not promotable to Track R yet).
- Strict solver-parity check (`oracle_gt`, DAIR max100) remains **not passed**: AP max delta reduced to `~2.93e-4` (target `<=1e-4`), while pose parity already passes; evidence: `outputs/strict_oracle_online_parity_20260209.json`.

Scope note:
- The above E2E numbers are full-test for the documented command set at a single noise point (`1m/1deg`).
- Full sweep conclusions (e.g., 1m–10m curves) still require running the same command family across all noise points.

## Risks and Mitigations
1) Comm-range gating drift when moving to model-side
   - Mitigation: keep the same `comm_range_use_clean_pose` semantics in PoseInputsBuilder.

2) Stable mode under DDP / multi-worker
   - Mitigation: per-rank state; restrict stable mode to single-rank if needed.

3) Cache schema mismatch
   - Mitigation: PoseInputsBuilder validates and normalizes schema.

4) CPU-only algorithms
   - Mitigation: mark as optional, default disabled, documented as exceptions.

5) Dropout global state changes behavior
   - Mitigation: explicit per-sequence state reset; unit tests for dropout parity.

## Open Questions
- Should PoseInputs include raw point clouds by default or lazy-load on demand?
- Which failure policy yields the most stable fusion behavior for register_and_fuse?
- Do we need a lightweight GPU-only fallback solver for sparse boxes?
- How to expose pose_confidence to fusion models consistently across modalities?

## Roadmap Boundary (拆分说明)
为解决本文“前后割裂”问题，执行顺序、切换策略与阶段回滚已拆分到独立执行手册：
- `docs/operations/heal_pose_fusion_execution_playbook.md`

本文保留：
- 统一架构契约（数据流、接口、模式语义）
- 当前代码现状与已验证事实
- 验收标准与风险定义

不再在本文维护：
- 长篇阶段推进计划（S0~S5）
- 切换/回滚操作细节
- benchmark 运行编排脚本级清单

文档导航见：
- `docs/operations/heal_pose_fusion_docs_index.md`
- `docs/operations/heal_noinit_online_heter_fusion_design.md`
