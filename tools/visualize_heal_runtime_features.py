#!/usr/bin/env python3
"""Render real HEAL runtime-feature misalignment and ghosting for one DAIR sample.

The figure uses the actual runtime tensors dumped from `heter_model_baseline`:

- `agent_bev`: real pre-fusion BEV feature for each agent
- `fused_feature`: real post-fusion feature after intermediate fusion

For readability, the visualization projects the 256-channel tensor to a 2D map
using a top-k channel-energy projection. It is therefore a visualization of the
real feature tensor, but not a single raw channel.
"""

import argparse
import copy
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.lines as mlines
import matplotlib.pyplot as plt
import numpy as np
import torch
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Rectangle
from mpl_toolkits.axes_grid1.inset_locator import inset_axes, mark_inset
from scipy.ndimage import gaussian_filter, sobel

REPO_ROOT = Path(__file__).resolve().parents[1]
HEAL_ROOT = REPO_ROOT / "HEAL"
if str(HEAL_ROOT) not in sys.path:
    sys.path.insert(0, str(HEAL_ROOT))

import opencood.hypes_yaml.yaml_utils as yaml_utils
from opencood.data_utils.datasets import build_dataset
from opencood.models.fuse_modules.fusion_in_one import warp_feature
from opencood.tools import train_utils
from opencood.utils.pose_utils import add_noise_data_dict


@dataclass
class RuntimeBundle:
    agent_bev: np.ndarray
    warped_agent_bev: np.ndarray
    fused_feature: np.ndarray
    affine_matrix: np.ndarray
    pairwise_t_matrix: np.ndarray
    lidar_pose: np.ndarray
    lidar_pose_clean: np.ndarray
    pose_confidence: np.ndarray
    record_len: np.ndarray
    cav_id_list: List[int]


def normalize_map(feature: np.ndarray) -> np.ndarray:
    feature = np.asarray(feature, dtype=np.float32)
    if not np.any(feature > 0):
        return np.zeros_like(feature, dtype=np.float32)
    nonzero = feature[feature > 0]
    denom = float(np.percentile(nonzero, 99.5))
    if denom <= 1e-6:
        denom = float(nonzero.max()) if nonzero.size else 1.0
    normalized = np.clip(feature / denom, 0.0, 1.0)
    return np.power(normalized, 0.72).astype(np.float32)


def compute_edge_energy(feature: np.ndarray) -> np.ndarray:
    grad_y = sobel(feature, axis=0)
    grad_x = sobel(feature, axis=1)
    edge = np.hypot(grad_x, grad_y)
    return normalize_map(edge)


def make_structure_background(feature: np.ndarray) -> np.ndarray:
    return np.clip(0.58 * feature + 0.74 * compute_edge_energy(feature), 0.0, 1.0)


def contour_levels_from_maps(*maps: np.ndarray) -> np.ndarray:
    nonzero = [m[m > 0] for m in maps if np.any(m > 0)]
    if not nonzero:
        return np.array([0.22, 0.4], dtype=np.float32)
    values = np.concatenate(nonzero)
    levels = np.quantile(values, [0.9, 0.972])
    levels = np.unique(np.clip(levels, 0.08, 0.96))
    return levels.astype(np.float32)


def project_feature_topk(feature_chw: np.ndarray, topk: int, blur_sigma: float) -> np.ndarray:
    feature = np.asarray(feature_chw, dtype=np.float32)
    centered = feature - np.median(feature, axis=(1, 2), keepdims=True)
    scale = np.percentile(np.abs(centered), 99.5, axis=(1, 2), keepdims=True)
    scale = np.where(scale > 1e-6, scale, 1.0).astype(np.float32)
    magnitude = np.clip(np.abs(centered) / scale, 0.0, 4.0)

    k = int(max(1, min(topk, magnitude.shape[0])))
    if k < magnitude.shape[0]:
        topk_map = np.partition(magnitude, magnitude.shape[0] - k, axis=0)[-k:]
    else:
        topk_map = magnitude

    projection = np.mean(topk_map, axis=0)
    if blur_sigma > 0:
        projection = gaussian_filter(projection, sigma=blur_sigma)
    return normalize_map(projection)


