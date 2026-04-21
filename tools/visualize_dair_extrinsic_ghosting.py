#!/usr/bin/env python3
"""Render DAIR point-cloud misalignment and mid-fusion ghosting figures.

This script uses one locally available DAIR pair and produces two figures:

1. A BEV point-cloud alignment comparison under GT extrinsics vs. a severe
   extrinsic offset.
2. A BEV "mid-fusion" ghosting visualization. The feature map here is a
   BEV occupancy-style surrogate built from raw point clouds and then fused in
   ego BEV. It is not a learned checkpoint activation, but it shows the same
   warp-then-fuse ghosting failure mode caused by noisy extrinsics.
"""

import argparse
import json
import math
import struct
from pathlib import Path
from typing import Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.lines as mlines
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle
from matplotlib.colors import LinearSegmentedColormap
from mpl_toolkits.axes_grid1.inset_locator import inset_axes, mark_inset
from scipy.ndimage import gaussian_filter, sobel


def _lzf_decompress(data: bytes, expected_len: int) -> bytes:
    out = bytearray()
    idx = 0
    while idx < len(data):
        ctrl = data[idx]
        idx += 1
        if ctrl < 32:
            length = ctrl + 1
            out.extend(data[idx : idx + length])
            idx += length
            continue
        length = ctrl >> 5
        ref_offset = (ctrl & 0x1F) << 8
        if length == 7:
            length += data[idx]
            idx += 1
        ref_offset += data[idx]
        idx += 1
        ref = len(out) - (ref_offset + 1)
        length += 2
        for j in range(length):
            out.append(out[ref + j])
    if len(out) != expected_len:
        raise ValueError(f"LZF size mismatch: got {len(out)} expected {expected_len}")
    return bytes(out)


def _parse_pcd_header(fp) -> dict:
    header = {}
    while True:
        line = fp.readline()
        if not line:
            raise ValueError("Unexpected EOF while reading PCD header")
        text = line.decode("ascii", errors="ignore").strip()
        if not text or text.startswith("#"):
            continue
        parts = text.split()
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
        elif key == "POINTS":
            header["points"] = int(vals[0])
        elif key == "DATA":
            header["data"] = vals[0].lower()
            break
    return header


def _dtype_from_type(tp: str, size: int) -> np.dtype:
    if tp == "F":
        return np.dtype("<f4") if size == 4 else np.dtype("<f8")
    if tp == "I":
        return np.dtype("<i1") if size == 1 else (np.dtype("<i2") if size == 2 else np.dtype("<i4"))
    if tp == "U":
        return np.dtype("<u1") if size == 1 else (np.dtype("<u2") if size == 2 else np.dtype("<u4"))
    raise ValueError(f"Unsupported PCD type {tp} size {size}")


def read_pcd_xyz(pcd_path: Path) -> np.ndarray:
    with pcd_path.open("rb") as f:
        header = _parse_pcd_header(f)
        if header.get("data") != "binary_compressed":
            raise ValueError(f"Only binary_compressed PCD is supported, got {header.get('data')}")
        comp_size, uncomp_size = struct.unpack("<II", f.read(8))
        raw = _lzf_decompress(f.read(comp_size), uncomp_size)

    arrays = {}
    offset = 0
    counts = header.get("count", [1] * len(header["fields"]))
    for name, size, tp, count in zip(header["fields"], header["size"], header["type"], counts):
        n = header["points"] * count
        nbytes = n * size
        arr = np.frombuffer(raw, dtype=_dtype_from_type(tp, size), count=n, offset=offset)
        arr = arr.reshape(header["points"], count)
        arrays[name] = arr
        offset += nbytes

    if not all(key in arrays for key in ("x", "y", "z")):
        raise ValueError(f"Missing xyz fields in {pcd_path}")
    return np.hstack([arrays["x"], arrays["y"], arrays["z"]]).astype(np.float32)


def load_lidar_i2v(calib_path: Path) -> Tuple[np.ndarray, np.ndarray]:
    calib = json.loads(calib_path.read_text())
    rotation = np.array(calib["rotation"], dtype=np.float32)
    translation = np.array(calib["translation"], dtype=np.float32).reshape(3)
    return rotation, translation


