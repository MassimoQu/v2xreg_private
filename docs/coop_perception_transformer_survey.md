# Cooperative Perception Transformer Survey (PE / Extrinsics / Hybrid vs "End-to-End")

This note summarizes several representative cooperative-perception codebases (mostly under `external/`) with a focus on:

- Where "position" enters the transformer: 2D BEV PE, 2D relative bias, 3D reference points for sampling, or explicit xyz->embedding.
- How extrinsics / poses are consumed (2D approximation vs full 3D), and whether there is any explicit robustness handling.
- Whether the model is "hybrid" (CNN/voxel backbone + transformer fusion + CNN detection head) or closer to end-to-end transformer detection (DETR-style queries).

Terminology used in this document:

- 2D BEV PE: absolute positional encoding on a BEV grid (learned row/col or sine), i.e., tokens live on an (x,y) plane.
- 2D relative bias: window-attention bias indexed by (dx,dy) in a 2D window.
- 3D reference points: (x,y,z) points used by deformable attention for sampling/projection; this is *not* the same as "3D token PE".
- 3D coord PE: explicitly embedding xyz (or xy+z) into an MLP/Conv/Fourier embedding and injecting it into attention.
- "Extrinsics robustness": whether the repo contains explicit mechanisms for noisy poses/extrinsics (pose noise injection, learnable refinement, masking/gating under misalignment, etc.). When absent, assume "requires accurate extrinsics".

---

## 1) Quick Comparison Table

Legend:

- Fusion transformer: transformer is used to exchange/aggregate features across agents (or across views).
- Detection head:
  - "CNN head": conv cls/reg heads (often anchor-based) on BEV feature maps.
  - "DETR-like": transformer decoder + NMS-free coder (query-based, Hungarian assignment, etc.).

| Method / Repo | Modality | Transformer usage | Detection head | Position encoding (2D vs 3D) | Extrinsics usage (2D vs 3D) | Explicit extrinsics robustness handling |
|---|---|---|---|---|---|---|
| UniAD (`external/UniAD`) | single-agent (camera-centric BEV) | BEVFormer encoder/decoder | DETR-like | 2D BEV learned PE + 3D ref points for sampling (`ref_3d`) | camera `lidar2img` projection; temporal ego-motion shift | none found (assumes accurate calibration / ego motion) |
| VAD (`external/VAD`) | single-agent (camera-centric BEV) | BEVFormer + planning/motion transformers | DETR-like | same as UniAD + many `pos2posemb2d` for interaction/motion | same as UniAD | none found |
| UniMM-V2X (`external/UniMM-V2X`) | cooperative (vehicle + infra, BEVFormer-like) | BEVFormer + cross-agent query fusion | DETR-like | BEV token PE is 2D learned; cross-agent queries embed xyz via MLP | uses full 4x4 calib (inf->veh) for query ref points; also concatenates 3x3 rotation into features | partial: query matching tolerance + uses rotation embedding, but no explicit pose-noise training found |
| V2X-ViT (`external/v2x-vit`) | cooperative (LiDAR BEV) | transformer fusion over BEV features | CNN head | 2D window relative bias (mswin); no 3D token PE | uses pairwise 4x4 but **reduced to 2D affine** (x,y,yaw) for warping; postprocess also assumes small z | partial: ROI overlap masking; no explicit pose-noise injection found |
| CoBEVT (`external/CoBEVT_clean`) | cooperative (camera BEV) | cross-view attention + (optional) window attention | mostly CNN heads (seg/heatmap style in OPV2V adapter) | 2D window relative bias; BEV query_pos from (x,y) via Conv2d(2->d); image/cam embedding from 3D rays | uses intrinsics/extrinsics to build ray and camera-center embeddings; no explicit pose-noise handling found | none found |
| MaskBEV (`external/mask_bev`) | single-agent (LiDAR) | transformer-like heads (Mask2Former) + PE | task-dependent; often CNN-ish heads + transformers in segmentation | 3D point/voxel coordinate Fourier PE + 2D sine PE in 2D decoders | no cross-agent extrinsics | N/A |
| BEVerse (`external/BEVerse`) | single-agent (camera BEV) | transformer in some heads + Swin | mixed | Swin 2D relative bias; GroupFree3D head uses xyz->ConvBN positional encoding | camera calibration + BEV geometry; no cooperative extrinsics | N/A |
| LiDARFormer (paper; `/tmp/paper_pe/lidarformer.txt`) | single-agent (LiDAR) | deformable attention between sparse voxels and dense BEV slices | mixed | uses voxel coordinates (u,v,h) for selecting queries; no explicit "3D RoPE for tokens" | no cooperative extrinsics | N/A |
| IFTR (`external/IFTR`) | cooperative (camera-only) | BEVFormer-like + instance-level fusion transformer | DETR-like | 2D BEV learned PE + 3D ref points for sampling | uses pairwise 4x4 transforms (`pairwise_t_matrix`) when projecting sampling points across agents | **yes**: supports pose noise injection (x,y,yaw) via `noise_setting` + `pose_utils.py` |
| HM-ViT (`external/HM-ViT`) | cooperative (hetero camera/LiDAR) | transformer for fusion (various) | CNN head (PointPillars-style) | mostly 2D (BEV/window) positional priors | typical OpenCOOD-style pairwise transforms; no explicit pose-noise support noticed (not fully audited) | none found (quick scan) |
| CMTCoop (`external/CMT-Cooperative-Perception`) | cooperative (multi-modal) | transformer-based detector / fusion | DETR-like (query-based) | uses BEV + RV (range-view) query embeddings; explicit BEV coords -> embedding | not audited end-to-end for pose-noise, but repo contains multiple "noise" knobs (mostly bbox noise / augmentation) | partial (needs deeper audit for pose/extrinsics noise specifically) |

