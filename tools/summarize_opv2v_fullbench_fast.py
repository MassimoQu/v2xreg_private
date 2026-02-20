#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple


def parse_log(path: Path) -> Dict[str, Dict[str, float]]:
    results: Dict[str, Dict[str, float]] = {}
    current_noise = None
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("Noise Added:"):
            m = re.search(r"Noise Added: ([0-9.]+)", line)
            if m:
                current_noise = f"{float(m.group(1)):.1f}"
                results.setdefault(current_noise, {})
            continue
        if "The Average Precision at IOU" in line and current_noise:
            m = re.search(r"IOU ([0-9.]+) is ([0-9.]+)", line)
            if m:
                iou = m.group(1)
                ap = float(m.group(2))
                results[current_noise][iou] = ap
    return results


def parse_logs(log_dirs: List[Path]) -> Dict[Tuple[str, str, str, str, str], Dict[str, float]]:
    data: Dict[Tuple[str, str, str, str, str], Dict[str, float]] = {}
    for log_dir in log_dirs:
        if not log_dir.exists():
            continue
        for path in log_dir.glob("*.log"):
            name = path.name
            # new-style: modality_sweep_method_strategy_nX.log
            m = re.match(r"(camera|lidar)_(noise10|drop20)_([a-z0-9_]+)_(best|stable|bounds)_n([0-9.]+)\.log", name)
            if m:
                modality, sweep, method, strategy, noise = m.groups()
                parsed = parse_log(path)
                noise_key = f"{float(noise):.1f}"
                if noise_key in parsed:
                    data[(modality, sweep, method, strategy, noise_key)] = parsed[noise_key]
                continue
            # legacy: modality_sweep_baseline|oracle|single.log
            m = re.match(r"(camera|lidar)_(noise10|drop20)_(baseline|oracle|single)\.log", name)
            if m:
                modality, sweep, method = m.groups()
                parsed = parse_log(path)
                for noise_key, ap in parsed.items():
                    data[(modality, sweep, method, "bounds", noise_key)] = ap
                continue
            # legacy: modality_sweep_method_best|stable.log
            m = re.match(r"(camera|lidar)_(noise10|drop20)_([a-z0-9_]+)_(best|stable)\.log", name)
            if m:
                modality, sweep, method, strategy = m.groups()
                parsed = parse_log(path)
                for noise_key, ap in parsed.items():
                    data[(modality, sweep, method, strategy, noise_key)] = ap
                continue
    return data


def build_series(data: Dict[Tuple[str, str, str, str, str], Dict[str, float]], sweep: str, modality: str) -> Dict[Tuple[str, str], Dict[str, float]]:
    series: Dict[Tuple[str, str], Dict[str, float]] = {}
    for (mod, sw, method, strategy, noise), ap in data.items():
        if mod != modality or sw != sweep:
            continue
        key = (method, strategy)
        series.setdefault(key, {})[noise] = ap.get("0.5", None)
    return series


def plot_series(out_path: Path, title: str, series: Dict[Tuple[str, str], Dict[str, float]], noise_axis: List[str], modality: str) -> None:
    import matplotlib.pyplot as plt

    color_map = {
        "v2xregpp": "#1f77b4",
        "freealign": "#ff7f0e",
        "vips": "#2ca02c",
        "cbm": "#d62728",
        "baseline": "#7f7f7f",
        "oracle": "#9467bd",
        "single": "#000000",
    }
    style_map = {
        "best": "-",
        "stable": "--",
        "bounds": "-",
    }

    x_vals = [float(x) for x in noise_axis]
    fig, ax = plt.subplots(figsize=(8.0, 5.0))
    for (method, strategy), points in series.items():
        ys = []
        for noise in noise_axis:
            val = points.get(noise)
            if val is None and method == "single":
                # single is constant; use noise 0 if present
                val = points.get("0.0")
            ys.append(val)
        if all(v is None for v in ys):
            continue
        ax.plot(
            x_vals,
            ys,
            color=color_map.get(method, "#333333"),
            linestyle=style_map.get(strategy, "-"),
            linewidth=1.8,
            label=f"{method}-{strategy}",
        )

    ax.set_xlabel("pos_std (m) / rot_std (deg)")
    ax.set_ylabel("AP50")
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.set_title(title)
    ax.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200)


