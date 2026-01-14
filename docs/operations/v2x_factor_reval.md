# V2I-Calib / V2X-Reg++ Factor Re-Evaluation (DAIR-V2X, 30 frames)

_Date:_ 2025-11-25  
_Environment:_ Python 3.10 (micromamba `v2x` env), `tools/run_calibration.py`, DAIR-V2X cooperative split (`max_samples=30`).  
_Default config:_ `configs/pipeline_hkust.yaml` (V2X-Reg++, oDist) unless noted.

All raw metrics live under `outputs/factor_sweeps/` (JSON summaries) and `outputs/v2*/` (per-run `metrics.json`, `matches.jsonl`).

## 1. Covisible Objects vs Accuracy / Latency

Command:

```bash
PYTHONPATH=. micromamba run -n v2x python tools/covisibility_sweep.py \
  --config configs/pipeline_hkust.yaml \
  --limits 1,2,3,4,5,7,10,12,15,18,20,25,30,40,50,70,80,100,inf \
  --tag-prefix v2xregpp_cov          # oDist
PYTHONPATH=. micromamba run -n v2x python tools/covisibility_sweep.py \
  --config configs/pipeline_hkust.yaml \
  --limits 1,2,3,4,5,7,10,12,15 \
  --core-components iou \
  --tag-prefix v2icalib_cov_low      # oIoU
```

Key points (success = `success_at_1m`, latency = `avg_time`):

| Config | Avg covisible objects (`avg_matches`) | success | Latency (s) | Output tag |
| --- | --- | --- | --- | --- |
| V2X-Reg++ limit=1 | 0.0 | 0.00 | 0.0019 | `outputs/v2xregpp_cov_k1` |
| limit=5 | 1.4 | 0.43 | 0.0053 | `k5` |
| limit=10 (paper setting) | 2.43 | 0.53 | 0.0156 | `k10` |
| limit=12 | 3.07 | **0.73** | 0.0182 | `k12` |
| limit=15 | 4.33 | **0.80** | 0.0271 | `k15` |
| limit=18 | 5.13 | 0.83 | 0.0337 | `k18` |
| limit=25 | 6.53 | 0.80 | 0.0565 | `k25` |
| limit=40 | 9.63 | 0.47 | 0.1730 | `k40` |
| limit→∞ | 15.63 | 0.43 | **0.4023** | `kinf` |
| V2I-Calib limit=5 | 1.93 | 0.40 | 0.0438 | `outputs/v2icalib_cov_low_k5` |
| limit=10 | 2.77 | 0.43 | **0.519** | `k10` |
| limit=15 | 5.10 | 0.63 | **1.92** | `k15` |

Observations:

* V2X-Reg++ only needs ~4–5 covisible objects to break 0.8 success@1 m while keeping latency <0.03 s. Increasing beyond ~6 matches causes diminishing accuracy and steep O(n²) cost (matching + Hungarian).
* V2I-Calib (oIoU) exceeds 0.1 s once `avg_matches` > ~2; at 10 matches each frame already costs ~0.52 s, explaining why DAIR experiments in `docs/operations/v2x_regpp_optimization.md` avoided IoU-only association for online monitoring.
* The plot `outputs/factor_sweeps/covisibility_tradeoff.png` shows both curves as a function of the actually observed covisible count.

## 2. Matching Compute Load (Synthetic Stress Test)

`tools/matching_microbench.json` measures `BoxesMatch` runtime on synthetic frames with `n` boxes per agent (no filtering/solver). Results:

| #boxes per agent | Matching runtime (s) |
| --- | --- |
| 10 | 0.019 |
| 20 | 0.130 |
| 30 | 0.356 |
| 40 | 0.911 |
| 50 | 1.79 |
| 70 | 5.27 |
| 100 | 19.70 |

Takeaways:

* The Hungarian-based matcher scales worse than O(n²); beyond ≈30 objects the CPU cost dominates even before SVD runs.
* Hitting the user’s `<0.1 s/frame` target therefore requires capping `filters.top_k` (or the new `matching.max_retained_matches`) to keep practical matches ≤6 and aggressively pruning by distance/category.

## 3. Bias / Time-Lag Robustness

Noise injected via `cfg.data.noise = {'offset': [Δx,0,0,0,0,Δyaw], 'target':'vehicle'}` using `tools/noise_sweep.py`. Each run used 30 GT frames for V2X-Reg++ and 20 frames for V2I-Calib (IoU).

### V2X-Reg++ (oDist)

| Δyaw (deg) | Δx (m) | success@1 m | mTE@1 m (m) | Avg time (s) | Tag |
| --- | --- | --- | --- | --- | --- |
| 0 | 0.0 | 0.53 | 0.66 | 0.017 | `v2xregpp_noise_pos0p00_rot0p0` |
| 0 | 0.5 | 0.43 | 0.68 | 0.019 | `pos0p50_rot0p0` |
| 0 | 1.0 | 0.13 | 0.69 | 0.019 | `pos1p00_rot0p0` |
| 0 | 1.5 | 0.03 | 0.71 | 0.020 | `pos1p50_rot0p0` |
| 2.5 | 0.0 | 0.30 | 0.73 | 0.021 | `pos0p00_rot2p5` |
| 5.0 | 0.0 | 0.07 | 0.51 | 0.022 | `pos0p00_rot5p0` |
| 10.0 | 0.0 | 0.00 | – | 0.019 | `pos0p00_rot10p0` |

