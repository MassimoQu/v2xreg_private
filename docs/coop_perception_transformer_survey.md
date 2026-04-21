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
| V2VFormer (paper; `/tmp/paper_pe2/v2vformer.pdf`) | cooperative (LiDAR BEV) | spatial-channel transformer for feature fusion | CNN head (voxel/pillar detector head) | BEV token space is 2D; no DETR-style set prediction | built on VoxelNet/SECOND/PointPillars; fusion operates on voxel/pillar features | none found (paper focuses on fusion) |
| CoBEVT (`external/CoBEVT_clean`) | cooperative (camera BEV) | cross-view attention + (optional) window attention | mostly CNN heads (seg/heatmap style in OPV2V adapter) | 2D window relative bias; BEV query_pos from (x,y) via Conv2d(2->d); image/cam embedding from 3D rays | uses intrinsics/extrinsics to build ray and camera-center embeddings; no explicit pose-noise handling found | none found |
| MaskBEV (`external/mask_bev`) | single-agent (LiDAR) | transformer-like heads (Mask2Former) + PE | task-dependent; often CNN-ish heads + transformers in segmentation | 3D point/voxel coordinate Fourier PE + 2D sine PE in 2D decoders | no cross-agent extrinsics | N/A |
| BEVerse (`external/BEVerse`) | single-agent (camera BEV) | transformer in some heads + Swin | mixed | Swin 2D relative bias; GroupFree3D head uses xyz->ConvBN positional encoding | camera calibration + BEV geometry; no cooperative extrinsics | N/A |
| LiDARFormer (paper; `/tmp/paper_pe/lidarformer.txt`) | single-agent (LiDAR) | deformable attention between sparse voxels and dense BEV slices | mixed | uses voxel coordinates (u,v,h) for selecting queries; no explicit "3D RoPE for tokens" | no cooperative extrinsics | N/A |
| IFTR (`external/IFTR`) | cooperative (camera-only) | BEVFormer-like + instance-level fusion transformer | DETR-like | 2D BEV learned PE + 3D ref points for sampling | uses pairwise 4x4 transforms (`pairwise_t_matrix`) when projecting sampling points across agents | **yes**: supports pose noise injection (x,y,yaw) via `noise_setting` + `pose_utils.py` |
| ActFormer (paper; `https://arxiv.org/abs/2403.04968`, code: `https://github.com/coperception/ActFormer`) | cooperative (camera-only) | BEV queries + sparse "active" query graph for multi-agent multi-camera | DETR-like ("DETR head [36]") | BEVFormer-style: 2D BEV query positions + per-query 3D ref points for sampling | uses pose/extrinsics to project BEV ref points to images; query selects relevant cameras based on pose | none found |
| HM-ViT (`external/HM-ViT`) | cooperative (hetero camera/LiDAR) | transformer for fusion (various) | CNN head (PointPillars-style) | mostly 2D (BEV/window) positional priors | typical OpenCOOD-style pairwise transforms; no explicit pose-noise support noticed (not fully audited) | none found (quick scan) |
| CMTCoop (`external/CMT-Cooperative-Perception`) | cooperative (multi-modal) | transformer-based detector / fusion | DETR-like (query-based) | uses BEV + RV (range-view) query embeddings; explicit BEV coords -> embedding | not audited end-to-end for pose-noise, but repo contains multiple "noise" knobs (mostly bbox noise / augmentation) | partial (needs deeper audit for pose/extrinsics noise specifically) |
| CoCMT (paper; `https://arxiv.org/abs/2503.13504`, code: `https://github.com/taco-group/COCMT`) | cooperative (camera/LiDAR/hetero) | object-query-based fusion transformer (EQFormer) + deep supervision | DETR-like (bipartite matching on object queries) | tokens are object queries; uses object-center coords as reference points + distance-masked MHSA | object queries transformed to ego/global for fusion (full pose assumed); LiDAR variant uses PointPillars encoder | none found |
| SlimComm (paper; `https://arxiv.org/abs/2508.13007`) | cooperative (LiDAR + 4D radar) | sparse query exchange + gated multi-scale deformable attention fusion | CNN head (PointPillars head) | BEV query locations + deformable-attn sampling; not set-prediction detection | broadcasts BEV query locations + global pose; warps BEV-level priors to ego frame | **yes (eval)**: explicitly evaluates localization/heading noise; no learnable refinement found |

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
  - V2VFormer paper (`/tmp/paper_pe2/v2vformer.pdf`) (VoxelNet/SECOND/PointPillars + transformer fusion)
  - `external/HM-ViT` (PointPillars-style + conv heads)
  - `external/CoBEVT_clean` OPV2V adapter (often heatmap/seg style heads)
  - SlimComm paper (`https://arxiv.org/abs/2508.13007`) (PointPillars head; transformer is in sparse comm/fusion)