def metric_box_to_pixel_slices(
    xlim: Tuple[float, float],
    ylim: Tuple[float, float],
    box: Tuple[float, float, float, float],
    height: int,
    width: int,
) -> Tuple[slice, slice]:
    x0, x1, y0, y1 = box
    px0 = int(np.clip(np.floor((x0 - xlim[0]) / (xlim[1] - xlim[0]) * width), 0, width - 1))
    px1 = int(np.clip(np.ceil((x1 - xlim[0]) / (xlim[1] - xlim[0]) * width), px0 + 1, width))
    py0 = int(np.clip(np.floor((y0 - ylim[0]) / (ylim[1] - ylim[0]) * height), 0, height - 1))
    py1 = int(np.clip(np.ceil((y1 - ylim[0]) / (ylim[1] - ylim[0]) * height), py0 + 1, height))
    return slice(py0, py1), slice(px0, px1)


def crop_feature_box(
    feature: np.ndarray,
    xlim: Tuple[float, float],
    ylim: Tuple[float, float],
    box: Tuple[float, float, float, float],
) -> np.ndarray:
    y_slice, x_slice = metric_box_to_pixel_slices(
        xlim=xlim,
        ylim=ylim,
        box=box,
        height=feature.shape[0],
        width=feature.shape[1],
    )
    return feature[y_slice, x_slice]


def auto_zoom_box(
    score_map: np.ndarray,
    focus_map: np.ndarray,
    xlim: Tuple[float, float],
    ylim: Tuple[float, float],
    width_m: float = 26.0,
    height_m: float = 16.0,
) -> Tuple[float, float, float, float]:
    combined = gaussian_filter(np.asarray(score_map, dtype=np.float32), sigma=2.4) * (
        0.35 + gaussian_filter(np.asarray(focus_map, dtype=np.float32), sigma=1.5)
    )
    h, w = combined.shape
    margin_y = max(4, int(round(h * 0.12)))
    margin_x = max(4, int(round(w * 0.12)))
    combined[:margin_y, :] = 0.0
    combined[-margin_y:, :] = 0.0
    combined[:, :margin_x] = 0.0
    combined[:, -margin_x:] = 0.0
    peak_y, peak_x = np.unravel_index(int(np.argmax(combined)), combined.shape)
    x_center = xlim[0] + (peak_x + 0.5) * (xlim[1] - xlim[0]) / w
    y_center = ylim[0] + (peak_y + 0.5) * (ylim[1] - ylim[0]) / h

    half_w = width_m * 0.5
    half_h = height_m * 0.5
    x0 = np.clip(x_center - half_w, xlim[0], xlim[1] - width_m)
    y0 = np.clip(y_center - half_h, ylim[0], ylim[1] - height_m)
    x1 = x0 + width_m
    y1 = y0 + height_m
    return float(x0), float(x1), float(y0), float(y1)


def _set_bev_axes(ax, xlim: Tuple[float, float], ylim: Tuple[float, float]) -> None:
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_aspect("equal")
    ax.set_xlabel("x in ego BEV (m)")
    ax.set_ylabel("y in ego BEV (m)")
    ax.grid(True, linestyle="--", linewidth=0.45, alpha=0.18)
    ax.axhline(0.0, color="#888888", linewidth=0.7, alpha=0.25)
    ax.axvline(0.0, color="#888888", linewidth=0.7, alpha=0.25)


def build_hypes(model_dir: Path) -> dict:
    class _Opt:
        pass

    opt = _Opt()
    opt.model_dir = str(model_dir)
    hypes = yaml_utils.load_yaml(None, opt)
    hypes["validate_dir"] = hypes["test_dir"]
    for align_key in (
        "box_align",
        "v2xregpp_align",
        "freealign_align",
        "vips_align",
        "cbm_align",
        "pgc_pose",
    ):
        cfg = hypes.get(align_key)
        if isinstance(cfg, dict) and "test_result" in cfg:
            cfg["val_result"] = cfg["test_result"]
    return hypes