---

## 2) What These Repos Do With Extrinsics (and Why Robustness Often Drops)

### A) "Warp-then-fuse" BEV pipelines (typical OpenCOOD style)

Representative: `external/v2x-vit`.

- How extrinsics enter:
  - A pairwise 4x4 transform is provided, but the implementation discretizes and drops z, keeping only a 2D affine (x,y,yaw) before `warp_affine`.
  - Example: `external/v2x-vit/v2xvit/models/sub_modules/torch_transformation_utils.py` converts `(B,L,4,4)` -> `(B,L,2,3)` and normalizes translation by `(discrete_ratio * downsample_rate)`.
- Special handling:
  - ROI overlap mask to avoid fusing non-overlapping areas: `get_roi_and_cav_mask(...)`.
  - Temporal prior encoding (dt, dv, infra flag) + optional RTE.
  - Post-processing assumes "z deviation is small" in BEV projection: `external/v2x-vit/v2xvit/data_utils/post_processor/bev_postprocessor.py`.
- Robustness expectation:
  - Sensitive to pose noise because fusion assumes correct geometric alignment (even if attention is used after warping).
  - Quantization/discretization can amplify small translation errors when BEV resolution is high.

### B) "Geometry-aware attention" (no hard BEV warping, but extrinsics shape attention)

Representative: `external/CoBEVT_clean`.

- How extrinsics enter:
  - Uses intrinsics/extrinsics to build camera-center embeddings and ray direction embeddings; these are added to key/value features and to BEV query positional terms.
  - The BEV positional term itself is still 2D (xy).
- Special handling:
  - 2D relative position bias inside local window attention (if enabled).
  - No explicit pose-noise injection found in the checked files.
- Robustness expectation:
  - Potentially less brittle than strict warp-then-sum because attention can learn soft associations, but still relies on accurate extrinsics to build correct geometric cues.

### C) "Query-level cross-agent fusion" on top of DETR-like heads

Representative: `external/UniMM-V2X`.

- How extrinsics enter:
  - Converts infra ref points into vehicle frame using a full 4x4 calibration matrix.
  - Concatenates rotation matrix (3x3 -> 9D) into query features to align distributions across agents.
  - Matching between agents is based on ref-point distances + Hungarian assignment.
- Special handling:
  - Matching has explicit distance filtering; this provides *some* tolerance to small pose errors, but hard thresholds will break when error >~ 1m (in this implementation).
- Robustness expectation:
  - More "3D-aware" than 2D affine warping, but still not intrinsically robust unless trained with pose noise or a learnable extrinsic refinement module.

### D) Explicit pose-noise injection / robustness evaluation hooks

Representative: `external/IFTR`.

- How extrinsics enter:
  - Uses pairwise 4x4 transforms (`pairwise_t_matrix`) when mapping sampling reference points across agents.
- Special handling:
  - Provides `noise_setting` in dataset pipeline to perturb `lidar_pose` by (x,y,yaw) noise (Gaussian/Laplace), keeping a clean copy: `external/IFTR/opencood/utils/pose_utils.py`.
- Robustness expectation:
  - This is the most "direct" code support for extrinsics robustness testing among the inspected camera-coop repos.