- DETR-like (transformer decoder does detection; closer to end-to-end):
  - `external/UniMM-V2X` (query-based tracking/detection; plus cross-agent query fusion)
  - `external/IFTR` (BEVFormer-like detection + instance-level fusion)
  - ActFormer (`https://arxiv.org/abs/2403.04968`, code: `https://github.com/coperception/ActFormer`) (BEV queries + DETR head; scalable via active queries)
  - CoCMT (`https://arxiv.org/abs/2503.13504`, code: `https://github.com/taco-group/COCMT`) (object-query fusion + bipartite matching)
  - (Single-agent references) `external/UniAD`, `external/VAD`
  - `external/CMT-Cooperative-Perception` (query-based, multi-modal; repo claims DETR-like)

---

## 4) If You Want "All Transformer" Cooperative Perception: Practical Options

If you mean "DETR-like end-to-end detection + transformer fusion" (but still allowing CNN/sparse-conv backbones), then the most relevant inspected candidates are:

- IFTR (`external/IFTR`): camera-only cooperative; transformer BEV + DETR-like head; includes pose-noise injection hooks.
- UniMM-V2X (`external/UniMM-V2X`): cooperative vehicle+infra; DETR-like head; query-level cross-agent fusion uses full 3D calib and rotation embedding.
- CMTCoop (`external/CMT-Cooperative-Perception`): transformer detector for multi-modal cooperative; requires deeper audit if your focus is specifically OPV2V and pose-noise robustness.
- ActFormer (`https://arxiv.org/abs/2403.04968`, code: `https://github.com/coperception/ActFormer`): camera-only cooperative; BEVFormer-style BEV queries + DETR head; uses "active queries" to scale to many collaborators/cameras.
- CoCMT (`https://arxiv.org/abs/2503.13504`, code: `https://github.com/taco-group/COCMT`): object-query-based collaboration; query fusion is transformer; detection uses bipartite matching (DETR-like set prediction).

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
- ActFormer:
  - BEVFormer-derived 3D ref points + projection: `external/ActFormer/projects/mmdet3d_plugin/Actformer/modules/encoder.py`
  - pose/extrinsics embedding used for active query selection: `external/ActFormer/projects/mmdet3d_plugin/Actformer/modules/spatial_cross_attention.py`
- CoCMT:
  - object-query fusion w/ distance masks + pose-conditioned query encoding: `external/COCMT/opencood/models/cmt_camera_lidar_att_fuse.py`
  - query-based set prediction loss (assigner/sampler): `external/COCMT/opencood/loss/cmt_loss.py`

---

## 6) How "Position" Is Actually Encoded in These Methods

This section records what we observed in code/papers, and clarifies an important distinction:

- "Token positional encoding" (PE): something injected into Q/K (or token embeddings) so attention knows where a token is.
- "3D reference points": 3D points used to *sample/project* features (typically in deformable attention). This is geometry, but it is not the same as giving each token a 3D RoPE.

### 6.1 BEVFormer-family (IFTR / ActFormer / UniAD / VAD / HM-ViT BEVFormer branch)

Token type: dense BEV grid tokens (H x W), i.e., tokens live on an (x,y) plane.

Position injection:

- 2D BEV absolute PE: `LearnedPositionalEncoding` (learned row/col tables) -> `bev_pos = positional_encoding(bev_mask)`.
  - IFTR: `external/IFTR/opencood/mmdet3d/projects/mmdet3d_plugin/IFTR/dense_heads/iftr_head.py`
  - ActFormer: `external/ActFormer/projects/mmdet3d_plugin/Actformer/dense_heads/bevformer_head.py`
  - HM-ViT BEVFormer: `external/HM-ViT/opencood/models/mmdet3d_plugin/bevformer/dense_heads/bevformer_head.py`