def plot_combined(out_path: Path, title: str, series_by_modality: Dict[str, Dict[Tuple[str, str], Dict[str, float]]], noise_axis: List[str]) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    color_map = {
        "v2xregpp": "#1f77b4",
        "freealign": "#ff7f0e",
        "vips": "#2ca02c",
        "cbm": "#d62728",
        "baseline": "#7f7f7f",
        "oracle": "#9467bd",
        "single": "#000000",
    }
    style_map = {
        "best": "-",
        "stable": "--",
        "bounds": "-",
    }
    marker_map = {"camera": "o", "lidar": "^"}

    x_vals = [float(x) for x in noise_axis]
    fig, ax = plt.subplots(figsize=(9.0, 5.5))
    for modality, series in series_by_modality.items():
        for (method, strategy), points in series.items():
            ys = []
            for noise in noise_axis:
                val = points.get(noise)
                if val is None and method == "single":
                    val = points.get("0.0")
                ys.append(val)
            if all(v is None for v in ys):
                continue
            ax.plot(
                x_vals,
                ys,
                color=color_map.get(method, "#333333"),
                linestyle=style_map.get(strategy, "-"),
                marker=marker_map.get(modality, "o"),
                markersize=4.0,
                linewidth=1.6,
            )

    ax.set_xlabel("pos_std (m) / rot_std (deg)")
    ax.set_ylabel("AP50")
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.set_title(title)

    method_handles = [Line2D([0], [0], color=c, linestyle="-", linewidth=2.0, label=m) for m, c in color_map.items()]
    legend_methods = ax.legend(handles=method_handles, title="Method (color)", fontsize=8, ncol=2, loc="upper right")
    ax.add_artist(legend_methods)

    style_handles = [
        Line2D([0], [0], color="black", linestyle=style_map["best"], label="best"),
        Line2D([0], [0], color="black", linestyle=style_map["stable"], label="stable"),
    ]
    legend_style = ax.legend(handles=style_handles, title="Line Style", fontsize=8, loc="lower left")
    ax.add_artist(legend_style)

    modality_handles = [
        Line2D([0], [0], color="black", marker=marker_map["camera"], linestyle="None", label="camera"),
        Line2D([0], [0], color="black", marker=marker_map["lidar"], linestyle="None", label="lidar"),
    ]
    ax.legend(handles=modality_handles, title="Modality", fontsize=8, loc="lower right")

    fig.tight_layout()
    fig.savefig(out_path, dpi=200)


def validate_complete(series: Dict[Tuple[str, str], Dict[str, float]], noise_axis: List[str]) -> List[str]:
    missing = []
    for (method, strategy), points in series.items():
        if method == "single":
            if "0.0" not in points:
                missing.append(f"{method}-{strategy}: missing noise 0.0")
            continue
        for noise in noise_axis:
            if points.get(noise) is None:
                missing.append(f"{method}-{strategy}: missing noise {noise}")
    return missing


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--log-dir", type=Path, action="append", default=[])
    p.add_argument("--out-json", type=Path, default=None)
    p.add_argument("--plot-dir", type=Path, default=None)
    p.add_argument("--metric", type=str, default="ap50")
    args = p.parse_args()

    log_dirs = [args.run_dir / "logs"] + args.log_dir
    data = parse_logs(log_dirs)

    out_json = args.out_json or (args.run_dir / "results_ap.json")
    out_json.write_text(json.dumps({"entries": [
        {
            "modality": k[0],
            "sweep": k[1],
            "method": k[2],
            "strategy": k[3],
            "noise": k[4],
            "ap": v,
        }
        for k, v in sorted(data.items())
    ]}, indent=2))

    if args.plot_dir:
        args.plot_dir.mkdir(parents=True, exist_ok=True)
        noise_axis = [f"{float(x):.1f}" for x in range(1, 11)]
        for sweep in ("noise10", "drop20"):
            for modality in ("camera", "lidar"):
                series = build_series(data, sweep=sweep, modality=modality)
                missing = validate_complete(series, noise_axis)
                if missing:
                    raise ValueError(f"Incomplete series for {modality}-{sweep}: {missing[:5]}")
                out_path = args.plot_dir / f"{sweep}_{modality}_ap50.png"
                plot_series(out_path, f"OPV2V {modality} {sweep} AP50", series, noise_axis, modality)
            series_by_mod = {
                "camera": build_series(data, sweep=sweep, modality="camera"),
                "lidar": build_series(data, sweep=sweep, modality="lidar"),
            }
            out_path = args.plot_dir / f"{sweep}_combined_ap50.png"
            plot_combined(out_path, f"OPV2V combined {sweep} AP50", series_by_mod, noise_axis)


if __name__ == "__main__":
    main()