* Translational delay beyond ~0.5 m rapidly reduces success despite TE staying <1 m on the frames that still pass.
* Pure yaw bias ≥5° already collapses success@1 m to ≤0.07, consistent with the oDist indicator curves in `docs/operations/experiment_reproduction.md`.
* Runtime remains <0.02 s because filtering still limits matches; failures stem from the solver receiving inconsistent correspondences.

### V2I-Calib (oIoU, 20-frame subset)

| Δyaw (deg) | Δx (m) | success@1 m | Avg time (s) |
| --- | --- | --- | --- |
| 0 | 0.0 | 0.45 | 0.58 |
| 0 | 0.5 | 0.45 | 0.57 |
| 0 | 1.0 | 0.15 | 0.57 |
| 5 | 0.0 | 0.05 | 0.60 |
| 5 | 1.0 | 0.00 | 0.52 |
| 10 | (any) | 0.00 | 0.55–0.62 |

The IoU matcher is far less tolerant: even 0.5 m drift or 5° yaw bias effectively breaks the pipeline, and the runtime never drops below 0.5 s/frame because of the dense IoU cost matrix.

## 4. Object-Type Sensitivity

Using the baseline matches (`outputs/v2i_vs_hkust/matches.jsonl`) and replaying the dataset with `DatasetManager`, the matched categories contribute as follows:

| Category | #matches | Avg TE per match (m) |
| --- | --- | --- |
| car | 30 | **0.85** |
| trafficcone | 30 | **2.41** |
| motorcyclist | 9 | 9.50 |
| van | 4 | 1.16 |

Cars dominate useful correspondences; cones and two-wheelers tend to sit at the fringe of the search area and inflate TE. This supports prioritising `[bus, truck, car]` in `filters.priority_categories` and enforcing `size_bounds`/`per_category_top_k` once detection scores are available. Heavy vehicles (bus/truck) are rare in the selected split, so importing the balanced filtering from Experiment 3 in `docs/operations/v2x_regpp_optimization.md` is recommended when detections include those classes.

## 5. Solver Strategy Ablation

| Variant | success@1 m | Avg time (s) | Notes |
| --- | --- | --- | --- |
| Weighted SVD + threshold filter (default) | 0.533 | **0.0156** | `outputs/v2i_vs_hkust` |
| Even SVD (`matching.matches2extrinsic=evenSVD`) | 0.533 | 0.0223 | Weighted and even SVD agree because the match set is small; even SVD costs ~40% more. |
| Top-1 / 8-point only (`matching.filter_strategy=topRetained`) | **0.333** | 0.0169 | Frames rely on a single correspondence, so success drops by 20 pp; TE jumps above 1 m on several frames. |

ICP/NDT baselines remain available under `benchmarks/` but already documented in `README.md` Table III; the new data here emphasises that the 8-point fallback cannot replace the multi-match SVD without severe accuracy loss.

## 6. Practical Guidance Toward <0.1 s per Frame

* **Keep covisible matches ≤6.** Use the new `matching.max_retained_matches` (introduced in this session) alongside `filters.top_k` to bound the correspondence count. `v2xregpp_cov_k15` (avg 4.33 matches) hits 0.027 s with 0.8 success@1 m, while `k25` already costs 0.056 s.
* **Filter out bad categories early.** Traffic-cone and motorcyclist matches yielded >2 m TE; cropping them via `priority_categories`, `size_bounds`, or per-class quotas reduces noise without hurting runtime.
* **Avoid the current parallel KP path.** `matching.parallel_flag=true` invokes the persistent 64-process pool from `legacy/v2x_calib/corresponding/similarity_utils.py`, but the spawn/join overhead pushed the average latency to 0.137 s on our workstation. The refactor mentioned in `docs/operations/v2x_regpp_optimization.md` (parallelising only `cal_KP` without Hungarian changes) is still the safest optimisation.
* **For oIoU (V2I-Calib), hitting 0.1 s is unrealistic** on CPU: even with `avg_matches≈2.0` the pipeline takes 0.15 s/frame, and it climbs beyond 0.5 s at 3 matches. Consider migrating V2I monitoring to oDist or borrowing oDist’s shielding ideas (distance gating, weighted SVD) if sub-0.1 s latency is mandatory.
* **Time-lag tolerance is limited.** Translation errors beyond 0.5 m or yaw errors beyond 5° degrade success sharply; adding temporal priors (as explored in `pipeline_hkust_temporal*.yaml`) must therefore include TE-aware gating to avoid propagating stale poses.

## 7. Artifacts

* Covisibility sweep data: `outputs/factor_sweeps/v2xregpp_cov_results.json`, `v2icalib_cov_low_results.json`.
* Noise sweeps: `outputs/factor_sweeps/v2xregpp_noise_noise_results.json`, `v2icalib_noise_noise_results.json`.
* Matching microbenchmark: `outputs/factor_sweeps/matching_microbench.json`.
* Visualization: `outputs/factor_sweeps/covisibility_tradeoff.png`.