- 3D reference points for spatial cross-attention (SCA):
  - `get_reference_points(..., dim='3d')` samples (x,y,z) points within each BEV pillar.
  - IFTR: `external/IFTR/opencood/mmdet3d/projects/mmdet3d_plugin/IFTR/modules/encoder.py`
  - ActFormer: `external/ActFormer/projects/mmdet3d_plugin/Actformer/modules/encoder.py`
- 2D reference points for temporal self-attention (TSA):
  - `get_reference_points(..., dim='2d')` provides (x,y) plane refs.

Key takeaway:

- The BEV token PE is still 2D (xy). The "3D-ness" is mainly in the sampling/projection step (ref_3d).

### 6.2 IFTR: multi-agent geometry enters via 4x4 transforms

IFTR extends the BEVFormer-style "3D reference-point sampling" into multi-agent:

- It uses `pairwise_t_matrix` (4x4) to map ego reference points into other agents' frames before projecting to cameras.
- See `point_sampling` in `external/IFTR/opencood/mmdet3d/projects/mmdet3d_plugin/IFTR/modules/encoder.py`.

This is still consistent with "2D token PE + 3D ref points", but now the 3D ref points are explicitly transformed across agents.

### 6.3 ActFormer: adds a "camera-pose-conditioned" gating on top of BEVFormer

ActFormer includes an additional mechanism beyond vanilla BEVFormer:

- It embeds per-camera `lidar2img` (flattened 4x4) via an MLP (`pose_embedding`) and uses it to produce a per-(camera,query) weight for selecting relevant cameras/queries.
- This is a form of "camera parameters as conditioning", but it is not PRoPE's projective attention; it is a learned gating on extrinsics.
- See `external/ActFormer/projects/mmdet3d_plugin/Actformer/modules/spatial_cross_attention.py`.

### 6.4 V2X-ViT: window attention uses 2D relative position bias (Swin-like)

Token type: BEV feature tokens (patch/window), still fundamentally 2D.

Position injection:

- Attention logits receive a learned table indexed by (dx,dy) within a local window ("relative position bias").
- See `external/v2x-vit/v2xvit/models/sub_modules/mswin.py`.

Note:

- Geometry/extrinsics are mostly consumed by BEV warping (often 2D affine in OpenCOOD-style pipelines), not by 3D token PE.

### 6.5 HM-ViT: multiple "position" signals depending on sub-module

HM-ViT contains several position-like injections:

- 2D relative bias for window attention in fusion modules:
  - `external/HM-ViT/opencood/models/sub_modules/hetero_fusion.py`
- Agent index (CAV id) sinusoid encoding:
  - `CavPositionalEncoding` in `external/HM-ViT/opencood/models/base_transformer.py`
- Relative temporal encoding (RTE) sinusoid:
  - `external/HM-ViT/opencood/models/base_transformer.py`
- If using its BEVFormer branch: 2D BEV learned PE via `positional_encoding(bev_mask)` as in other BEVFormer-family repos.

### 6.6 CoBEVT: geometry embeddings instead of a vanilla PE table

Token types:

- BEV grid tokens (query side)
- Image feature tokens (key/value side)

Position injection is largely geometry-driven:

- It builds an image embedding from camera ray directions and camera centers, and a BEV embedding from BEV grid coordinates and camera centers.
- The BEV "query_pos" is effectively `normalize(w_embed - c_embed)` per camera, rather than a simple learned 2D PE table.
- See `external/CoBEVT_clean/nuscenes/cross_view_transformer/model/encoder.py`.

### 6.7 CoCMT / CMTCoop: mixed 2D BEV embeddings + projection-based RV embeddings + pose-conditioned query modulation

CoCMT/CMT family uses multiple positional signals:

- BEV pos embedding: 2D sin/cos embedding on BEV coordinates (then a linear/conv embedding):
  - `pos2embed` in `external/COCMT/opencood/models/mmdet3d_plugin/models/dense_heads/cmt_head.py`
- RV (range-view / image-view) embedding: constructed from 3D ref points projected to images (and reprojected/backprojected with depth bins):
  - `_rv_query_embed` in `external/COCMT/opencood/models/mmdet3d_plugin/models/dense_heads/cmt_head.py`
