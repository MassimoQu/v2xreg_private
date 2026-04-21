#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np


def _read_json(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _load_image(path: Path):
    try:
        from PIL import Image
    except Exception as exc:  # pragma: no cover - optional dep
        raise RuntimeError("PIL is required for image loading") from exc
    return Image.open(path).convert("RGB")


def _load_intrinsics(side_root: Path, frame_id: str) -> np.ndarray:
    calib_path = side_root / "calib" / "camera_intrinsic" / f"{frame_id}.json"
    data = _read_json(calib_path)
    K = np.asarray(data.get("cam_K") or data.get("K"), dtype=np.float32).reshape(3, 3)
    return K


def _load_lidar2cam(side_root: Path, frame_id: str) -> Tuple[np.ndarray, np.ndarray]:
    calib_path = None
    for folder in ("virtuallidar_to_camera", "lidar_to_camera"):
        candidate = side_root / "calib" / folder / f"{frame_id}.json"
        if candidate.exists():
            calib_path = candidate
            break
    if calib_path is None:
        raise FileNotFoundError(f"Missing lidar-to-camera calibration for {side_root}/{frame_id}")
    data = _read_json(calib_path)
    R = np.asarray(data["rotation"], dtype=np.float32).reshape(3, 3)
    t = np.asarray(data["translation"], dtype=np.float32).reshape(3)
    return R, t


def _make_box_corners(center: np.ndarray, dims: np.ndarray) -> np.ndarray:
    l, w, h = dims.tolist()
    x, y, z = center.tolist()
    dx = l / 2.0
    dy = w / 2.0
    dz = h
    # z points forward in camera; box is axis-aligned in camera frame.
    corners = np.array(
        [
            [x + dx, y + dy, z - dz],
            [x + dx, y - dy, z - dz],
            [x - dx, y - dy, z - dz],
            [x - dx, y + dy, z - dz],
            [x + dx, y + dy, z],
            [x + dx, y - dy, z],
            [x - dx, y - dy, z],
            [x - dx, y + dy, z],
        ],
        dtype=np.float32,
    )
    return corners


def _project_lidar_to_image(
    points: np.ndarray, K: np.ndarray, R: np.ndarray, t: np.ndarray, img_w: int, img_h: int
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    pts = np.asarray(points, dtype=np.float32)
    if pts.ndim != 2 or pts.shape[1] < 3:
        return np.zeros((0,), dtype=np.float32), np.zeros((0,), dtype=np.float32), np.zeros((0,), dtype=np.float32)
    xyz = pts[:, :3]
    cam = (R @ xyz.T).T + t[None, :]
    z = cam[:, 2]
    valid = z > 1e-3
    cam = cam[valid]
    z = z[valid]
    if cam.size == 0:
        return np.zeros((0,), dtype=np.float32), np.zeros((0,), dtype=np.float32), np.zeros((0,), dtype=np.float32)
    u = (K[0, 0] * cam[:, 0] / z) + K[0, 2]
    v = (K[1, 1] * cam[:, 1] / z) + K[1, 2]
    in_view = (u >= 0) & (u < img_w) & (v >= 0) & (v < img_h)
    return u[in_view], v[in_view], z[in_view]


def _build_lidar_kdtree(u: np.ndarray, v: np.ndarray, z: np.ndarray):
    try:
        from scipy.spatial import cKDTree
    except Exception:
        return None, None
    if u.size == 0:
        return None, None
    pts = np.stack([u, v], axis=1)
    return cKDTree(pts), z


def _load_pcd_points(path: Path, max_points: int) -> np.ndarray:
    try:
        import open3d as o3d
    except Exception as exc:  # pragma: no cover - optional dep
        raise RuntimeError("open3d is required for depth calibration") from exc
    pcd = o3d.io.read_point_cloud(str(path))
    pts = np.asarray(pcd.points, dtype=np.float32)
    if max_points > 0 and pts.shape[0] > max_points:
        rng = np.random.default_rng(0)
        choice = rng.choice(pts.shape[0], size=max_points, replace=False)
        pts = pts[choice]
    return pts


def _resize_image_np(img_np: np.ndarray, target: int) -> Tuple[np.ndarray, float]:
    h, w = img_np.shape[:2]
    scale = 1.0
    if target > 0 and max(h, w) > target:
        scale = float(target) / float(max(h, w))
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        try:
            from PIL import Image
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("PIL is required for resizing") from exc
        img_np = np.asarray(Image.fromarray(img_np).resize((new_w, new_h)))
    return img_np, scale


def _depth_prepare(device: str, model_type: str):
    import torch

    model_key = str(model_type).strip().lower()
    if model_key.startswith("lidar"):
        return {"backend": "lidar"}
    if model_key.startswith("zoe"):
        use_k = (
            model_key in {"zoe_k", "zoed_k", "zoe-k", "zoed-k"}
            or model_key.endswith("_k")
            or model_key.endswith("-k")
        )
        model_name = "ZoeD_K" if use_k else "ZoeD_NK"
        zoe = torch.hub.load(
            "isl-org/ZoeDepth", model_name, pretrained=True, trust_repo=True
        )
        zoe.eval()
        zoe.to(device)
        return {"backend": "zoe", "model": zoe}

    midas = torch.hub.load("intel-isl/MiDaS", model_type)
    midas.eval()
    midas.to(device)
    transforms = torch.hub.load("intel-isl/MiDaS", "transforms")
    if model_key.startswith("dpt"):
        transform = transforms.dpt_transform
    else:
        transform = transforms.small_transform
    return {"backend": "midas", "model": midas, "transform": transform}


def _predict_depth(img: np.ndarray, backend: Dict, device: str) -> np.ndarray:
    import torch

    if backend["backend"] == "lidar":
        raise RuntimeError("Lidar backend does not support image-only depth prediction")
    if backend["backend"] == "zoe":
        from PIL import Image

        model = backend["model"]
        depth = model.infer_pil(Image.fromarray(img))
        depth = np.asarray(depth, dtype=np.float32)
        return depth

    model = backend["model"]
    transform = backend["transform"]
    input_batch = transform(img).to(device)
    with torch.no_grad():
        pred = model(input_batch)
        pred = torch.nn.functional.interpolate(
            pred.unsqueeze(1),
            size=img.shape[:2],
            mode="bicubic",
            align_corners=False,
        ).squeeze(1)
    return pred.squeeze(0).detach().cpu().numpy()


def _estimate_scale(
    records: List[Dict],
    data_root: Path,
    side: str,
    depth_backend: Dict,
    device: str,
    sample_limit: int,
    pcd_points: int,
) -> Tuple[str, float]:
    ratios_linear: List[float] = []
    ratios_inv: List[float] = []
    errs_linear: List[float] = []
    errs_inv: List[float] = []
    side_root = data_root / f"{side}-side"
    if depth_backend.get("backend") == "lidar":
        return "lidar", 1.0
    for rec in records[:sample_limit]:
        img_rel = rec.get(f"{side}_image_path")
        pcd_rel = rec.get(f"{side}_pointcloud_path")
        if not img_rel or not pcd_rel:
            continue
        img_path = data_root / str(img_rel)
        pcd_path = data_root / str(pcd_rel)
        if not img_path.exists() or not pcd_path.exists():
            continue
        frame_id = Path(img_rel).stem
        K = _load_intrinsics(side_root, frame_id)
        R, t = _load_lidar2cam(side_root, frame_id)
        img = np.asarray(_load_image(img_path))
        depth_rel = _predict_depth(img, depth_backend, device)
        pts = _load_pcd_points(pcd_path, max_points=pcd_points)
        u, v, z = _project_lidar_to_image(pts, K, R, t, img.shape[1], img.shape[0])
        if u.size == 0:
            continue
        u_i = np.clip(np.round(u).astype(np.int32), 0, img.shape[1] - 1)
        v_i = np.clip(np.round(v).astype(np.int32), 0, img.shape[0] - 1)
        pred = depth_rel[v_i, u_i]
        mask = np.isfinite(pred) & (pred > 1e-6) & np.isfinite(z) & (z > 1e-3)
        if not np.any(mask):
            continue
        pred = pred[mask]
        z = z[mask]
        scale_lin = float(np.median(z / pred))
        scale_inv = float(np.median(z * pred))
        ratios_linear.append(scale_lin)
        ratios_inv.append(scale_inv)
        errs_linear.append(float(np.median(np.abs(pred * scale_lin - z))))
        errs_inv.append(float(np.median(np.abs(scale_inv / np.maximum(pred, 1e-6) - z))))
    if not ratios_linear or not ratios_inv:
        return "linear", 1.0
    ratio_linear = float(np.median(ratios_linear))
    ratio_inv = float(np.median(ratios_inv))
    err_linear = float(np.median(errs_linear)) if errs_linear else float("inf")
    err_inv = float(np.median(errs_inv)) if errs_inv else float("inf")
    if err_inv < err_linear:
        return "inverse", ratio_inv
    return "linear", ratio_linear


def _build_loftr(device: str):
    import torch
    from kornia.feature import LoFTR

    loftr = LoFTR(pretrained="outdoor").eval().to(device)
    return loftr


def _build_sift(args):
    try:
        import cv2
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("opencv-python is required for SIFT matching") from exc
    return cv2.SIFT_create(
        nfeatures=int(args.sift_max_kpts),
        contrastThreshold=float(args.sift_contrast_threshold),
        edgeThreshold=float(args.sift_edge_threshold),
        sigma=float(args.sift_sigma),
    )


def _run_sift(sift, img0: np.ndarray, img1: np.ndarray, ratio: float):
    import cv2

    gray0 = cv2.cvtColor(img0, cv2.COLOR_RGB2GRAY)
    gray1 = cv2.cvtColor(img1, cv2.COLOR_RGB2GRAY)
    kp0, des0 = sift.detectAndCompute(gray0, None)
    kp1, des1 = sift.detectAndCompute(gray1, None)
    if des0 is None or des1 is None or len(kp0) == 0 or len(kp1) == 0:
        return np.zeros((0, 2), dtype=np.float32), np.zeros((0, 2), dtype=np.float32), np.zeros((0,), dtype=np.float32)
    bf = cv2.BFMatcher(cv2.NORM_L2)
    raw_matches = bf.knnMatch(des0, des1, k=2)
    good = []
    conf = []
    for m_n in raw_matches:
        if len(m_n) < 2:
            continue
        m, n = m_n
        if m.distance < ratio * n.distance:
            good.append((m.queryIdx, m.trainIdx, m.distance))
            conf.append(1.0 / (float(m.distance) + 1e-6))
    if not good:
        return np.zeros((0, 2), dtype=np.float32), np.zeros((0, 2), dtype=np.float32), np.zeros((0,), dtype=np.float32)
    kpts0 = np.array([kp0[i].pt for i, _, _ in good], dtype=np.float32)
    kpts1 = np.array([kp1[j].pt for _, j, _ in good], dtype=np.float32)
    conf = np.array(conf, dtype=np.float32)
    return kpts0, kpts1, conf


def _lidar_depth_map(
    points: np.ndarray,
    K: np.ndarray,
    R: np.ndarray,
    t: np.ndarray,
    img_w: int,
    img_h: int,
) -> np.ndarray:
    depth = np.zeros((img_h, img_w), dtype=np.float32)
    pts = np.asarray(points, dtype=np.float32)
    if pts.ndim != 2 or pts.shape[1] < 3:
        return depth
    cam = (R @ pts[:, :3].T).T + t[None, :]
    z = cam[:, 2]
    valid = z > 1e-3
    cam = cam[valid]
    z = z[valid]
    if cam.size == 0:
        return depth
    u = (K[0, 0] * cam[:, 0] / z) + K[0, 2]
    v = (K[1, 1] * cam[:, 1] / z) + K[1, 2]
    u_i = np.round(u).astype(np.int32)
    v_i = np.round(v).astype(np.int32)
    mask = (u_i >= 0) & (u_i < img_w) & (v_i >= 0) & (v_i < img_h)
    u_i = u_i[mask]
    v_i = v_i[mask]
    z = z[mask]
    for px, py, zz in zip(u_i.tolist(), v_i.tolist(), z.tolist()):
        cur = depth[py, px]
        if cur <= 1e-6 or zz < cur:
            depth[py, px] = zz
    return depth


def _run_loftr(loftr, img0: np.ndarray, img1: np.ndarray, max_size: int, device: str):
    import torch

    img0_resized, scale0 = _resize_image_np(img0, max_size)
    img1_resized, scale1 = _resize_image_np(img1, max_size)
    gray0 = img0_resized.mean(axis=2, keepdims=True) / 255.0
    gray1 = img1_resized.mean(axis=2, keepdims=True) / 255.0
    t0 = torch.from_numpy(gray0.transpose(2, 0, 1)).unsqueeze(0).float().to(device)
    t1 = torch.from_numpy(gray1.transpose(2, 0, 1)).unsqueeze(0).float().to(device)
    with torch.no_grad():
        out = loftr({"image0": t0, "image1": t1})
    kpts0 = out["keypoints0"].detach().cpu().numpy()
    kpts1 = out["keypoints1"].detach().cpu().numpy()
    conf = out["confidence"].detach().cpu().numpy()
    # Map back to original resolution.
    if scale0 != 1.0:
        kpts0 = kpts0 / scale0
    if scale1 != 1.0:
        kpts1 = kpts1 / scale1
    return kpts0, kpts1, conf


def _normalize_kpts(kpts: np.ndarray, K: np.ndarray) -> np.ndarray:
    fx = float(K[0, 0])
    fy = float(K[1, 1])
    cx = float(K[0, 2])
    cy = float(K[1, 2])
    x = (kpts[:, 0] - cx) / max(fx, 1e-6)
    y = (kpts[:, 1] - cy) / max(fy, 1e-6)
    return np.stack([x, y], axis=1)


def _ransac_filter(
    kpts0: np.ndarray,
    kpts1: np.ndarray,
    conf: np.ndarray,
    threshold: float,
    confidence: float,
    max_iters: int,
    *,
    mode: str = "fundamental",
    K0: Optional[np.ndarray] = None,
    K1: Optional[np.ndarray] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    if kpts0.size == 0 or kpts1.size == 0:
        return kpts0, kpts1, conf
    if kpts0.shape[0] < 8 or kpts1.shape[0] < 8:
        return kpts0, kpts1, conf
    try:
        import cv2
    except Exception as exc:  # pragma: no cover - optional dep
        raise RuntimeError("opencv-python is required for RANSAC filtering") from exc
    if mode == "essential":
        if K0 is None or K1 is None:
            return kpts0, kpts1, conf
        pts0 = _normalize_kpts(kpts0, K0)
        pts1 = _normalize_kpts(kpts1, K1)
        eye = np.eye(3, dtype=np.float64)
        F, mask = cv2.findEssentialMat(
            pts0,
            pts1,
            eye,
            cv2.RANSAC,
            float(confidence),
            float(threshold),
        )
    else:
        F, mask = cv2.findFundamentalMat(
            kpts0,
            kpts1,
            cv2.FM_RANSAC,
            float(threshold),
            float(confidence),
            int(max_iters),
        )
    if mask is None:
        return kpts0, kpts1, conf
    mask = mask.reshape(-1).astype(bool)
    if not np.any(mask):
        return kpts0, kpts1, conf
    return kpts0[mask], kpts1[mask], conf[mask]


def _depth_value(depth_map: np.ndarray, u: float, v: float) -> Optional[float]:
    h, w = depth_map.shape
    x = int(round(u))
    y = int(round(v))
    if x < 0 or x >= w or y < 0 or y >= h:
        return None
    val = float(depth_map[y, x])
    if not math.isfinite(val) or val <= 1e-6:
        return None
    return val


def _query_lidar_depth(kd_bundle, u: float, v: float, radius: float) -> Optional[float]:
    if kd_bundle is None:
        return None
    tree, z = kd_bundle
    if tree is None or z is None or z.size == 0:
        return None
    try:
        idxs = tree.query_ball_point([float(u), float(v)], r=float(radius))
    except Exception:
        idxs = []
    if not idxs:
        return None
    depths = z[idxs]
    depths = depths[np.isfinite(depths)]
    if depths.size == 0:
        return None
    return float(np.min(depths))


def _camera_xyz(u: float, v: float, z: float, K: np.ndarray) -> np.ndarray:
    x = (u - float(K[0, 2])) * z / float(K[0, 0])
    y = (v - float(K[1, 2])) * z / float(K[1, 1])
    return np.array([x, y, z], dtype=np.float32)


def _camera_to_lidar(points: np.ndarray, R: np.ndarray, t: np.ndarray) -> np.ndarray:
    R_inv = R.T
    t_inv = -R_inv @ t
    return (R_inv @ points.T).T + t_inv[None, :]


def build_cache(args) -> None:
    data_root = Path(args.data_root).expanduser().resolve()
    data_info = _read_json(Path(args.data_info))
    records = list(data_info)
    if args.max_samples > 0:
        records = records[: args.max_samples]

    device = args.device
    depth_backend = _depth_prepare(device, args.depth_model)
    scale_mode, infra_scale = _estimate_scale(
        records,
        data_root,
        "infrastructure",
        depth_backend,
        device,
        sample_limit=args.depth_calib_samples,
        pcd_points=args.depth_calib_points,
    )
    _, veh_scale = _estimate_scale(
        records,
        data_root,
        "vehicle",
        depth_backend,
        device,
        sample_limit=args.depth_calib_samples,
        pcd_points=args.depth_calib_points,
    )

    loftr = _build_loftr(device) if args.matcher == "loftr" else None
    sift = _build_sift(args) if args.matcher == "sift" else None
    rng = np.random.default_rng(args.seed)
    descriptor_mode = str(getattr(args, "descriptor_mode", "random") or "random").lower()
    descriptor_dim = max(1, int(args.descriptor_dim))
    if descriptor_mode not in {"random", "onehot"}:
        raise ValueError(f"descriptor_mode={descriptor_mode} must be random or onehot")
    output: Dict[str, Dict] = {}

    for idx, rec in enumerate(records):
        img_infra_rel = rec.get("infrastructure_image_path")
        img_veh_rel = rec.get("vehicle_image_path")
        if not img_infra_rel or not img_veh_rel:
            output[str(idx)] = {
                "cav_id_list": ["infrastructure", "vehicle"],
                "feature_corner3d_np_list": [[], []],
            }
            continue
        img_infra_path = data_root / str(img_infra_rel)
        img_veh_path = data_root / str(img_veh_rel)
        if not img_infra_path.exists() or not img_veh_path.exists():
            output[str(idx)] = {
                "cav_id_list": ["infrastructure", "vehicle"],
                "feature_corner3d_np_list": [[], []],
            }
            continue

        infra_id = Path(img_infra_rel).stem
        veh_id = Path(img_veh_rel).stem
        infra_root = data_root / "infrastructure-side"
        veh_root = data_root / "vehicle-side"
        K_infra = _load_intrinsics(infra_root, infra_id)
        K_veh = _load_intrinsics(veh_root, veh_id)
        R_infra, t_infra = _load_lidar2cam(infra_root, infra_id)
        R_veh, t_veh = _load_lidar2cam(veh_root, veh_id)

        infra_img = np.asarray(_load_image(img_infra_path))
        veh_img = np.asarray(_load_image(img_veh_path))

        lidar_kd_infra = None
        lidar_kd_veh = None
        if depth_backend.get("backend") == "lidar":
            infra_pcd_rel = rec.get("infrastructure_pointcloud_path")
            veh_pcd_rel = rec.get("vehicle_pointcloud_path")
            infra_pcd = _load_pcd_points(data_root / str(infra_pcd_rel), max_points=args.depth_calib_points)
            veh_pcd = _load_pcd_points(data_root / str(veh_pcd_rel), max_points=args.depth_calib_points)
            u_i, v_i, z_i = _project_lidar_to_image(
                infra_pcd, K_infra, R_infra, t_infra, infra_img.shape[1], infra_img.shape[0]
            )
            u_v, v_v, z_v = _project_lidar_to_image(
                veh_pcd, K_veh, R_veh, t_veh, veh_img.shape[1], veh_img.shape[0]
            )
            lidar_kd_infra = _build_lidar_kdtree(u_i, v_i, z_i)
            lidar_kd_veh = _build_lidar_kdtree(u_v, v_v, z_v)
        else:
            depth_infra = _predict_depth(infra_img, depth_backend, device)
            depth_veh = _predict_depth(veh_img, depth_backend, device)
            if scale_mode == "inverse":
                depth_infra = infra_scale / np.maximum(depth_infra, 1e-6)
                depth_veh = veh_scale / np.maximum(depth_veh, 1e-6)
            else:
                depth_infra = infra_scale * depth_infra
                depth_veh = veh_scale * depth_veh

        if args.matcher == "sift":
            kpts0, kpts1, conf = _run_sift(sift, infra_img, veh_img, args.sift_ratio)
        else:
            kpts0, kpts1, conf = _run_loftr(
                loftr, infra_img, veh_img, args.loftr_max_size, device
            )
        if args.ransac:
            kpts0, kpts1, conf = _ransac_filter(
                kpts0,
                kpts1,
                conf,
                threshold=args.ransac_threshold,
                confidence=args.ransac_confidence,
                max_iters=args.ransac_max_iters,
                mode=args.ransac_mode,
                K0=K_infra,
                K1=K_veh,
            )
        if kpts0.size == 0:
            output[str(idx)] = {
                "cav_id_list": ["infrastructure", "vehicle"],
                "infra_frame_id": infra_id,
                "veh_frame_id": veh_id,
                "feature_corner3d_np_list": [[], []],
            }
            continue

        order = np.argsort(-conf)
        if args.loftr_max_matches > 0:
            order = order[: args.loftr_max_matches]
        infra_feats: List[Dict] = []
        veh_feats: List[Dict] = []
        box_dims = np.array([args.box_dim, args.box_dim, args.box_dim], dtype=np.float32)

        for match_idx in order.tolist():
            u0, v0 = kpts0[match_idx]
            u1, v1 = kpts1[match_idx]
            score = float(conf[match_idx])
            if score < args.loftr_min_conf:
                continue
            if depth_backend.get("backend") == "lidar":
                z0 = _query_lidar_depth(lidar_kd_infra, u0, v0, args.lidar_depth_radius)
                z1 = _query_lidar_depth(lidar_kd_veh, u1, v1, args.lidar_depth_radius)
            else:
                z0 = _depth_value(depth_infra, u0, v0)
                z1 = _depth_value(depth_veh, u1, v1)
            if z0 is None or z1 is None:
                continue
            if not (args.min_depth <= z0 <= args.max_depth):
                continue
            if not (args.min_depth <= z1 <= args.max_depth):
                continue

            if descriptor_mode == "onehot":
                pair_idx = len(infra_feats)
                if pair_idx >= descriptor_dim:
                    continue
                desc = np.zeros((descriptor_dim,), dtype=np.float32)
                desc[pair_idx] = 1.0
            else:
                desc = rng.normal(size=(descriptor_dim,)).astype(np.float32)
                desc /= max(float(np.linalg.norm(desc)), 1e-6)

            center0 = _camera_xyz(u0, v0, z0, K_infra)
            center1 = _camera_xyz(u1, v1, z1, K_veh)
            corners0 = _make_box_corners(center0, box_dims)
            corners1 = _make_box_corners(center1, box_dims)
            corners0_lidar = _camera_to_lidar(corners0, R_infra, t_infra)
            corners1_lidar = _camera_to_lidar(corners1, R_veh, t_veh)

            infra_feats.append(
                {
                    "type": "feature",
                    "score": score,
                    "descriptor": desc.tolist(),
                    "corners": corners0_lidar.tolist(),
                }
            )
            veh_feats.append(
                {
                    "type": "feature",
                    "score": score,
                    "descriptor": desc.tolist(),
                    "corners": corners1_lidar.tolist(),
                }
            )

        output[str(idx)] = {
            "cav_id_list": ["infrastructure", "vehicle"],
            "infra_frame_id": infra_id,
            "veh_frame_id": veh_id,
            "feature_corner3d_np_list": [infra_feats, veh_feats],
        }

    out_path = Path(args.output).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False)
    meta = {
        "matcher": args.matcher,
        "depth_model": args.depth_model,
        "depth_scale_mode": scale_mode,
        "infra_depth_scale": infra_scale,
        "veh_depth_scale": veh_scale,
        "loftr_max_size": args.loftr_max_size,
        "loftr_min_conf": args.loftr_min_conf,
        "loftr_max_matches": args.loftr_max_matches,
        "descriptor_mode": descriptor_mode,
        "descriptor_dim": descriptor_dim,
        "box_dim": args.box_dim,
        "min_depth": args.min_depth,
        "max_depth": args.max_depth,
        "lidar_depth_radius": args.lidar_depth_radius,
    }
    meta_path = out_path.parent / (out_path.stem + "_meta.json")
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"Wrote cache to {out_path}")
    print(f"Wrote meta to {meta_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build image feature cache using LoFTR + monocular depth.")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--data-info", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--max-samples", type=int, default=0)
    parser.add_argument("--matcher", default="loftr", choices=["loftr", "sift"])
    parser.add_argument("--depth-model", default="DPT_Hybrid")
    parser.add_argument("--depth-calib-samples", type=int, default=200)
    parser.add_argument("--depth-calib-points", type=int, default=10000)
    parser.add_argument("--min-depth", type=float, default=3.0)
    parser.add_argument("--max-depth", type=float, default=80.0)
    parser.add_argument("--loftr-max-size", type=int, default=640)
    parser.add_argument("--loftr-min-conf", type=float, default=0.3)
    parser.add_argument("--loftr-max-matches", type=int, default=256)
    parser.add_argument("--sift-max-kpts", type=int, default=2048)
    parser.add_argument("--sift-contrast-threshold", type=float, default=0.04)
    parser.add_argument("--sift-edge-threshold", type=float, default=10.0)
    parser.add_argument("--sift-sigma", type=float, default=1.6)
    parser.add_argument("--sift-ratio", type=float, default=0.75)
    parser.add_argument("--descriptor-dim", type=int, default=64)
    parser.add_argument("--descriptor-mode", default="random", choices=["random", "onehot"])
    parser.add_argument("--ransac", action="store_true")
    parser.add_argument("--ransac-threshold", type=float, default=1.0)
    parser.add_argument("--ransac-confidence", type=float, default=0.999)
    parser.add_argument("--ransac-max-iters", type=int, default=10000)
    parser.add_argument("--ransac-mode", default="fundamental", choices=["fundamental", "essential"])
    parser.add_argument("--box-dim", type=float, default=0.5)
    parser.add_argument("--lidar-depth-radius", type=float, default=3.0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    build_cache(args)


if __name__ == "__main__":
    main()