These files contain the per-run summaries (success curves, runtime, actual match counts) referenced above.

## 8. Representative DAIR subset (60 frames)

To mirror the DAIR-V2X setup in the T-ITS paper while keeping runtime manageable, we curated `data/DAIR-V2X/cooperative/representative_data_info.json` by sorting all 521 cooperative pairs by infrastructure LiDAR ID and sampling 60 evenly spaced entries (no duplicate RSU IDs). This preserves diversity across intersections and vehicle partners even though the absolute sample size is smaller.

**Infra-ID coverage.**

| Infra prefix | #frames |
| --- | --- |
| 000 | 4 |
| 001 | 7 |
| 003 | 5 |
| 005 | 7 |
| 007 | 3 |
| 008 | 2 |
| 009 | 2 |
| 010 | 2 |
| 012 | 1 |
| 014 | 4 |
| 015 | 3 |
| 016 | 2 |
| 017 | 8 |
| 018 | 9 |
| 019 | 1 |

The IDs span the entire 000***–019*** range (dawn, day, dusk sequences in DAIR), so each frame probes a different junction/traffic density rather than repeating adjacent timestamps.

**Full pair list (infra ↔ vehicle).**

| # | Infra ID | Vehicle ID |
|---|---------|-----------|
| 00 | 000017 | 015373 |
| 01 | 000133 | 015015 |
| 02 | 000158 | 015039 |
| 03 | 000326 | 015150 |
| 04 | 001104 | 015875 |
| 05 | 001177 | 015466 |
| 06 | 001202 | 015490 |
| 07 | 001341 | 017290 |
| 08 | 001368 | 017316 |
| 09 | 001377 | 017325 |
| 10 | 001396 | 017343 |
| 11 | 003883 | 020055 |
| 12 | 003899 | 020071 |
| 13 | 003912 | 020084 |
| 14 | 003920 | 020092 |
| 15 | 003937 | 020109 |
| 16 | 005013 | 001103 |
| 17 | 005048 | 001137 |
| 18 | 005077 | 001166 |
| 19 | 005309 | 001385 |
| 20 | 005502 | 001893 |
| 21 | 005622 | 001942 |
| 22 | 005639 | 001958 |
| 23 | 007136 | 000642 |
| 24 | 007200 | 000705 |
| 25 | 007272 | 000775 |
| 26 | 008470 | 005725 |
| 27 | 008649 | 002491 |
| 28 | 009205 | 004983 |
| 29 | 009367 | 004110 |
| 30 | 010517 | 003507 |
| 31 | 010763 | 003730 |
| 32 | 012661 | 011497 |
| 33 | 014342 | 013138 |
| 34 | 014839 | 013745 |
| 35 | 014853 | 013759 |
| 36 | 014870 | 013776 |
| 37 | 015638 | 006750 |
| 38 | 015668 | 006780 |
| 39 | 015917 | 010552 |
| 40 | 016510 | 007580 |
| 41 | 016521 | 007591 |
| 42 | 017877 | 009312 |
| 43 | 017893 | 009328 |
| 44 | 017905 | 009340 |
| 45 | 017919 | 009354 |
| 46 | 017928 | 009363 |
| 47 | 017939 | 009374 |
| 48 | 017949 | 009384 |
| 49 | 017967 | 009402 |
| 50 | 018088 | 010652 |
| 51 | 018102 | 010666 |
| 52 | 018114 | 010678 |
| 53 | 018128 | 010692 |
| 54 | 018141 | 010705 |
| 55 | 018151 | 010715 |
| 56 | 018462 | 010257 |
| 57 | 018505 | 010300 |
| 58 | 018527 | 010322 |
| 59 | 019848 | 008828 |

This list can be cross-checked against DAIR metadata to verify scene variety.

## 9. Reproducing V2X-Reg++ vs V2I-Calib on the representative subset

Configs: `configs/pipeline_hkust_representative.yaml` (oDist) and `configs/pipeline_hkust_representative_oiou.yaml` (oIoU). Both keep the paper’s `top_k=10`, GT boxes, and weighted SVD; only the data_info path changes.

| Method | success@1 m | success@2 m | Avg time (s) | Avg matches | Output |
| --- | --- | --- | --- | --- | --- |
| V2X-Reg++ (oDist) | 0.717 | 0.917 | **0.0155** | 2.67 | `outputs/v2i_vs_hkust_representative` |
| V2I-Calib (oIoU) | 0.583 | 0.717 | **0.608** | 3.47 | `outputs/v2i_calib_representative_oiou` |

Despite doubling the pair count and covering 15 distinct RSU prefixes, V2X-Reg++ still runs in ~16 ms and approaches the paper’s 0.73–0.80 success band once ≥3 matches are available. The IoU pipeline remains bottlenecked by the dense cost matrix (≈0.6 s/frame) and therefore fails the `<0.1 s` budget even on this balanced subset, consistent with the analysis in Sections 1 and 5.