- Cooperative (multi-agent) stage:
  - Uses predicted 3D object centers as reference points, and builds distance masks for query fusion.
  - Encodes the 3D rigid transform (3x4) with a NeRF-style Fourier PE (144-D) to modulate the other-agent object queries (MLN).
  - See `external/COCMT/opencood/models/cmt_camera_lidar_att_fuse.py` and `external/COCMT/opencood/models/mmdet3d_plugin/models/utils/mln_utils.py`.

### 6.8 VRoPE / PRoPE (what they are, and what they are not)

We have local copies under:

- VRoPE: `external/VRoPE` (video LLM rotary embedding; general N-D RoPE implementation in `external/VRoPE/vrope.py`)
- PRoPE: `external/prope` (camera conditioning via relative projective transform; PyTorch impl in `external/prope/prope/torch.py`)

Important note:

- None of the inspected cooperative-perception repos appear to directly use RoPE/VRoPE today (quick grep found no `RoPE` / `rotary` usage).
- PRoPE is designed for multi-view image-token attention (camera conditioning). It is not a drop-in replacement for BEV grid PE without re-deriving what "tokens" represent.

---

## 7) Theory: 2D PE vs 3D PE (and Two Practical Design Routes)

### 7.1 Start from "what is a token?"

Position encodings only make sense relative to token semantics:

- BEV grid token: represents a cell (x,y) on the ground plane, usually aggregating height into channels. It does not have a unique z.
- 3D voxel / point token: represents a unique 3D location (x,y,z) (or a small neighborhood in 3D).
- Object query token (DETR-like): represents a latent "object slot" that is often anchored by a learned/predicted 3D reference point.
- Image patch token: lives on the image plane, but camera parameters define a 3D ray for that token.

A common failure mode is to give a token a positional signal that does not match what the token represents.

### 7.2 Attention needs position because it is permutation-equivariant

Vanilla self-attention (single head) can be written as:

- q_i = W_q h_i, k_j = W_k h_j, v_j = W_v h_j
- a_ij = softmax_j( (q_i^T k_j) / sqrt(d) )
- y_i = sum_j a_ij v_j

If we permute tokens, the output permutes the same way. There is no built-in notion of "adjacent in space".

Position can enter attention in (at least) three standard ways:

1) Additive absolute PE:
   - h_i <- h_i + PE(p_i)
2) Additive relative bias:
   - a_ij <- softmax_j( (q_i^T k_j)/sqrt(d) + b(p_i - p_j) )
3) Rotary / phase-based (RoPE-like):
   - q_i <- R(p_i) q_i, k_j <- R(p_j) k_j
   - so that q_i^T k_j becomes a function of the relative offset under certain constructions.

### 7.3 2D PE: when it is the "correct" inductive bias

If tokens live on a BEV plane, then 2D PE is the natural choice:

- Absolute 2D PE (learned row/col or 2D sine):
  - helps encode "where on the map" a cell is.
  - tends to be less translation-equivariant.
- Relative 2D bias (Swin-like window bias):
  - makes attention depend primarily on (dx,dy), which is closer to translation-equivariant locality.

For BEV pipelines in autonomous driving, many cues are fundamentally 2.5D (objects are near ground plane, z is often a secondary cue). This is why 2D PE is often stable and data-efficient.

### 7.4 3D PE: when it is meaningful (and when it is not)

3D PE is meaningful only if each token has a stable 3D location:

- 3D voxels/points: yes.
- Object queries with reference points: yes (the ref point is the 3D anchor).
- BEV grid cells: not really (no unique z).

In practice, "3D" enters many BEVFormer-style models as 3D reference points used for sampling/projection. This is geometry, but it does not turn BEV tokens into 3D tokens.

### 7.5 Why naive "replace 2D PE with 3D PE" often hurts

Theoretical reasons you should expect a drop if you do a naive swap (especially without re-training):

- Token mismatch:
  - a BEV cell has no unique z; adding a fake z can inject noise and reduce identifiability.
- Scale/frequency sensitivity:
  - Fourier/RoPE-style encodings are very sensitive to coordinate normalization and frequency design.
  - small pose/extrinsics errors can translate into large phase errors for high-frequency encodings.
- Distribution shift:
  - swapping PE changes the input distribution of all attention blocks; without full re-training, degradation is expected.