def noise_setting(noise_std: float) -> dict:
    if float(noise_std) <= 0:
        return {
            "add_noise": False,
            "args": {"pos_std": 0.0, "rot_std": 0.0, "pos_mean": 0.0, "rot_mean": 0.0},
        }
    return {
        "add_noise": True,
        "args": {
            "pos_std": float(noise_std),
            "rot_std": float(noise_std),
            "pos_mean": 0.0,
            "rot_mean": 0.0,
            "target": "non-ego",
        },
    }


def load_model(model_dir: Path, hypes: dict, device: torch.device) -> torch.nn.Module:
    model = train_utils.create_model(hypes)
    _, model = train_utils.load_saved_model(str(model_dir), model)
    model = model.to(device)
    model.eval()
    raw_model = model.module if hasattr(model, "module") else model
    raw_model.record_runtime_features = True
    return model


def extract_runtime_bundle(
    model: torch.nn.Module,
    hypes: dict,
    device: torch.device,
    sample_idx: int,
    noise_std: float,
    seed: int,
) -> RuntimeBundle:
    sample_hypes = copy.deepcopy(hypes)
    sample_hypes["noise_setting"] = noise_setting(noise_std)

    if hasattr(add_noise_data_dict, "_dropout_state"):
        delattr(add_noise_data_dict, "_dropout_state")
    np.random.seed(int(seed))

    dataset = build_dataset(sample_hypes, visualize=False, train=False)
    batch_data = dataset.collate_batch_test([dataset[int(sample_idx)]])
    batch_data = train_utils.to_device(batch_data, device)
    batch_data = train_utils.maybe_apply_pose_provider(batch_data, sample_hypes)

    with torch.no_grad():
        _ = model(batch_data["ego"])

    raw_model = model.module if hasattr(model, "module") else model
    runtime_store = getattr(raw_model, "_runtime_feature_store", {})
    warped = warp_feature(
        runtime_store["agent_bev"].detach().cpu(),
        runtime_store["record_len"].detach().cpu(),
        runtime_store["affine_matrix"].detach().cpu(),
    )

    ego = batch_data["ego"]
    return RuntimeBundle(
        agent_bev=runtime_store["agent_bev"].detach().cpu().numpy(),
        warped_agent_bev=warped.detach().cpu().numpy(),
        fused_feature=runtime_store["fused_feature"][0].detach().cpu().numpy(),
        affine_matrix=runtime_store["affine_matrix"].detach().cpu().numpy(),
        pairwise_t_matrix=runtime_store["pairwise_t_matrix"].detach().cpu().numpy(),
        lidar_pose=ego["lidar_pose"].detach().cpu().numpy(),
        lidar_pose_clean=ego["lidar_pose_clean"].detach().cpu().numpy(),
        pose_confidence=ego["pose_confidence"].detach().cpu().numpy(),
        record_len=runtime_store["record_len"].detach().cpu().numpy(),
        cav_id_list=list(ego.get("cav_id_list") or []),
    )


