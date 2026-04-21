#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np


DEFAULT_CLASS_DIMS = {
    "car": (3.9, 1.7, 1.5),
    "truck": (10.0, 2.6, 3.0),
    "bus": (12.0, 2.6, 3.2),
    "van": (4.8, 1.9, 1.9),
    "pedestrian": (0.8, 0.6, 1.7),
    "cyclist": (1.8, 0.6, 1.6),
    "motorcyclist": (2.0, 0.6, 1.6),
    "tricylist": (2.5, 1.0, 1.8),
}


def _read_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _load_intrinsics(side_root: Path, frame_id: str) -> np.ndarray:
    data = _read_json(side_root / "calib" / "camera_intrinsic" / f"{frame_id}.json")
    return np.asarray(data.get("cam_K") or data.get("K"), dtype=np.float32).reshape(3, 3)


def _load_lidar2cam(side_root: Path, frame_id: str) -> Tuple[np.ndarray, np.ndarray]:
    for folder in ("virtuallidar_to_camera", "lidar_to_camera"):
        path = side_root / "calib" / folder / f"{frame_id}.json"
        if path.exists():
            data = _read_json(path)
            R = np.asarray(data["rotation"], dtype=np.float32).reshape(3, 3)
            t = np.asarray(data["translation"], dtype=np.float32).reshape(3)
            return R, t
    raise FileNotFoundError(f"Missing lidar-to-camera calibration for {side_root}/{frame_id}")


def _camera_to_lidar(points: np.ndarray, R: np.ndarray, t: np.ndarray) -> np.ndarray:
    R_inv = R.T
    t_inv = -R_inv @ t
    return (R_inv @ points.T).T + t_inv[None, :]


def _box_corners(center: np.ndarray, dims: Tuple[float, float, float]) -> np.ndarray:
    l, w, h = dims
    x, y, z = center.tolist()
    dx, dy, dz = l / 2.0, w / 2.0, h
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


def _infer_depth_from_height(h_pix: float, fy: float, h_real: float) -> Optional[float]:
    if h_pix <= 1e-3:
        return None
    return float(fy * h_real / h_pix)


def _load_labels(side_root: Path, frame_id: str) -> List[Dict]:
    label_path = side_root / "label" / "camera" / f"{frame_id}.json"
    if not label_path.exists():
        return []
    data = _read_json(label_path)
    return data if isinstance(data, list) else []


def _load_image(path: Path):
    try:
        from PIL import Image
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("PIL is required for image loading") from exc
    return Image.open(path).convert("RGB")


def _depth_prepare(device: str, model_type: Optional[str]):
    import torch

    if not model_type:
        return None
    model_key = str(model_type).strip().lower()
    if model_key in {"none", "off", "false", "0"}:
        return None
    if model_key.startswith("zoe"):
        use_k = (
            model_key in {"zoe_k", "zoed_k", "zoe-k", "zoed-k"}
            or model_key.endswith("_k")
            or model_key.endswith("-k")
        )
        model_name = "ZoeD_K" if use_k else "ZoeD_NK"
        zoe = torch.hub.load("isl-org/ZoeDepth", model_name, pretrained=True, trust_repo=True)
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


def _predict_depth(img_np: np.ndarray, backend: Dict, device: str) -> np.ndarray:
    import torch

    if backend["backend"] == "zoe":
        from PIL import Image

        model = backend["model"]
        depth = model.infer_pil(Image.fromarray(img_np))
        return np.asarray(depth, dtype=np.float32)

    model = backend["model"]
    transform = backend["transform"]
    input_batch = transform(img_np).to(device)
    with torch.no_grad():
        pred = model(input_batch)
        pred = torch.nn.functional.interpolate(
            pred.unsqueeze(1),
            size=img_np.shape[:2],
            mode="bicubic",
            align_corners=False,
        ).squeeze(1)
    return pred.squeeze(0).detach().cpu().numpy()


def _depth_at(depth: np.ndarray, u: float, v: float) -> Optional[float]:
    h, w = depth.shape
    x = int(round(u))
    y = int(round(v))
    if x < 0 or x >= w or y < 0 or y >= h:
        return None
    val = float(depth[y, x])
    if not np.isfinite(val) or val <= 1e-6:
        return None
    return val