- Implementation mismatch:
  - RoPE/VRoPE is not a drop-in replacement for "additive PE"; it rotates Q/K. A naive "replace embedding tensor" is not equivalent.

### 7.6 Route (1): keep 2D BEV tokens, inject 3D geometry into cross-attn / sampling / biases

This route keeps token semantics consistent:

- BEV tokens remain (x,y) tokens with 2D PE (absolute or relative).
- 3D geometry enters only where it is needed: alignment across views/agents.

Mechanisms:

1) Hard geometry via 3D reference-point sampling (BEVFormer-style):
   - For each BEV cell i at (x_i,y_i), sample D heights z_d and form r_{i,d}=(x_i,y_i,z_d).
   - Use camera intrinsics/extrinsics (and/or inter-agent SE(3)) to project r_{i,d} to the source feature space.
   - Sample key/value features at those projected locations and aggregate them into the BEV token.

2) Soft geometry via attention bias / gating:
   - Add a geometric term to attention logits:
     - logit_ij = (q_i^T k_j)/sqrt(d) + g(Delta_ij, calib_ij)
   - where Delta_ij can include (dx,dy,dz,||d||,dyaw), and calib_ij encodes relative pose.
   - g can be a small MLP or an RBF kernel.

Where PRoPE/VRoPE could fit (conceptually):

- PRoPE is best matched to image-token attention (multi-view camera tokens). It can be used to condition cross-view attention on relative projective transforms.
- VRoPE could be used on 3D reference points or object queries *after* transforming everything into a shared frame (e.g., ego frame), but it should not be treated as a BEV-grid PE replacement.

Expected robustness profile:

- Hard warp-then-sum is brittle under pose noise (misalignment + discretization).
- Geometry-conditioned attention/gating tends to degrade more gracefully (soft associations), especially if trained with pose noise.

### 7.7 Route (2): make fusion tokens genuinely 3D, then use 3D PE / 3D relative geometry

If you want 3D PE to be "intrinsic", you need 3D tokens:

- voxel tokens (possibly sparse and multi-scale)
- point tokens (point transformer style)
- object-centric tokens (queries) attending to 3D tokens

Position injection options:

- 3D relative bias (distance/orientation kernels) is often the most stable baseline.
- 3D RoPE / VRoPE can enforce a form of translation-related structure along axes, but:
  - it is not generally SO(3)-equivariant (rotations in 3D do not preserve axis-wise phases).
  - it is sensitive to coordinate scaling and pose noise.

Compute/engineering reality:

- full global attention over 3D tokens is expensive (O(N^2)).
- practical systems need sparse attention, kNN attention, windowing, or hierarchical pooling.

### 7.8 Practical guidance if you want to test these routes

Coordinate normalization (critical for Fourier/RoPE-like PE):

- define a consistent shared frame (usually ego frame) and normalize xyz into a fixed range (e.g., [0,1] or [-1,1]) before computing frequencies/phases.
- tie max frequency to spatial resolution to avoid aliasing (do not use very high frequencies if your BEV grid is coarse or poses are noisy).

Extrinsics robustness (critical for coop):

- if you introduce geometry-conditioned attention, you should evaluate under pose noise and ideally train with noise injection.
- "soft" geometry terms (bias/gating) typically behave better than "hard" warp under the same noise.

Ablation design (minimal but informative):

- Baseline: 2D BEV PE + current fusion.
- Route (1A): 2D BEV PE + 3D reference-point cross-agent sampling (no 2D affine warp).
- Route (1B): 2D BEV PE + geometry bias/gating in fusion attention.
- Route (2): sparse 3D tokens + relative 3D bias (before trying 3D RoPE).

### 7.9 What symmetry do you actually want? (SE(2) vs SE(3))

In cooperative perception, the "right" positional inductive bias depends on the geometry group your pipeline tries to respect:

- Many BEV pipelines implicitly target SE(2) (x,y translation + yaw rotation) in the ground plane.
  - This matches road scenes well and is compatible with BEV tokens.
  - It also explains why many repos reduce extrinsics to (x,y,yaw) for warping: they are enforcing an SE(2) worldview.
- True SE(3) (full 3D rotation + translation) matters if:
  - you want height-aware fusion (ramps, overpasses, strong pitch/roll, multi-level scenes), or
  - you want camera geometry to be handled via full projection constraints, or
  - you fuse modalities where z plays a critical discriminative role.