def render_real_feature_figure(
    clean: RuntimeBundle,
    noisy: RuntimeBundle,
    cav_range: List[float],
    noise_std: float,
    topk: int,
    blur_sigma: float,
    out_path: Path,
) -> None:
    xlim = (float(cav_range[0]), float(cav_range[3]))
    ylim = (float(cav_range[1]), float(cav_range[4]))
    extent = (xlim[0], xlim[1], ylim[0], ylim[1])
    if int(clean.record_len[0]) < 2:
        raise ValueError("This visualization expects at least two agents in the selected sample.")

    ego_map = project_feature_topk(clean.warped_agent_bev[0], topk=topk, blur_sigma=blur_sigma)
    collab_clean = project_feature_topk(clean.warped_agent_bev[1], topk=topk, blur_sigma=blur_sigma)
    collab_noisy = project_feature_topk(noisy.warped_agent_bev[1], topk=topk, blur_sigma=blur_sigma)
    fused_clean = project_feature_topk(clean.fused_feature, topk=topk, blur_sigma=blur_sigma)
    fused_noisy = project_feature_topk(noisy.fused_feature, topk=topk, blur_sigma=blur_sigma)

    pre_clean_bg = make_structure_background(normalize_map(0.68 * ego_map + 0.32 * collab_clean))
    pre_noisy_bg = make_structure_background(normalize_map(0.68 * ego_map + 0.32 * collab_noisy))
    post_noisy_bg = make_structure_background(fused_noisy)

    ego_edge = compute_edge_energy(ego_map)
    collab_clean_edge = compute_edge_energy(collab_clean)
    collab_noisy_edge = compute_edge_energy(collab_noisy)
    fused_clean_edge = compute_edge_energy(fused_clean)
    fused_noisy_edge = compute_edge_energy(fused_noisy)

    pre_ghost = normalize_map(
        np.abs(collab_noisy_edge - collab_clean_edge) * (0.25 + 0.75 * pre_noisy_bg)
        + 0.25 * np.abs(collab_noisy - collab_clean)
    )
    post_ghost = normalize_map(
        np.abs(fused_noisy_edge - fused_clean_edge) * (0.25 + 0.75 * post_noisy_bg)
        + 0.25 * np.abs(fused_noisy - fused_clean)
    )
    zoom_box = auto_zoom_box(
        post_ghost,
        focus_map=normalize_map(fused_clean_edge + fused_noisy_edge),
        xlim=xlim,
        ylim=ylim,
    )
    zoom_extent = (zoom_box[0], zoom_box[1], zoom_box[2], zoom_box[3])

    ego_levels = contour_levels_from_maps(ego_edge)
    collab_clean_levels = contour_levels_from_maps(collab_clean_edge)
    collab_noisy_levels = contour_levels_from_maps(collab_noisy_edge)
    fused_clean_levels = contour_levels_from_maps(fused_clean_edge)
    fused_noisy_levels = contour_levels_from_maps(fused_noisy_edge)

    pose_delta = noisy.lidar_pose - noisy.lidar_pose_clean
    collab_delta = pose_delta[1] if pose_delta.shape[0] > 1 else np.zeros(6, dtype=np.float32)

    figure_bg = "#f5f1e8"
    panel_bg = "#fbfaf7"
    struct_cmap = LinearSegmentedColormap.from_list(
        "warm_structure",
        ["#fffdf8", "#d8d0c2", "#8f8a80", "#24211f"],
    )

    fig = plt.figure(figsize=(14.8, 10.4), dpi=220)
    fig.patch.set_facecolor(figure_bg)
    axd = fig.subplot_mosaic(
        [["pre_clean", "pre_noisy"], ["post", "post"]],
        gridspec_kw={"height_ratios": [1.0, 1.15]},
    )
    pre_clean_ax = axd["pre_clean"]
    pre_noisy_ax = axd["pre_noisy"]
    post_ax = axd["post"]

    for ax in (pre_clean_ax, pre_noisy_ax, post_ax):
        ax.set_facecolor(panel_bg)

    pre_clean_ax.imshow(
        pre_clean_bg,
        origin="lower",
        extent=extent,
        cmap=struct_cmap,
        vmin=0.0,
        vmax=1.0,
        interpolation="bilinear",
    )
    pre_clean_ax.contour(
        ego_edge,
        origin="lower",
        extent=extent,
        levels=ego_levels,
        colors=["#f7f7f5"],
        linewidths=1.0,
        alpha=0.72,
    )
    pre_clean_ax.contour(
        collab_clean_edge,
        origin="lower",
        extent=extent,
        levels=collab_clean_levels,
        colors=["#2a9d8f"],
        linewidths=1.22,
        alpha=0.96,
    )
    pre_clean_ax.add_patch(
        Rectangle(
            (zoom_box[0], zoom_box[2]),
            zoom_box[1] - zoom_box[0],
            zoom_box[3] - zoom_box[2],
            fill=False,
            linewidth=1.1,
            linestyle="--",
            edgecolor="#f6bd60",
            alpha=0.95,
        )
    )
    _set_bev_axes(pre_clean_ax, xlim=xlim, ylim=ylim)
    pre_clean_ax.set_title("Real `agent_bev` Warped Into Ego BEV: Clean Extrinsics", fontsize=12.9)
    pre_clean_ax.text(
        0.03,
        0.97,
        "White = ego pre-fusion edge\nTeal = collaborator `agent_bev` after clean warp",
        transform=pre_clean_ax.transAxes,
        va="top",
        ha="left",
        fontsize=10.1,
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.92, edgecolor="#d9d9d9"),
    )

    pre_noisy_ax.imshow(
        pre_noisy_bg,
        origin="lower",
        extent=extent,
        cmap=struct_cmap,
        vmin=0.0,
        vmax=1.0,
        interpolation="bilinear",
    )
    pre_noisy_ax.imshow(
        pre_ghost,
        origin="lower",
        extent=extent,
        cmap="inferno",
        vmin=0.0,
        vmax=1.0,
        alpha=0.26,
        interpolation="bilinear",
    )
    pre_noisy_ax.contour(
        ego_edge,
        origin="lower",
        extent=extent,
        levels=ego_levels,
        colors=["#f7f7f5"],
        linewidths=1.0,
        alpha=0.7,
    )
    pre_noisy_ax.contour(
        collab_clean_edge,
        origin="lower",
        extent=extent,
        levels=collab_clean_levels,
        colors=["#2a9d8f"],
        linewidths=1.0,
        linestyles="dashed",
        alpha=0.82,
    )
    pre_noisy_ax.contour(
        collab_noisy_edge,
        origin="lower",
        extent=extent,
        levels=collab_noisy_levels,
        colors=["#e76f51"],
        linewidths=1.24,
        alpha=0.98,
    )
    pre_noisy_ax.add_patch(
        Rectangle(
            (zoom_box[0], zoom_box[2]),
            zoom_box[1] - zoom_box[0],
            zoom_box[3] - zoom_box[2],
            fill=False,
            linewidth=1.1,
            linestyle="--",
            edgecolor="#f6bd60",
            alpha=0.95,
        )
    )
    _set_bev_axes(pre_noisy_ax, xlim=xlim, ylim=ylim)
    pre_noisy_ax.set_title(
        "Real `agent_bev` Warped Into Ego BEV: Noisy Extrinsics",
        fontsize=12.9,
    )
    pre_noisy_ax.text(
        0.03,
        0.97,
        (
            "Dashed teal = clean collaborator edge\n"
            "Coral = noisy collaborator edge\n"
            f"Injected non-ego pose noise: dx={collab_delta[0]:+.1f} m, "
            f"dy={collab_delta[1]:+.1f} m, yaw={collab_delta[4]:+.1f} deg"
        ),
        transform=pre_noisy_ax.transAxes,
        va="top",
        ha="left",
        fontsize=10.0,
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.92, edgecolor="#d9d9d9"),
    )

    post_ax.imshow(
        post_noisy_bg,
        origin="lower",
        extent=extent,
        cmap=struct_cmap,
        vmin=0.0,
        vmax=1.0,
        interpolation="bilinear",
    )
    post_ax.imshow(
        post_ghost,
        origin="lower",
        extent=extent,
        cmap="inferno",
        vmin=0.0,
        vmax=1.0,
        alpha=0.3,
        interpolation="bilinear",
    )
    post_ax.contour(
        fused_clean_edge,
        origin="lower",
        extent=extent,
        levels=fused_clean_levels,
        colors=["#2a9d8f"],
        linewidths=1.1,
        linestyles="dashed",
        alpha=0.88,
    )
    post_ax.contour(
        fused_noisy_edge,
        origin="lower",
        extent=extent,
        levels=fused_noisy_levels,
        colors=["#e76f51"],
        linewidths=1.32,
        alpha=0.98,
    )
    post_ax.add_patch(
        Rectangle(
            (zoom_box[0], zoom_box[2]),
            zoom_box[1] - zoom_box[0],
            zoom_box[3] - zoom_box[2],
            fill=False,
            linewidth=1.18,
            linestyle="--",
            edgecolor="#f6bd60",
            alpha=0.98,
        )
    )
    _set_bev_axes(post_ax, xlim=xlim, ylim=ylim)
    post_ax.set_title("Real `fused_feature`: Noisy Warp Creates A Ghosted Double Ridge", fontsize=13.3)
    post_ax.text(
        0.02,
        0.97,
        "Dashed teal = clean fused-feature edge\nCoral = noisy fused-feature edge\nInferno overlay = strongest clean-vs-noisy drift",
        transform=post_ax.transAxes,
        va="top",
        ha="left",
        fontsize=10.2,
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.92, edgecolor="#d9d9d9"),
    )

    zoom_ax = inset_axes(post_ax, width="35%", height="38%", loc="lower right", borderpad=1.05)
    zoom_ax.set_facecolor("#ffffff")
    zoom_ax.imshow(
        crop_feature_box(post_noisy_bg, xlim=xlim, ylim=ylim, box=zoom_box),
        origin="lower",
        extent=zoom_extent,
        cmap=struct_cmap,
        vmin=0.0,
        vmax=1.0,
        interpolation="bilinear",
    )
    zoom_ax.imshow(
        crop_feature_box(post_ghost, xlim=xlim, ylim=ylim, box=zoom_box),
        origin="lower",
        extent=zoom_extent,
        cmap="inferno",
        vmin=0.0,
        vmax=1.0,
        alpha=0.34,
        interpolation="bilinear",
    )
    zoom_ax.contour(
        crop_feature_box(fused_clean_edge, xlim=xlim, ylim=ylim, box=zoom_box),
        origin="lower",
        extent=zoom_extent,
        levels=fused_clean_levels,
        colors=["#2a9d8f"],
        linewidths=1.18,
        linestyles="dashed",
        alpha=0.9,
    )
    zoom_ax.contour(
        crop_feature_box(fused_noisy_edge, xlim=xlim, ylim=ylim, box=zoom_box),
        origin="lower",
        extent=zoom_extent,
        levels=fused_noisy_levels,
        colors=["#e76f51"],
        linewidths=1.28,
        alpha=0.98,
    )
    _set_bev_axes(zoom_ax, xlim=(zoom_box[0], zoom_box[1]), ylim=(zoom_box[2], zoom_box[3]))
    zoom_ax.set_title("Auto Zoom", fontsize=11.2, pad=7)
    zoom_ax.annotate(
        "clean edge",
        xy=(zoom_box[0] + 0.38 * (zoom_box[1] - zoom_box[0]), zoom_box[2] + 0.32 * (zoom_box[3] - zoom_box[2])),
        xytext=(zoom_box[0] + 0.08 * (zoom_box[1] - zoom_box[0]), zoom_box[2] + 0.83 * (zoom_box[3] - zoom_box[2])),
        arrowprops=dict(arrowstyle="->", color="#2a9d8f", lw=1.3),
        color="#1f7f74",
        fontsize=10.0,
        ha="left",
        va="center",
        bbox=dict(boxstyle="round,pad=0.22", facecolor="white", edgecolor="#c8e4df", alpha=0.92),
    )
    zoom_ax.annotate(
        "ghosted edge",
        xy=(zoom_box[0] + 0.58 * (zoom_box[1] - zoom_box[0]), zoom_box[2] + 0.42 * (zoom_box[3] - zoom_box[2])),
        xytext=(zoom_box[0] + 0.53 * (zoom_box[1] - zoom_box[0]), zoom_box[2] + 0.86 * (zoom_box[3] - zoom_box[2])),
        arrowprops=dict(arrowstyle="->", color="#e76f51", lw=1.3),
        color="#e76f51",
        fontsize=10.0,
        ha="left",
        va="center",
        bbox=dict(boxstyle="round,pad=0.22", facecolor="white", edgecolor="#f0d0c7", alpha=0.92),
    )
    for spine in zoom_ax.spines.values():
        spine.set_linewidth(1.0)
        spine.set_edgecolor("#2f4858")
    mark_inset(post_ax, zoom_ax, loc1=2, loc2=4, fc="none", ec="#2f4858", lw=0.8, alpha=0.7)

    legend_handles = [
        mlines.Line2D([], [], color="#f7f7f5", linewidth=1.4, label="ego pre-fusion edge"),
        mlines.Line2D([], [], color="#2a9d8f", linewidth=1.8, linestyle="dashed", label="clean reference edge"),
        mlines.Line2D([], [], color="#e76f51", linewidth=1.8, label="noisy edge"),
    ]
    pre_noisy_ax.legend(handles=legend_handles, loc="lower right", frameon=True, framealpha=0.92)

    fig.suptitle("Real HEAL Runtime Feature Misalignment And Mid-Fusion Ghosting", fontsize=16.2, y=0.992)
    fig.text(
        0.5,
        0.958,
        (
            f"Projection uses the strongest top-{topk} channel activations from the real 256-channel tensor. "
            "Top row: `agent_bev` after warp into ego BEV. Bottom: post-fusion `fused_feature`."
        ),
        ha="center",
        va="center",
        fontsize=10.8,
        color="#4f5d5c",
    )
    fig.subplots_adjust(left=0.055, right=0.985, bottom=0.07, top=0.87, wspace=0.12, hspace=0.2)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def save_bundle_dump(clean: RuntimeBundle, noisy: RuntimeBundle, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out_path,
        clean_agent_bev=clean.agent_bev,
        clean_warped_agent_bev=clean.warped_agent_bev,
        clean_fused_feature=clean.fused_feature,
        clean_affine_matrix=clean.affine_matrix,
        clean_pairwise_t_matrix=clean.pairwise_t_matrix,
        clean_lidar_pose=clean.lidar_pose,
        clean_lidar_pose_clean=clean.lidar_pose_clean,
        clean_pose_confidence=clean.pose_confidence,
        noisy_agent_bev=noisy.agent_bev,
        noisy_warped_agent_bev=noisy.warped_agent_bev,
        noisy_fused_feature=noisy.fused_feature,
        noisy_affine_matrix=noisy.affine_matrix,
        noisy_pairwise_t_matrix=noisy.pairwise_t_matrix,
        noisy_lidar_pose=noisy.lidar_pose,
        noisy_lidar_pose_clean=noisy.lidar_pose_clean,
        noisy_pose_confidence=noisy.pose_confidence,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path("HEAL/opencood/logs/HeterBaseline_DAIR_lidar_v2xvit_2023_09_09_11_19_26"),
    )
    parser.add_argument("--sample-idx", type=int, default=160)
    parser.add_argument("--noise-std", type=float, default=10.0, help="XY translation std and yaw std in deg.")
    parser.add_argument("--seed", type=int, default=303)
    parser.add_argument("--topk", type=int, default=24, help="Top-k channels used in the 2D feature projection.")
    parser.add_argument("--blur-sigma", type=float, default=0.8, help="Gaussian blur on the projected 2D map.")
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    parser.add_argument("--out-dir", type=Path, default=Path("outputs/visualizations"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model_dir = (REPO_ROOT / args.model_dir).resolve() if not args.model_dir.is_absolute() else args.model_dir
    device = torch.device("cuda" if args.device == "cuda" and torch.cuda.is_available() else "cpu")
    hypes = build_hypes(model_dir)
    cav_range = list(hypes["cav_lidar_range"])

    model = load_model(model_dir, hypes, device=device)
    clean = extract_runtime_bundle(
        model=model,
        hypes=hypes,
        device=device,
        sample_idx=args.sample_idx,
        noise_std=0.0,
        seed=args.seed,
    )
    noisy = extract_runtime_bundle(
        model=model,
        hypes=hypes,
        device=device,
        sample_idx=args.sample_idx,
        noise_std=args.noise_std,
        seed=args.seed,
    )

    sample_tag = f"dair_s{args.sample_idx:04d}_n{int(round(args.noise_std))}"
    out_png = args.out_dir / f"{sample_tag}_heal_real_feature_ghosting.png"
    out_npz = args.out_dir / f"{sample_tag}_heal_real_feature_dump.npz"
    save_bundle_dump(clean, noisy, out_npz)
    render_real_feature_figure(
        clean=clean,
        noisy=noisy,
        cav_range=cav_range,
        noise_std=args.noise_std,
        topk=args.topk,
        blur_sigma=args.blur_sigma,
        out_path=out_png,
    )

    pose_delta = noisy.lidar_pose - noisy.lidar_pose_clean
    collab_delta = pose_delta[1] if pose_delta.shape[0] > 1 else np.zeros(6, dtype=np.float32)
    print(f"figure={out_png}")
    print(f"tensor_dump={out_npz}")
    print("feature_stage=agent_bev (pre-fusion) + fused_feature (post-fusion)")
    print(
        "non_ego_noise="
        f"dx={collab_delta[0]:+.3f}m dy={collab_delta[1]:+.3f}m yaw={collab_delta[4]:+.3f}deg"
    )


if __name__ == "__main__":
    main()