def apply_rigid(points: np.ndarray, rotation: np.ndarray, translation: np.ndarray) -> np.ndarray:
    return points @ rotation.T + translation


def build_noise_transform(tx: float, ty: float, yaw_deg: float) -> Tuple[np.ndarray, np.ndarray]:
    yaw = math.radians(yaw_deg)
    cos_yaw = math.cos(yaw)
    sin_yaw = math.sin(yaw)
    rotation = np.array(
        [[cos_yaw, -sin_yaw, 0.0], [sin_yaw, cos_yaw, 0.0], [0.0, 0.0, 1.0]],
        dtype=np.float32,
    )
    translation = np.array([tx, ty, 0.0], dtype=np.float32)
    return rotation, translation


def crop_points(
    points: np.ndarray,
    xlim: Tuple[float, float],
    ylim: Tuple[float, float],
    zlim: Tuple[float, float],
) -> np.ndarray:
    mask = (
        (points[:, 0] >= xlim[0])
        & (points[:, 0] <= xlim[1])
        & (points[:, 1] >= ylim[0])
        & (points[:, 1] <= ylim[1])
        & (points[:, 2] >= zlim[0])
        & (points[:, 2] <= zlim[1])
    )
    return points[mask]


def subsample_points(points: np.ndarray, max_points: int, rng: np.random.Generator) -> np.ndarray:
    if max_points <= 0 or len(points) <= max_points:
        return points
    keep = rng.choice(len(points), size=max_points, replace=False)
    return points[keep]


def normalize_feature(feature: np.ndarray) -> np.ndarray:
    if not np.any(feature > 0):
        return np.zeros_like(feature, dtype=np.float32)
    nonzero = feature[feature > 0]
    denom = float(np.percentile(nonzero, 99.5))
    if denom <= 1e-6:
        denom = float(nonzero.max()) if nonzero.size else 1.0
    normalized = np.clip(feature / denom, 0.0, 1.0)
    return np.power(normalized, 0.72).astype(np.float32)


def make_bev_feature(
    points: np.ndarray,
    xlim: Tuple[float, float],
    ylim: Tuple[float, float],
    zlim: Tuple[float, float],
    resolution: float,
    sigma: float,
) -> np.ndarray:
    cropped = crop_points(points, xlim=xlim, ylim=ylim, zlim=zlim)
    nx = int(math.ceil((xlim[1] - xlim[0]) / resolution))
    ny = int(math.ceil((ylim[1] - ylim[0]) / resolution))
    counts = np.zeros((ny, nx), dtype=np.float32)
    if len(cropped) == 0:
        return counts

    x_idx = ((cropped[:, 0] - xlim[0]) / resolution).astype(np.int32)
    y_idx = ((cropped[:, 1] - ylim[0]) / resolution).astype(np.int32)
    valid = (x_idx >= 0) & (x_idx < nx) & (y_idx >= 0) & (y_idx < ny)
    x_idx = x_idx[valid]
    y_idx = y_idx[valid]
    np.add.at(counts, (y_idx, x_idx), 1.0)

    feature = np.log1p(counts)
    if sigma > 0:
        feature = gaussian_filter(feature, sigma=sigma)
    return normalize_feature(feature)


def make_overlay_rgb(ego_feature: np.ndarray, collab_feature: np.ndarray) -> np.ndarray:
    rgb = np.zeros(ego_feature.shape + (3,), dtype=np.float32)
    rgb[..., 0] = collab_feature
    rgb[..., 1] = ego_feature
    rgb[..., 2] = np.clip(0.32 * np.maximum(ego_feature, collab_feature), 0.0, 1.0)
    return np.clip(rgb, 0.0, 1.0)


def compute_edge_energy(feature: np.ndarray) -> np.ndarray:
    grad_y = sobel(feature, axis=0)
    grad_x = sobel(feature, axis=1)
    edge = np.hypot(grad_x, grad_y)
    return normalize_feature(edge)


def feature_display(feature: np.ndarray, edge_boost: float = 0.55) -> np.ndarray:
    edge = compute_edge_energy(feature)
    return np.clip(0.65 * feature + edge_boost * edge, 0.0, 1.0)


