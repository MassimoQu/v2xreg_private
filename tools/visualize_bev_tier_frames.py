#!/usr/bin/env python3
"""Visualize DAIR BEV point clouds + boxes grouped by Reg++ performance tiers.

This uses the full6617 run outputs (matches.jsonl) to pick representative
frames per tier and renders BEV plots from DAIR point clouds and world boxes.
"""
import argparse
import json
import math
import random
import struct
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image


def _load_records(run_dir: Path) -> List[Dict]:
    lines = (run_dir / "matches.jsonl").read_text().strip().split("\n")
    return [json.loads(l) for l in lines if l.strip()]


def _load_data_info(data_root: Path) -> List[Dict]:
    return json.loads((data_root / "cooperative" / "data_info.json").read_text())


def _tier(rec: Dict) -> str:
    te, re = rec.get("TE"), rec.get("RE")
    if te is None or re is None or te == float("inf") or re == float("inf"):
        return "T0_FAIL"
    if te < 0.5 and re < 1.0:
        return "T1_EXCELLENT"
    if te < 2.0 and re < 2.0:
        return "T2_GOOD"
    if te < 5.0 and re < 5.0:
        return "T3_MODERATE"
    return "T4_POOR"


def _pick_representative(records: List[Dict], tier_name: str, n: int) -> List[int]:
    indices = [i for i, r in enumerate(records) if _tier(r) == tier_name]
    if not indices:
        return []
    if tier_name == "T1_EXCELLENT":
        indices.sort(key=lambda i: records[i].get("TE", float("inf")))
    elif tier_name == "T4_POOR":
        indices.sort(key=lambda i: -records[i].get("TE", -1e9) if records[i].get("TE") != float("inf") else -1e9)
    elif tier_name == "T0_FAIL":
        random.seed(42)
        random.shuffle(indices)
    else:
        indices.sort(key=lambda i: records[i].get("TE", float("inf")))
    step = max(1, len(indices) // n)
    return indices[::step][:n]


def _lzf_decompress(data: bytes, expected_len: int) -> bytes:
    out = bytearray()
    i = 0
    while i < len(data):
        ctrl = data[i]
        i += 1
        if ctrl < 32:
            length = ctrl + 1
            out.extend(data[i:i + length])
            i += length
        else:
            length = ctrl >> 5
            ref_offset = (ctrl & 0x1F) << 8
            if length == 7:
                length += data[i]
                i += 1
            ref_offset += data[i]
            i += 1
            ref = len(out) - (ref_offset + 1)
            length += 2
            for j in range(length):
                out.append(out[ref + j])
    if expected_len is not None and len(out) != expected_len:
        raise ValueError(f"LZF size mismatch: got {len(out)} expected {expected_len}")
    return bytes(out)


def _parse_pcd_header(fp) -> Dict:
    header = {}
    while True:
        line = fp.readline()
        if not line:
            raise ValueError("Unexpected EOF while reading PCD header")
        try:
            line = line.decode("ascii").strip()
        except Exception:
            line = line.decode("ascii", errors="ignore").strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        key = parts[0].upper()
        vals = parts[1:]
        if key == "FIELDS":
            header["fields"] = vals
        elif key == "SIZE":
            header["size"] = list(map(int, vals))
        elif key == "TYPE":
            header["type"] = vals
        elif key == "COUNT":
            header["count"] = list(map(int, vals))
        elif key == "WIDTH":
            header["width"] = int(vals[0])
        elif key == "HEIGHT":
            header["height"] = int(vals[0])
        elif key == "POINTS":
            header["points"] = int(vals[0])
        elif key == "DATA":
            header["data"] = vals[0].lower()
            break
    return header


def _dtype_from_type(t: str, size: int) -> np.dtype:
    if t == "F":
        return np.dtype("<f4") if size == 4 else np.dtype("<f8")
    if t == "I":
        return np.dtype("<i1") if size == 1 else (np.dtype("<i2") if size == 2 else np.dtype("<i4"))
    if t == "U":
        return np.dtype("<u1") if size == 1 else (np.dtype("<u2") if size == 2 else np.dtype("<u4"))
    raise ValueError(f"Unsupported PCD type {t} size {size}")


def read_pcd_xyz(pcd_path: Path) -> np.ndarray:
    with pcd_path.open("rb") as f:
        header = _parse_pcd_header(f)
        fields = header["fields"]
        sizes = header["size"]
        types = header["type"]
        counts = header.get("count", [1] * len(fields))
        points = header["points"]
        if header["data"] != "binary_compressed":
            raise ValueError(f"Only binary_compressed supported, got {header['data']}")
        comp_size, uncomp_size = struct.unpack("<II", f.read(8))
        comp_data = f.read(comp_size)
        raw = _lzf_decompress(comp_data, uncomp_size)

    field_arrays = {}
    offset = 0
    for name, sz, tp, cnt in zip(fields, sizes, types, counts):
        n = points * cnt
        nbytes = n * sz
        arr = np.frombuffer(raw, dtype=_dtype_from_type(tp, sz), count=n, offset=offset)
        if cnt > 1:
            arr = arr.reshape(points, cnt)
        else:
            arr = arr.reshape(points, 1)
        field_arrays[name] = arr
        offset += nbytes

    if not all(k in field_arrays for k in ("x", "y", "z")):
        raise ValueError(f"Missing xyz fields in {pcd_path}")
    xyz = np.hstack([field_arrays["x"], field_arrays["y"], field_arrays["z"]]).astype(np.float32)
    return xyz


def _load_calib(path: Path) -> Tuple[np.ndarray, np.ndarray]:
    data = json.loads(path.read_text())
    R = np.array(data["rotation"], dtype=np.float32)
    t = np.array(data["translation"], dtype=np.float32).reshape(3)
    return R, t


def _transform_points(points: np.ndarray, R: np.ndarray, t: np.ndarray) -> np.ndarray:
    return points @ R.T + t


def _compute_vehicle_lidar_to_world(root: Path, veh_id: str) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    nov = root / "vehicle-side" / "calib" / "novatel_to_world" / f"{veh_id}.json"
    l2n = root / "vehicle-side" / "calib" / "lidar_to_novatel" / f"{veh_id}.json"
    R_w, t_w = _load_calib(nov)
    data = json.loads(l2n.read_text())
    R_l2n = np.array(data["transform"]["rotation"], dtype=np.float32)
    t_l2n = np.array(data["transform"]["translation"], dtype=np.float32).reshape(3)
    R = R_w @ R_l2n
    t = R_w @ t_l2n + t_w
    return R, t, t_w


def _compute_infra_lidar_to_world(root: Path, infra_id: str) -> Tuple[np.ndarray, np.ndarray]:
    inf = root / "infrastructure-side" / "calib" / "virtuallidar_to_world" / f"{infra_id}.json"
    return _load_calib(inf)


def _compute_lidar_i2v(R_inf: np.ndarray, t_inf: np.ndarray,
                       R_veh: np.ndarray, t_veh: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    # T_i2v = inv(T_vehicle_lidar2world) @ T_infra_lidar2world
    R_i2v = R_veh.T @ R_inf
    t_i2v = R_veh.T @ (t_inf - t_veh)
    return R_i2v, t_i2v


def _convex_hull(points: np.ndarray) -> np.ndarray:
    # Monotonic chain convex hull for 2D points.
    pts = sorted(points.tolist())
    if len(pts) <= 1:
        return np.array(pts)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    return np.array(hull)


def _render_bev(points_infra: np.ndarray, points_veh: np.ndarray,
                boxes_infra: List[np.ndarray], boxes_veh: List[np.ndarray],
                title: str, limit_m: float, max_points: int) -> Image.Image:
    fig, ax = plt.subplots(figsize=(6.5, 6.5), dpi=220)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    if points_infra is not None and len(points_infra) > 0:
        if max_points and len(points_infra) > max_points:
            idx = np.random.choice(len(points_infra), max_points, replace=False)
            points_infra = points_infra[idx]
        ax.scatter(points_infra[:, 0], points_infra[:, 1], s=0.35, c="#b01515", alpha=0.75, linewidths=0)

    if points_veh is not None and len(points_veh) > 0:
        if max_points and len(points_veh) > max_points:
            idx = np.random.choice(len(points_veh), max_points, replace=False)
            points_veh = points_veh[idx]
        ax.scatter(points_veh[:, 0], points_veh[:, 1], s=0.35, c="#1f9d41", alpha=0.75, linewidths=0)

    def _scale_poly(poly: np.ndarray, scale: float) -> np.ndarray:
        center = poly.mean(axis=0, keepdims=True)
        return (poly - center) * scale + center

    for poly in boxes_infra:
        if poly.shape[0] < 3:
            continue
        poly = _scale_poly(poly, 1.02)
        poly = np.vstack([poly, poly[0]])
        ax.plot(poly[:, 0], poly[:, 1], color="#b01515", linewidth=1.2, linestyle="--", alpha=0.9)

    for poly in boxes_veh:
        if poly.shape[0] < 3:
            continue
        poly = _scale_poly(poly, 0.98)
        poly = np.vstack([poly, poly[0]])
        ax.plot(poly[:, 0], poly[:, 1], color="#1f9d41", linewidth=1.2, linestyle="-", alpha=0.95)

    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(-limit_m, limit_m)
    ax.set_ylim(-limit_m, limit_m)
    ax.axis("off")

    fig.canvas.draw()
    w, h = fig.canvas.get_width_height()
    img = np.frombuffer(fig.canvas.tostring_rgb(), dtype=np.uint8).reshape(h, w, 3)
    plt.close(fig)
    return Image.fromarray(img)


def _collect_boxes_lidar(label_path: Path, R: np.ndarray, t: np.ndarray,
                         origin_xy: np.ndarray = None) -> List[np.ndarray]:
    objs = json.loads(label_path.read_text())
    polys: List[np.ndarray] = []
    for obj in objs:
        dims = obj.get("3d_dimensions", {})
        loc = obj.get("3d_location", {})
        try:
            l = float(dims["l"])
            w = float(dims["w"])
            x = float(loc["x"])
            y = float(loc["y"])
            z = float(loc.get("z", 0.0))
            yaw = float(obj.get("rotation", 0.0))
        except Exception:
            continue
        corners = np.array([
            [ l / 2.0,  w / 2.0, 0.0],
            [ l / 2.0, -w / 2.0, 0.0],
            [-l / 2.0, -w / 2.0, 0.0],
            [-l / 2.0,  w / 2.0, 0.0],
        ], dtype=np.float32)
        c, s = math.cos(yaw), math.sin(yaw)
        Rz = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]], dtype=np.float32)
        pts = corners @ Rz.T
        pts[:, 0] += x
        pts[:, 1] += y
        pts[:, 2] += z
        pts_world = pts @ R.T + t
        if origin_xy is not None:
            pts_world[:, 0] -= origin_xy[0]
            pts_world[:, 1] -= origin_xy[1]
        polys.append(pts_world[:, :2])
    return polys


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", default="outputs/full6617_dair_v2xregpp_gt25")
    parser.add_argument("--data-root", default="data/DAIR-V2X/cooperative-vehicle-infrastructure")
    parser.add_argument("--samples-per-tier", type=int, default=6)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--limit-m", type=float, default=80.0, help="Half-range of BEV in meters.")
    parser.add_argument("--max-points", type=int, default=40000, help="Max points per cloud to render.")
    parser.add_argument("--all-frames", action="store_true", help="Render all frames sequentially.")
    parser.add_argument("--start", type=int, default=0, help="Start index in matches.jsonl (inclusive).")
    parser.add_argument("--end", type=int, default=None, help="End index in matches.jsonl (exclusive).")
    parser.add_argument("--stride", type=int, default=1, help="Stride over matches.jsonl indices.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    data_root = Path(args.data_root)
    if args.all_frames:
        out_dir = Path(args.out_dir) if args.out_dir else run_dir / "vis_bev_full"
    else:
        out_dir = Path(args.out_dir) if args.out_dir else run_dir / "vis_bev_tiers"
    out_dir.mkdir(parents=True, exist_ok=True)

    records = _load_records(run_dir)
    data_info = _load_data_info(data_root)
    info_map = {}
    for item in data_info:
        infra_id = Path(item["infrastructure_pointcloud_path"]).stem
        veh_id = Path(item["vehicle_pointcloud_path"]).stem
        info_map[(infra_id, veh_id)] = item

    def _render_one(idx: int, rec: dict, title_prefix: str, out_path: Path) -> bool:
        infra_id = rec.get("infra_id")
        veh_id = rec.get("veh_id")
        info = info_map.get((infra_id, veh_id)) or data_info[idx]
        infra_pcd = data_root / info["infrastructure_pointcloud_path"]
        veh_pcd = data_root / info["vehicle_pointcloud_path"]
        infra_label = data_root / "infrastructure-side" / "label" / "virtuallidar" / f"{infra_id}.json"
        veh_label = data_root / "vehicle-side" / "label" / "lidar" / f"{veh_id}.json"
        if not infra_pcd.exists() or not veh_pcd.exists() or not infra_label.exists() or not veh_label.exists():
            return False

        infra_xyz = read_pcd_xyz(infra_pcd)
        veh_xyz = read_pcd_xyz(veh_pcd)

        R_inf, t_inf = _compute_infra_lidar_to_world(data_root, infra_id)
        R_veh, t_veh, _veh_origin = _compute_vehicle_lidar_to_world(data_root, veh_id)
        R_i2v, t_i2v = _compute_lidar_i2v(R_inf, t_inf, R_veh, t_veh)

        infra_v = _transform_points(infra_xyz, R_i2v, t_i2v)
        veh_v = veh_xyz

        boxes_infra = _collect_boxes_lidar(infra_label, R_i2v, t_i2v)
        boxes_veh = _collect_boxes_lidar(veh_label, np.eye(3, dtype=np.float32), np.zeros(3, dtype=np.float32))

        te = rec.get("TE", float("inf"))
        re = rec.get("RE", float("inf"))
        title = f"{title_prefix} idx={idx} infra={infra_id} veh={veh_id} TE={te:.2f} RE={re:.2f}"
        panel = _render_bev(infra_v, veh_v, boxes_infra, boxes_veh, title, args.limit_m, args.max_points)
        panel.save(out_path, quality=92)
        return True

    if args.all_frames:
        start = max(0, int(args.start))
        end = int(args.end) if args.end is not None else len(records)
        stride = max(1, int(args.stride))
        frame_dir = out_dir / "frames"
        frame_dir.mkdir(parents=True, exist_ok=True)
        manifest = (out_dir / "frames_manifest.jsonl").open("w", encoding="utf-8")
        seq = 0
        for idx in range(start, min(end, len(records)), stride):
            rec = records[idx]
            out_path = frame_dir / f"frame_{seq:06d}.png"
            ok = _render_one(idx, rec, "FULL", out_path)
            if ok:
                manifest.write(json.dumps({"seq": seq, "index": idx, "infra_id": rec.get("infra_id"), "veh_id": rec.get("veh_id")}) + "\\n")
                seq += 1
            if seq % 200 == 0 and seq > 0:
                print(f"[full] rendered {seq} frames...")
        manifest.close()
        print(f"\\nAll BEV frames saved to {frame_dir}/ (total {seq})")
    else:
        for tier_name in ["T1_EXCELLENT", "T2_GOOD", "T3_MODERATE", "T4_POOR", "T0_FAIL"]:
            picked = _pick_representative(records, tier_name, args.samples_per_tier)
            if not picked:
                continue
            tier_dir = out_dir / tier_name.lower()
            tier_dir.mkdir(parents=True, exist_ok=True)

            panels: List[Image.Image] = []
            for idx in picked:
                rec = records[idx]
                panel_path = tier_dir / f"idx_{idx:05d}.png"
                ok = _render_one(idx, rec, tier_name, panel_path)
                if ok:
                    panels.append(Image.open(panel_path))

            if not panels:
                print(f"[{tier_name}] no panels generated")
                continue

            pw, ph = panels[0].size
            canvas = Image.new("RGB", (pw, ph * len(panels) + 2 * (len(panels) - 1)), color=(10, 10, 10))
            for j, p in enumerate(panels):
                canvas.paste(p, (0, j * (ph + 2)))

            out_path = out_dir / f"{tier_name.lower()}.png"
            canvas.save(out_path, quality=92)
            print(f"[{tier_name}] saved {len(panels)} panels -> {out_path}")

        print(f"\\nAll BEV visualizations saved to {out_dir}/")


if __name__ == "__main__":
    main()