---

## 3) Are These "Mostly Transformer" or "Fully Transformer End-to-End"?

In cooperative perception, "all transformer" can mean different things:

1) Strict all-transformer:
   - No CNN / sparse conv backbone; raw points/images -> tokens -> transformers -> outputs.
   - Rare in 3D detection due to compute/memory, especially for multi-agent.

2) End-to-end transformer detection (common in BEVFormer family):
   - CNN (or sparse conv) backbone still exists, but detection uses transformer decoder queries + NMS-free coder (DETR-like).
   - Fusion can also be transformer-based.

3) Hybrid (most OpenCOOD baselines):
   - Voxel/Pillar backbone (PointPillars/SECOND) + (optional) transformer fusion + CNN detection head (conv cls/reg on BEV).

Where the surveyed repos fall:

- Hybrid (transformer mainly in fusion; CNN head):
  - `external/v2x-vit` (PointPillars + transformer fusion + conv heads)
  - `external/HM-ViT` (PointPillars-style + conv heads)
  - `external/CoBEVT_clean` OPV2V adapter (often heatmap/seg style heads)

- DETR-like (transformer decoder does detection; closer to end-to-end):
  - `external/UniMM-V2X` (query-based tracking/detection; plus cross-agent query fusion)
  - `external/IFTR` (BEVFormer-like detection + instance-level fusion)
  - (Single-agent references) `external/UniAD`, `external/VAD`
  - `external/CMT-Cooperative-Perception` (query-based, multi-modal; repo claims DETR-like)

---

## 4) If You Want "All Transformer" Cooperative Perception: Practical Options

If you mean "DETR-like end-to-end detection + transformer fusion" (but still allowing CNN/sparse-conv backbones), then the most relevant inspected candidates are:

- IFTR (`external/IFTR`): camera-only cooperative; transformer BEV + DETR-like head; includes pose-noise injection hooks.
- UniMM-V2X (`external/UniMM-V2X`): cooperative vehicle+infra; DETR-like head; query-level cross-agent fusion uses full 3D calib and rotation embedding.
- CMTCoop (`external/CMT-Cooperative-Perception`): transformer detector for multi-modal cooperative; requires deeper audit if your focus is specifically OPV2V and pose-noise robustness.

If you mean *strict* "no CNN / no sparse conv anywhere", then (based on the inspected repos) you will likely need to build it yourself by combining:

- a transformer tokenization/backbone (ViT for images; PointTransformer-like for points), and
- a transformer-based cooperative fusion module, and
- a DETR-like decoder head.

---

## 5) Code Pointers (for Fast Grep)

Selected entry points and key files:

- UniAD:
  - 2D BEV PE: `external/UniAD/projects/mmdet3d_plugin/uniad/dense_heads/bevformer_head.py`
  - 3D/2D reference points: `external/UniAD/projects/mmdet3d_plugin/uniad/modules/encoder.py`
- VAD:
  - 2D BEV PE config: `external/VAD/projects/configs/VAD/VAD_base_e2e.py`
  - 3D/2D reference points: `external/VAD/projects/mmdet3d_plugin/VAD/modules/encoder.py`
- UniMM-V2X:
  - agent query fusion (3D ref pts + rot embedding): `external/UniMM-V2X/projects/mmdet3d_plugin/unimmv2x/fusion_modules/agent_fusion.py`
- V2X-ViT:
  - 2D relative bias: `external/v2x-vit/v2xvit/models/sub_modules/mswin.py`
  - 2D extrinsics warp + ROI mask: `external/v2x-vit/v2xvit/models/sub_modules/torch_transformation_utils.py`
  - STTF warping: `external/v2x-vit/v2xvit/models/sub_modules/v2xvit_basic.py`
  - z~0 assumption in postprocess: `external/v2x-vit/v2xvit/data_utils/post_processor/bev_postprocessor.py`
- CoBEVT:
  - 2D relative bias + geometry embeddings: `external/CoBEVT_clean/nuscenes/cross_view_transformer/model/encoder_pyramid_axial.py`
  - OPV2V CVT module: `external/CoBEVT_clean/opv2v/opencood/models/sub_modules/cvt_modules.py`
- IFTR:
  - cooperative BEVFormer encoder w/ pairwise transforms: `external/IFTR/opencood/mmdet3d/projects/mmdet3d_plugin/IFTR/modules/encoder.py`
  - pose noise injection: `external/IFTR/opencood/utils/pose_utils.py`

