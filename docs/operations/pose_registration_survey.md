# Pose Registration Survey (Image / LiDAR / Cross-Modal)

**Owner:** qqxluca + Codex  
**Last updated:** 2026-01-26

Goal: catalogue popular registration methods across (image-image), (lidar-lidar), and (image-lidar) pairs, then map them to what we can validate inside HEAL’s pose-solver framework.

---

## 1) Image ↔ Image

**Popular methods (field consensus)**
- Handcrafted + RANSAC: ORB / SIFT + Essential matrix (baseline).
- Learned dense matching: LoFTR (ECCV’21), ASpanFormer (CVPR’22).
- Learned sparse matching: DISK (NeurIPS’20), SuperPoint + LightGlue (CVPR’23).

**GitHub refs (search snippets)**
- zju3dv/LoFTR, cvg/LightGlue, 3DOM-FBK/deep-image-matching.

**What we integrated**
- `opencood/extrinsics/late_fusion/image_matching.py` now supports:
  - `orb`, `sift` (handcrafted)
  - `loftr` (learned dense, via `kornia`)
  - `disk` (learned sparse, via `kornia` + mutual NN)
  - `lightglue` (learned sparse, via `kornia` LightGlueMatcher + DISK)

**Where it plugs in**
- `opencood/extrinsics/pose_correction/stage1_image_match.py`
- `opencood/extrinsics/pose_correction/pose_solver.py` (external solver)

---

## 2) LiDAR ↔ LiDAR

**Popular methods (field consensus)**
- ICP / GICP / NDT (classic).
- Feature-based global registration: FPFH + RANSAC/FGR, TEASER++ (robust).
- Learning-based: DCP / FMR / PointNetLK.

**GitHub refs (search snippets)**
- MIT-SPARK/TEASER-plusplus.

**What we integrated**
- `opencood/extrinsics/late_fusion/lidar_registration.py`:
  - FPFH + RANSAC/FGR coarse
  - ICP refine (point-to-plane / point-to-point / GICP)
- `opencood/extrinsics/pose_correction/stage1_lidar_registration.py`

**Where it plugs in**
- `opencood/extrinsics/pose_correction/pose_solver.py`
- `opencood/tools/inference_w_noise.py` via `--pose-correction lidar_reg_*`

---

## 3) Image ↔ LiDAR (Cross-Modal)

**Popular methods (field consensus)**
- PnP w/ 2D–3D correspondences (needs semantic/2D detections or depth).
- MI / edge-alignment on rendered depth vs image gradients.
- Learning-based cross-modal: CalibNet, CMRNet, DeepI2P, PCL2I.

**GitHub refs (search snippets)**
- epiception/CalibNet, lijx10/DeepI2P.

**Current practical path in this repo**
- Object-level alignment (V2X-Reg++ / FreeAlign / CBM / VIPS) uses 3D boxes
  from any modality, so in multi-modal settings it already acts as a cross-modal
  registration mechanism.

**Next-step candidates**
- Use camera detections + LiDAR points to build 2D–3D correspondences for PnP.
- Add semantic or depth supervision to stabilize cross-modal alignment.

---

## 4) Validation Status (HEAL)

Current validation is driven through `inference_w_noise.py`:
- Image-based (camera-only): `--pose-correction image_match_*` with `matcher=loftr|disk|lightglue`.
- LiDAR-based: `--pose-correction lidar_reg_*` on LiDAR input configs.
- Cross-modal: object-level methods (`v2xregpp_*`, `freealign_*`, `cbm_*`, `vips_*`).

Upcoming work: add a dedicated cross-modal PnP pipeline once 2D–3D correspondences
are available in the stage-1 caches.