def make_structure_background(feature: np.ndarray) -> np.ndarray:
    return np.clip(0.55 * feature + 0.75 * compute_edge_energy(feature), 0.0, 1.0)


def contour_levels_from_maps(*maps: np.ndarray) -> np.ndarray:
    nonzero = [m[m > 0] for m in maps if np.any(m > 0)]
    if not nonzero:
        return np.array([0.24, 0.42], dtype=np.float32)
    vals = np.concatenate(nonzero)
    levels = np.quantile(vals, [0.9, 0.972])
    levels = np.unique(np.clip(levels, 0.08, 0.95))
    return levels.astype(np.float32)


def metric_box_to_pixel_slices(
    xlim: Tuple[float, float],
    ylim: Tuple[float, float],
    resolution: float,
    box: Tuple[float, float, float, float],
    height: int,
    width: int,
) -> Tuple[slice, slice]:
    x0, x1, y0, y1 = box
    px0 = int(np.clip(math.floor((x0 - xlim[0]) / resolution), 0, width - 1))
    px1 = int(np.clip(math.ceil((x1 - xlim[0]) / resolution), px0 + 1, width))
    py0 = int(np.clip(math.floor((y0 - ylim[0]) / resolution), 0, height - 1))
    py1 = int(np.clip(math.ceil((y1 - ylim[0]) / resolution), py0 + 1, height))
    return slice(py0, py1), slice(px0, px1)


def crop_feature_box(
    feature: np.ndarray,
    xlim: Tuple[float, float],
    ylim: Tuple[float, float],
    resolution: float,
    box: Tuple[float, float, float, float],
) -> np.ndarray:
    y_slice, x_slice = metric_box_to_pixel_slices(
        xlim=xlim,
        ylim=ylim,
        resolution=resolution,
        box=box,
        height=feature.shape[0],
        width=feature.shape[1],
    )
    return feature[y_slice, x_slice]


def _set_bev_axes(ax, xlim: Tuple[float, float], ylim: Tuple[float, float]) -> None:
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_aspect("equal")
    ax.set_xlabel("x in vehicle frame (m)")
    ax.set_ylabel("y in vehicle frame (m)")
    ax.grid(True, linestyle="--", linewidth=0.45, alpha=0.18)
    ax.axhline(0.0, color="#888888", linewidth=0.7, alpha=0.25)
    ax.axvline(0.0, color="#888888", linewidth=0.7, alpha=0.25)