If your internal representation is 2D BEV, you can still use full SE(3) *in the sampling step* (Route 1), but you cannot fully represent SE(3) interactions *within* the BEV token space unless you add a height dimension (Route 2 or a hybrid).

### 7.10 Why RoPE/VRoPE can be both attractive and fragile

RoPE intuition (1D):

- RoPE rotates Q/K in 2D subspaces with an angle proportional to position p:
  - R(p) = blockdiag(rot(w_1 p), rot(w_2 p), ...)
- The dot product q_i^T k_j after rotation includes terms like cos(w (p_i - p_j)) and sin(w (p_i - p_j)),
  - so the similarity depends on relative offsets, which is a strong inductive bias for sequence/space.

Multi-D RoPE / VRoPE intuition:

- Extending to (x,y,z) usually means applying independent phase rotations per axis (or per grouped axis).
- This gives you "axis-aligned translation structure" (dependence on dx,dy,dz), but it is not generally SO(3)-equivariant:
  - rotating the coordinate system mixes axes, while axis-wise phases do not commute with arbitrary rotations.

Why it can be fragile under pose noise:

- For a high-frequency component w, a small coordinate error delta produces a phase error ~ w * delta.
- Similarity terms like cos(w * (d + delta)) change rapidly when w is large.
- Therefore, high-frequency RoPE/Fourier features can amplify small extrinsics/localization errors unless:
  - you normalize coordinates very carefully,
  - you limit max frequency to what your spatial resolution/noise supports, and
  - you train with pose noise so the model learns to be robust.

### 7.11 A practical "middle ground": 2.5D (height-sliced) BEV tokens

If you want 3D positional structure but cannot afford full 3D tokenization, you can make BEV tokens partially 3D:

- Replace a single BEV feature map (H x W) with a small stack of height slices (H x W x Zb), where Zb is small (e.g., 4 or 8).
- Tokens now have a meaningful z_bin, so a 3D PE (or 3D relative bias) becomes well-defined.

Trade-offs:

- Compute/memory grows roughly linearly in Zb (token count multiplies by Zb).
- The representation becomes closer to SE(3)-capable than plain BEV, while still being much cheaper than point-level tokens.

Connection to BEVFormer:

- BEVFormer already samples multiple z values per BEV cell as reference points (for sampling), but these are not tokens.
- Turning "sampled heights" into explicit tokens is one way to make 3D PE truly meaningful in a BEV-style architecture.

### 7.12 How PRoPE/VRoPE would realistically be integrated (conceptually)

PRoPE:

- Best matched location: attention layers where tokens are image patches across multiple cameras/views.
- The bias comes from relative projective transforms derived from (viewmats, intrinsics) and patch geometry.
- It is not a direct replacement for BEV grid PE; it replaces/augments the attention dot-product for camera tokens.
- See `external/prope/README.md` for the intended usage pattern.

VRoPE:

- Best matched location: attention layers where each token has an explicit coordinate in a shared frame:
  - 3D voxel/point tokens (Route 2), or
  - object queries anchored by 3D reference points (if you can also define key-token coordinates consistently).
- For BEV grid tokens, VRoPE is effectively a 2D RoPE unless you add a meaningful z dimension (Route 2.5D).
- See `external/VRoPE/vrope.py` for an N-D RoPE implementation, but note that you still need a correct "token order -> coordinate" mapping.

### 7.13 What to measure when changing PE (beyond AP)

To understand whether a positional change is "better" or just "different", you usually need at least:

- Clean performance: AP@0.5 / AP@0.7 (or your benchmark's standard).
- Pose noise curves: AP vs localization noise (m) and heading noise (deg).
- Sensitivity to BEV resolution: does performance degrade sharply when you change voxel size / downsample rate?
- Communication dependence (for query-based comm): AP vs bandwidth / number of shared queries.

---

## 8) Can Cooperative Perception Work Without Extrinsics as Input?

First clarify what "no extrinsics input" means, because there are two different things:

1) No inter-agent relative pose at inference (no T_ego<-agent provided).
2) No sensor calibration inside each agent (camera->lidar, intrinsics, etc.).

This note focuses on (1). Most cooperative perception systems still assume (2) is known.