def build_cache(args) -> None:
    data_root = Path(args.data_root).expanduser().resolve()
    records = _read_json(Path(args.data_info))
    if args.max_samples > 0:
        records = records[: args.max_samples]

    depth_backend = _depth_prepare(args.device, args.depth_model)
    class_dims = {k.lower(): tuple(v) for k, v in DEFAULT_CLASS_DIMS.items()}
    output: Dict[str, Dict] = {}

    for idx, rec in enumerate(records):
        infra_img_rel = rec.get("infrastructure_image_path")
        veh_img_rel = rec.get("vehicle_image_path")
        if not infra_img_rel or not veh_img_rel:
            output[str(idx)] = {
                "cav_id_list": ["infrastructure", "vehicle"],
                "pred_corner3d_np_list": [[], []],
                "pred_score_np_list": [[], []],
            }
            continue
        infra_id = Path(infra_img_rel).stem
        veh_id = Path(veh_img_rel).stem
        infra_root = data_root / "infrastructure-side"
        veh_root = data_root / "vehicle-side"
        K_infra = _load_intrinsics(infra_root, infra_id)
        K_veh = _load_intrinsics(veh_root, veh_id)
        R_infra, t_infra = _load_lidar2cam(infra_root, infra_id)
        R_veh, t_veh = _load_lidar2cam(veh_root, veh_id)

        infra_labels = _load_labels(infra_root, infra_id)
        veh_labels = _load_labels(veh_root, veh_id)

        infra_depth = None
        veh_depth = None
        if depth_backend is not None:
            try:
                infra_img = np.asarray(_load_image(data_root / str(infra_img_rel)))
                veh_img = np.asarray(_load_image(data_root / str(veh_img_rel)))
            except Exception:
                infra_img = veh_img = None
            if infra_img is not None:
                infra_depth = _predict_depth(infra_img, depth_backend, args.device)
            if veh_img is not None:
                veh_depth = _predict_depth(veh_img, depth_backend, args.device)

        def _convert_labels(
            labels: List[Dict],
            K: np.ndarray,
            R: np.ndarray,
            t: np.ndarray,
            depth_map: Optional[np.ndarray],
        ):
            boxes = []
            scores = []
            bboxes_2d = []
            fy = float(K[1, 1])
            fx = float(K[0, 0])
            cx = float(K[0, 2])
            cy = float(K[1, 2])
            scale = None
            if depth_map is not None and labels:
                ratios = []
                for entry in labels:
                    bbox = entry.get("2d_box") or {}
                    xmin = float(bbox.get("xmin", 0))
                    xmax = float(bbox.get("xmax", 0))
                    ymin = float(bbox.get("ymin", 0))
                    ymax = float(bbox.get("ymax", 0))
                    if xmax <= xmin or ymax <= ymin:
                        continue
                    h_pix = ymax - ymin
                    cls = str(entry.get("type", "car")).lower()
                    dims = class_dims.get(cls, class_dims["car"])
                    depth_size = _infer_depth_from_height(h_pix, fy, dims[2])
                    if depth_size is None or depth_size <= 0:
                        continue
                    u = (xmin + xmax) / 2.0
                    v = (ymin + ymax) / 2.0
                    depth_pred = _depth_at(depth_map, u, v)
                    if depth_pred is None:
                        continue
                    ratios.append(depth_size / depth_pred)
                if ratios:
                    scale = float(np.median(ratios))
            for entry in labels:
                bbox = entry.get("2d_box") or {}
                xmin = float(bbox.get("xmin", 0))
                xmax = float(bbox.get("xmax", 0))
                ymin = float(bbox.get("ymin", 0))
                ymax = float(bbox.get("ymax", 0))
                if xmax <= xmin or ymax <= ymin:
                    continue
                h_pix = ymax - ymin
                cls = str(entry.get("type", "car")).lower()
                dims = class_dims.get(cls, class_dims["car"])
                depth = None
                if depth_map is not None:
                    u = (xmin + xmax) / 2.0
                    v = (ymin + ymax) / 2.0
                    depth_pred = _depth_at(depth_map, u, v)
                    if depth_pred is not None and scale is not None:
                        depth = depth_pred * scale
                if depth is None:
                    depth = _infer_depth_from_height(h_pix, fy, dims[2])
                if depth is None or depth <= 0:
                    continue
                u = (xmin + xmax) / 2.0
                v = (ymin + ymax) / 2.0
                x = (u - cx) * depth / fx
                y = (v - cy) * depth / fy
                center_cam = np.array([x, y, depth], dtype=np.float32)
                corners_cam = _box_corners(center_cam, dims)
                corners_lidar = _camera_to_lidar(corners_cam, R, t)
                boxes.append(corners_lidar.tolist())
                scores.append(1.0)
                bboxes_2d.append([xmin, ymin, xmax, ymax])
            return boxes, scores, bboxes_2d

        infra_boxes, infra_scores, infra_bboxes2d = _convert_labels(
            infra_labels, K_infra, R_infra, t_infra, infra_depth
        )
        veh_boxes, veh_scores, veh_bboxes2d = _convert_labels(
            veh_labels, K_veh, R_veh, t_veh, veh_depth
        )

        output[str(idx)] = {
            "cav_id_list": ["infrastructure", "vehicle"],
            "infra_frame_id": infra_id,
            "veh_frame_id": veh_id,
            "pred_corner3d_np_list": [
                [
                    {
                        "corners": box,
                        "score": score,
                        "type": "detected",
                        "bbox2d": bbox2d,
                    }
                    for box, score, bbox2d in zip(infra_boxes, infra_scores, infra_bboxes2d)
                ],
                [
                    {
                        "corners": box,
                        "score": score,
                        "type": "detected",
                        "bbox2d": bbox2d,
                    }
                    for box, score, bbox2d in zip(veh_boxes, veh_scores, veh_bboxes2d)
                ],
            ],
            "pred_score_np_list": [infra_scores, veh_scores],
        }

    out_path = Path(args.output).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False)
    print(f"Wrote cache to {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build 3D box cache from 2D camera labels + size priors.")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--data-info", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-samples", type=int, default=0)
    parser.add_argument("--depth-model", default=None)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    build_cache(args)


if __name__ == "__main__":
    main()