def render_pointcloud_alignment(
    vehicle_points: np.ndarray,
    infra_points_gt: np.ndarray,
    infra_points_noisy: np.ndarray,
    xlim: Tuple[float, float],
    ylim: Tuple[float, float],
    zlim: Tuple[float, float],
    max_points: int,
    noise_tx: float,
    noise_ty: float,
    noise_yaw_deg: float,
    out_path: Path,
) -> None:
    paper_bg = "#f5f1e8"
    panel_bg = "#fbfaf7"
    zoom_box = (11.5, 22.5, 3.8, 10.3)
    rng = np.random.default_rng(20260324)
    veh = subsample_points(crop_points(vehicle_points, xlim, ylim, zlim), max_points, rng)
    inf_gt = subsample_points(crop_points(infra_points_gt, xlim, ylim, zlim), max_points, rng)
    inf_noisy = subsample_points(crop_points(infra_points_noisy, xlim, ylim, zlim), max_points, rng)

    fig, axes = plt.subplots(1, 2, figsize=(13.8, 6.8), dpi=220)
    fig.patch.set_facecolor(paper_bg)

    panels = [
        (axes[0], inf_gt, "GT extrinsic alignment"),
        (
            axes[1],
            inf_noisy,
            f"Noisy extrinsic alignment\n(dx={noise_tx:+.1f} m, dy={noise_ty:+.1f} m, yaw={noise_yaw_deg:+.1f} deg)",
        ),
    ]
    for ax, infra_pts, title in panels:
        ax.set_facecolor(panel_bg)
        ax.scatter(
            infra_pts[:, 0],
            infra_pts[:, 1],
            s=0.85,
            c="#d1495b",
            alpha=0.36,
            linewidths=0,
            rasterized=True,
            label="infra -> vehicle",
        )
        ax.scatter(
            veh[:, 0],
            veh[:, 1],
            s=0.85,
            c="#2a9d8f",
            alpha=0.36,
            linewidths=0,
            rasterized=True,
            label="vehicle",
        )
        _set_bev_axes(ax, xlim=xlim, ylim=ylim)
        ax.set_title(title, fontsize=12.5, pad=10)
        rect = Rectangle(
            (zoom_box[0], zoom_box[2]),
            zoom_box[1] - zoom_box[0],
            zoom_box[3] - zoom_box[2],
            fill=False,
            linewidth=1.2,
            linestyle="--",
            edgecolor="#2f4858",
            alpha=0.9,
        )
        ax.add_patch(rect)
        inset = inset_axes(ax, width="34%", height="34%", loc="lower right", borderpad=1.1)
        inset.set_facecolor("#ffffff")
        inset.scatter(infra_pts[:, 0], infra_pts[:, 1], s=2.4, c="#d1495b", alpha=0.42, linewidths=0, rasterized=True)
        inset.scatter(veh[:, 0], veh[:, 1], s=2.4, c="#2a9d8f", alpha=0.42, linewidths=0, rasterized=True)
        inset.set_xlim(zoom_box[0], zoom_box[1])
        inset.set_ylim(zoom_box[2], zoom_box[3])
        inset.set_xticks([])
        inset.set_yticks([])
        inset.set_aspect("equal")
        for spine in inset.spines.values():
            spine.set_linewidth(1.0)
            spine.set_edgecolor("#2f4858")
        mark_inset(ax, inset, loc1=2, loc2=4, fc="none", ec="#2f4858", lw=0.8, alpha=0.7)

    axes[1].text(
        0.03,
        0.97,
        "Severe offset splits object contours\nand breaks cross-agent overlap.",
        transform=axes[1].transAxes,
        va="top",
        ha="left",
        fontsize=10.5,
        bbox=dict(boxstyle="round,pad=0.35", facecolor="white", alpha=0.9, edgecolor="#d9d9d9"),
    )
    legend_handles = [
        mlines.Line2D([], [], color="#d1495b", marker="o", linestyle="None", markersize=6, label="infra -> vehicle"),
        mlines.Line2D([], [], color="#2a9d8f", marker="o", linestyle="None", markersize=6, label="vehicle"),
    ]
    axes[0].legend(handles=legend_handles, loc="upper left", frameon=True, framealpha=0.92)

    fig.suptitle("DAIR Multi-End Point Cloud Misalignment Under Extrinsic Offset", fontsize=16, y=0.992)
    fig.text(
        0.5,
        0.955,
        "Inset windows isolate the same local structure so the contour split is easier to read.",
        ha="center",
        va="center",
        fontsize=10.8,
        color="#4f5d5c",
    )
    fig.subplots_adjust(left=0.055, right=0.985, bottom=0.08, top=0.84, wspace=0.14)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def render_feature_ghosting(
    vehicle_points: np.ndarray,
    infra_points_gt: np.ndarray,
    infra_points_noisy: np.ndarray,
    xlim: Tuple[float, float],
    ylim: Tuple[float, float],
    zlim: Tuple[float, float],
    resolution: float,
    sigma: float,
    noise_tx: float,
    noise_ty: float,
    noise_yaw_deg: float,
    out_path: Path,
) -> None:
    panel_bg = "#fbfaf7"
    figure_bg = "#f5f1e8"
    struct_cmap = LinearSegmentedColormap.from_list(
        "warm_structure",
        ["#fffdf8", "#d8d0c2", "#8f8a80", "#24211f"],
    )

    ego_feature = make_bev_feature(vehicle_points, xlim=xlim, ylim=ylim, zlim=zlim, resolution=resolution, sigma=sigma)
    collab_feature_gt = make_bev_feature(
        infra_points_gt, xlim=xlim, ylim=ylim, zlim=zlim, resolution=resolution, sigma=sigma
    )
    collab_feature_noisy = make_bev_feature(
        infra_points_noisy, xlim=xlim, ylim=ylim, zlim=zlim, resolution=resolution, sigma=sigma
    )

    fusion_clean = normalize_feature(0.58 * ego_feature + 0.42 * collab_feature_gt)
    fusion_noisy = normalize_feature(0.58 * ego_feature + 0.42 * collab_feature_noisy)
    base_clean = make_structure_background(fusion_clean)
    base_noisy = make_structure_background(fusion_noisy)
    ego_edge = compute_edge_energy(ego_feature)
    collab_edge_clean = compute_edge_energy(collab_feature_gt)
    collab_edge_noisy = compute_edge_energy(collab_feature_noisy)
    fusion_edge_clean = compute_edge_energy(fusion_clean)
    fusion_edge_noisy = compute_edge_energy(fusion_noisy)
    ghost_score = normalize_feature(np.abs(fusion_edge_noisy - fusion_edge_clean) * (0.3 + base_noisy))

    ego_levels = contour_levels_from_maps(ego_edge)
    clean_levels = contour_levels_from_maps(collab_edge_clean)
    noisy_levels = contour_levels_from_maps(collab_edge_noisy)
    zoom_box = (11.5, 23.5, 3.8, 11.8)
    zoom_extent = (zoom_box[0], zoom_box[1], zoom_box[2], zoom_box[3])
    extent = (xlim[0], xlim[1], ylim[0], ylim[1])

    mosaic = [["clean", "noisy"], ["zoom", "zoom"]]
    fig = plt.figure(figsize=(14.4, 10.2), dpi=220)
    fig.patch.set_facecolor(figure_bg)
    axd = fig.subplot_mosaic(mosaic)

    clean_ax = axd["clean"]
    noisy_ax = axd["noisy"]
    zoom_ax = axd["zoom"]

    for ax in (clean_ax, noisy_ax, zoom_ax):
        ax.set_facecolor(panel_bg)

    clean_ax.imshow(base_clean, origin="lower", extent=extent, cmap=struct_cmap, vmin=0.0, vmax=1.0)
    clean_ax.contour(ego_edge, origin="lower", extent=extent, levels=ego_levels, colors=["#f7f7f5"], linewidths=0.95, alpha=0.7)
    clean_ax.contour(
        collab_edge_clean,
        origin="lower",
        extent=extent,
        levels=clean_levels,
        colors=["#2a9d8f"],
        linewidths=1.2,
        alpha=0.95,
    )
    _set_bev_axes(clean_ax, xlim=xlim, ylim=ylim)
    clean_ax.set_title("Clean Mid-Fusion Feature Alignment", fontsize=13.0)
    clean_ax.add_patch(
        Rectangle(
            (zoom_box[0], zoom_box[2]),
            zoom_box[1] - zoom_box[0],
            zoom_box[3] - zoom_box[2],
            fill=False,
            linewidth=1.15,
            linestyle="--",
            edgecolor="#f6bd60",
            alpha=0.98,
        )
    )
    clean_ax.text(
        0.03,
        0.97,
        "White = ego structure\nTeal = collaborator feature edge",
        transform=clean_ax.transAxes,
        va="top",
        ha="left",
        fontsize=10.2,
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.9, edgecolor="#d9d9d9"),
    )

    noisy_ax.imshow(base_noisy, origin="lower", extent=extent, cmap=struct_cmap, vmin=0.0, vmax=1.0)
    noisy_ax.contour(ego_edge, origin="lower", extent=extent, levels=ego_levels, colors=["#f7f7f5"], linewidths=0.95, alpha=0.68)
    noisy_ax.contour(
        collab_edge_clean,
        origin="lower",
        extent=extent,
        levels=clean_levels,
        colors=["#2a9d8f"],
        linewidths=0.9,
        linestyles="dashed",
        alpha=0.7,
    )
    noisy_ax.contour(
        collab_edge_noisy,
        origin="lower",
        extent=extent,
        levels=noisy_levels,
        colors=["#e76f51"],
        linewidths=1.2,
        alpha=0.96,
    )
    noisy_ax.imshow(ghost_score, origin="lower", extent=extent, cmap="inferno", vmin=0.0, vmax=1.0, alpha=0.28)
    _set_bev_axes(noisy_ax, xlim=xlim, ylim=ylim)
    noisy_ax.set_title(
        f"Noisy Mid-Fusion Feature Alignment\n(dx={noise_tx:+.1f} m, dy={noise_ty:+.1f} m, yaw={noise_yaw_deg:+.1f} deg)",
        fontsize=13.0,
    )
    noisy_ax.add_patch(
        Rectangle(
            (zoom_box[0], zoom_box[2]),
            zoom_box[1] - zoom_box[0],
            zoom_box[3] - zoom_box[2],
            fill=False,
            linewidth=1.15,
            linestyle="--",
            edgecolor="#f6bd60",
            alpha=0.98,
        )
    )
    noisy_ax.text(
        0.03,
        0.97,
        "Dashed teal = clean reference\nCoral = noisy warped collaborator edge",
        transform=noisy_ax.transAxes,
        va="top",
        ha="left",
        fontsize=10.2,
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.9, edgecolor="#d9d9d9"),
    )

    zoom_ax.imshow(crop_feature_box(base_noisy, xlim=xlim, ylim=ylim, resolution=resolution, box=zoom_box), origin="lower", extent=zoom_extent, cmap=struct_cmap, vmin=0.0, vmax=1.0)
    zoom_ax.contour(
        crop_feature_box(ego_edge, xlim=xlim, ylim=ylim, resolution=resolution, box=zoom_box),
        origin="lower",
        extent=zoom_extent,
        levels=ego_levels,
        colors=["#f7f7f5"],
        linewidths=1.1,
        alpha=0.75,
    )
    zoom_ax.contour(
        crop_feature_box(collab_edge_clean, xlim=xlim, ylim=ylim, resolution=resolution, box=zoom_box),
        origin="lower",
        extent=zoom_extent,
        levels=clean_levels,
        colors=["#2a9d8f"],
        linewidths=1.2,
        linestyles="dashed",
        alpha=0.88,
    )
    zoom_ax.contour(
        crop_feature_box(collab_edge_noisy, xlim=xlim, ylim=ylim, resolution=resolution, box=zoom_box),
        origin="lower",
        extent=zoom_extent,
        levels=noisy_levels,
        colors=["#e76f51"],
        linewidths=1.35,
        alpha=0.98,
    )
    _set_bev_axes(zoom_ax, xlim=(zoom_box[0], zoom_box[1]), ylim=(zoom_box[2], zoom_box[3]))
    zoom_ax.set_title("Zoomed Contour Split In The Fused Feature", fontsize=13.2)
    zoom_ax.annotate(
        "ghosted double edge",
        xy=(18.3, 6.6),
        xytext=(19.6, 10.9),
        arrowprops=dict(arrowstyle="->", color="#e76f51", lw=1.4),
        color="#e76f51",
        fontsize=11.0,
        ha="left",
        va="center",
        bbox=dict(boxstyle="round,pad=0.25", facecolor="white", edgecolor="#f0d0c7", alpha=0.92),
    )
    zoom_ax.annotate(
        "clean edge stays here",
        xy=(16.7, 6.0),
        xytext=(12.1, 10.8),
        arrowprops=dict(arrowstyle="->", color="#2a9d8f", lw=1.4),
        color="#1f7f74",
        fontsize=11.0,
        ha="left",
        va="center",
        bbox=dict(boxstyle="round,pad=0.25", facecolor="white", edgecolor="#c8e4df", alpha=0.92),
    )

    legend_handles = [
        mlines.Line2D([], [], color="#f7f7f5", linewidth=1.4, label="ego fused structure"),
        mlines.Line2D([], [], color="#2a9d8f", linewidth=1.8, linestyle="dashed", label="clean collaborator edge"),
        mlines.Line2D([], [], color="#e76f51", linewidth=1.8, label="noisy collaborator edge"),
    ]
    zoom_ax.legend(handles=legend_handles, loc="lower right", frameon=True, framealpha=0.92)

    fig.suptitle(
        "Mid-Fusion Ghosting From Noisy Extrinsics",
        fontsize=16,
        y=0.992,
    )
    fig.text(
        0.5,
        0.958,
        "Feature map is a BEV occupancy-style surrogate; the bottom row isolates where noisy warping creates duplicated feature edges.",
        ha="center",
        va="center",
        fontsize=10.8,
        color="#4f5d5c",
    )
    fig.subplots_adjust(left=0.055, right=0.985, bottom=0.07, top=0.865, wspace=0.12, hspace=0.2)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("data/DAIR-V2X"))
    parser.add_argument("--infra-id", default="001366", help="Infrastructure frame id with local PCD available.")
    parser.add_argument("--veh-id", default="017314", help="Vehicle frame id with local PCD available.")
    parser.add_argument("--noise-tx", type=float, default=2.8, help="Vehicle-frame x noise in meters.")
    parser.add_argument("--noise-ty", type=float, default=-1.6, help="Vehicle-frame y noise in meters.")
    parser.add_argument("--noise-yaw-deg", type=float, default=8.0, help="Vehicle-frame yaw noise in degrees.")
    parser.add_argument("--x-min", type=float, default=0.0)
    parser.add_argument("--x-max", type=float, default=60.0)
    parser.add_argument("--y-min", type=float, default=-25.0)
    parser.add_argument("--y-max", type=float, default=25.0)
    parser.add_argument("--z-min", type=float, default=-3.0)
    parser.add_argument("--z-max", type=float, default=2.5)
    parser.add_argument("--bev-resolution", type=float, default=0.20, help="BEV pixel size in meters.")
    parser.add_argument("--bev-sigma", type=float, default=1.4, help="Gaussian blur sigma on the BEV feature.")
    parser.add_argument("--max-points", type=int, default=35000, help="Point subsampling limit per cloud for scatter.")
    parser.add_argument("--out-dir", type=Path, default=Path("outputs/visualizations"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    xlim = (args.x_min, args.x_max)
    ylim = (args.y_min, args.y_max)
    zlim = (args.z_min, args.z_max)

    infra_pcd = args.data_root / "infrastructure-side" / "velodyne" / f"{args.infra_id}.pcd"
    veh_pcd = args.data_root / "vehicle-side" / "velodyne" / f"{args.veh_id}.pcd"
    calib_path = args.data_root / "cooperative" / "calib" / "lidar_i2v" / f"{args.veh_id}.json"
    for path in (infra_pcd, veh_pcd, calib_path):
        if not path.exists():
            raise FileNotFoundError(f"Required input not found: {path}")

    infra_points = read_pcd_xyz(infra_pcd)
    veh_points = read_pcd_xyz(veh_pcd)
    rotation_i2v, translation_i2v = load_lidar_i2v(calib_path)
    infra_points_gt = apply_rigid(infra_points, rotation_i2v, translation_i2v)
    noise_rotation, noise_translation = build_noise_transform(
        tx=args.noise_tx,
        ty=args.noise_ty,
        yaw_deg=args.noise_yaw_deg,
    )
    infra_points_noisy = apply_rigid(infra_points_gt, noise_rotation, noise_translation)

    pair_tag = f"infra{args.infra_id}_veh{args.veh_id}"
    out_alignment = args.out_dir / f"{pair_tag}_extrinsic_offset_pointcloud.png"
    out_ghost = args.out_dir / f"{pair_tag}_midfusion_ghosting.png"

    render_pointcloud_alignment(
        vehicle_points=veh_points,
        infra_points_gt=infra_points_gt,
        infra_points_noisy=infra_points_noisy,
        xlim=xlim,
        ylim=ylim,
        zlim=zlim,
        max_points=args.max_points,
        noise_tx=args.noise_tx,
        noise_ty=args.noise_ty,
        noise_yaw_deg=args.noise_yaw_deg,
        out_path=out_alignment,
    )
    render_feature_ghosting(
        vehicle_points=veh_points,
        infra_points_gt=infra_points_gt,
        infra_points_noisy=infra_points_noisy,
        xlim=xlim,
        ylim=ylim,
        zlim=zlim,
        resolution=args.bev_resolution,
        sigma=args.bev_sigma,
        noise_tx=args.noise_tx,
        noise_ty=args.noise_ty,
        noise_yaw_deg=args.noise_yaw_deg,
        out_path=out_ghost,
    )

    print(out_alignment)
    print(out_ghost)


if __name__ == "__main__":
    main()