### 8.1 Fundamental constraint: you still need a shared frame (explicitly or implicitly)

If the final output is a set of 3D boxes in the ego/world frame, then information from another agent must be mapped into that frame.

If you do not *input* the inter-agent pose, you must still obtain it somehow:

- Estimate it from data (learned or optimization-based), or
- Avoid explicit alignment and accept that fusion becomes "non-geometric" (usually much worse for 3D detection), or
- Change the task/output so that a shared frame is not required (rare for 3D detection benchmarks).

So the realistic goal is not "extrinsics-free", but "extrinsics-implicit":

- Do not rely on external pose input.
- Predict a pose (or a distribution over poses) inside the model and use it for fusion.

### 8.2 Why "geometry injection" alone does not remove the need for pose

Route (1) (3D reference-point sampling / geometry-conditioned attention) *uses* extrinsics:

- to project 3D reference points into another agent's feature space, or
- to transform coordinates into a shared frame before comparing/aggregating.

Therefore, "better geometry injection" usually increases reliance on correct geometry unless you also add:

- pose estimation, or
- pose-noise training + soft alignment mechanisms.

### 8.3 What can work in practice: three patterns for pose-implicit coop

Pattern A: Learn a pose estimator, then do geometry-aware fusion

- Stage 1: f_pose(ego_feat, agent_feat) -> (dx, dy, dyaw) or a distribution.
- Stage 2: use predicted pose to do:
  - BEV warping, or
  - 3D reference-point sampling, or
  - geometry-conditioned attention bias/gating.

This is the cleanest way to "remove extrinsics input" while keeping a geometric fusion.

Pattern B: Soft alignment by marginalizing over candidate transforms

Instead of predicting one pose, predict weights over a small discrete set:

- T in {T_1, ..., T_K} (SE(2) grid is typical for OPV2V: translations + yaw).
- w_k = softmax(sim(ego_feat, warp(agent_feat, T_k))).
- fused = sum_k w_k * warp(agent_feat, T_k).

This behaves like an internal "pose distribution" and can be more robust under ambiguity.

Pattern C: Object-level alignment (queries/boxes as landmarks)

- Each agent runs a local detector in its own frame.
- Exchange a compact object set (centers + class logits + features).
- Solve for relative pose by matching objects (Hungarian / nearest neighbors) and fitting an SE(2) transform (RANSAC / Procrustes / ICP-like).
- Use the estimated pose for final fusion, or directly fuse object sets.

This reduces bandwidth and can be more stable when BEV textures are weak, but it fails if few common objects exist.

### 8.4 Why pose-implicit fusion is hard (and how to avoid degenerate solutions)

Main difficulties:

- Identifiability: if overlap is small or the scene is symmetric, pose is ambiguous.
- Shortcut learning: the easiest way for the network to reduce loss is to ignore other agents (w_k -> 0).
- Search complexity: the pose space (especially SE(3)) is large; a brute-force search is expensive.

Common tricks to prevent "ignore the neighbor":

- Randomly drop ego features during training (force reliance on neighbors).
- Add an auxiliary loss on predicted pose if GT relative pose exists (or self-supervision via cycle consistency).
- Constrain the pose search space (SE(2) is often enough for ground vehicles).
- Use coarse-to-fine alignment: estimate on low-res BEV, refine on higher-res or on queries.

### 8.5 What "no extrinsics input" is most plausible for

- LiDAR BEV cooperative detection (OPV2V-like): most plausible, because pose can be approximated in SE(2) and BEV correlation is natural.
- Camera-only cooperative BEV (V2X-Sim-like): harder; you typically need camera poses to define 3D rays/BEV lifting. PRoPE still assumes camera matrices.
- Full SE(3) robustness: hardest; you likely need IMU/GNSS priors or explicit registration modules.

### 8.6 Suggested experiment order (so we learn something quickly)

1) Implement Route (1A) or (1B) with correct extrinsics to verify the "geometry injection" path works.
2) Freeze that fusion and replace pose input with:
   - Pattern A (pose regressor), or
   - Pattern B (soft alignment over SE(2) grid).
3) Evaluate:
   - clean AP
   - AP vs pose noise
   - failure cases under small overlap / symmetric scenes

If performance collapses, the likely cause is not that "geometry injection is wrong", but that pose inference is ill-posed without additional priors or training constraints.
