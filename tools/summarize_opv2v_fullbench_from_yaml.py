#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml


Key = Tuple[str, str, str, str, str]  # modality, sweep, method, strategy, noise


def normalize_noise(val: str) -> str:
    return f"{float(val):.1f}"


def load_config_snapshot(run_dir: Path) -> dict:
    path = run_dir / "config_snapshot.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing config snapshot: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def iter_ap_yamls(model_dir: Path) -> Iterable[Path]:
    if not model_dir.exists():
        return []
    return sorted(model_dir.glob("AP030507_*.yaml"))


def parse_ap_filename(path: Path, run_id: str) -> Optional[Tuple[Key, str]]:
    """
    Parse a filename produced by HEAL/opencood/tools/inference_w_noise.py:
      AP030507_{pose_correction}_{run_id}_{modality}_{sweep}_... .yaml

    Returns: ((modality, sweep, method, strategy, noise), pose_correction)
    """
    stem = path.stem
    if not stem.startswith("AP030507_"):
        return None

    marker = f"_{run_id}_"
    pos = stem.find(marker)
    if pos < 0:
        return None

    pose_correction = stem[len("AP030507_") : pos]
    remainder = stem[pos + len(marker) :]

    # single (comm_range=0) => noise 0.0
    m = re.match(r"^(camera|lidar)_(noise10|drop20)_single$", remainder)
    if m:
        modality, sweep = m.groups()
        return (modality, sweep, "single", "bounds", normalize_noise("0")), pose_correction

    # baseline/oracle bounds
    m = re.match(r"^(camera|lidar)_(noise10|drop20)_(baseline|oracle)_n([0-9.]+)$", remainder)
    if m:
        modality, sweep, method, noise = m.groups()
        return (modality, sweep, method, "bounds", normalize_noise(noise)), pose_correction

    # methods best/stable
    m = re.match(r"^(camera|lidar)_(noise10|drop20)_([a-z0-9_]+)_(best|stable)_n([0-9.]+)$", remainder)
    if m:
        modality, sweep, method, strategy, noise = m.groups()
        return (modality, sweep, method, strategy, normalize_noise(noise)), pose_correction

    return None


def _first_float(v: Any) -> Optional[float]:
    if isinstance(v, list) and v:
        try:
            return float(v[0])
        except Exception:
            return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def collect_entries(
    *,
    run_id: str,
    camera_model_dir: Path,
    lidar_model_dir: Path,
) -> Dict[Key, dict]:
    data: Dict[Key, dict] = {}
    chosen_mtime: Dict[Key, float] = {}
    for model_dir in (camera_model_dir, lidar_model_dir):
        for path in iter_ap_yamls(model_dir):
            parsed = parse_ap_filename(path, run_id=run_id)
            if not parsed:
                continue
            key, _pose = parsed
            obj = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore"))
            ap30_val = _first_float(obj.get("ap30"))
            ap50_val = _first_float(obj.get("ap50"))
            ap70_val = _first_float(obj.get("ap70"))
            if ap50_val is None:
                raise ValueError(f"Invalid/missing ap50 in {path}: {type(obj.get('ap50'))}")

            # Sanity-check: filename noise vs YAML content.
            expected_noise = key[4]
            pos_list = obj.get("pos_std_list") or []
            if pos_list:
                actual_noise = normalize_noise(str(pos_list[0]))
                if actual_noise != expected_noise:
                    raise ValueError(f"Noise mismatch in {path}: filename={expected_noise} yaml={actual_noise}")
            mtime = path.stat().st_mtime
            # Prefer the newest file if duplicates exist (same key re-run).
            if key not in chosen_mtime or mtime >= chosen_mtime[key]:
                entry: dict = {
                    "ap30": ap30_val,
                    "ap50": ap50_val,
                    "ap70": ap70_val,
                }
                # timing stats (optional)
                ts_list = obj.get("timing_stats") or []
                ts0 = ts_list[0] if isinstance(ts_list, list) and ts_list else {}
                if isinstance(ts0, dict):
                    entry.update(
                        {
                            "infer_fps": ts0.get("infer_fps"),
                            "infer_sec": ts0.get("infer_sec"),
                            "pose_fps": ts0.get("pose_fps"),
                            "pose_sec": ts0.get("pose_sec"),
                            "samples": ts0.get("samples"),
                        }
                    )
                    ps = ts0.get("pose_solver")
                    if isinstance(ps, dict):
                        entry.update(
                            {
                                "pose_solver_applied": ps.get("applied"),
                                "pose_solver_avg_time_sec": ps.get("avg_time_sec"),
                                "pose_solver_samples": ps.get("samples"),
                            }
                        )

                data[key] = entry
                chosen_mtime[key] = mtime
    return data


def build_series(data: Dict[Key, dict], *, modality: str, sweep: str, field: str) -> Dict[Tuple[str, str], Dict[str, float]]:
    series: Dict[Tuple[str, str], Dict[str, float]] = {}
    for (mod, sw, method, strategy, noise), entry in data.items():
        if mod != modality or sw != sweep:
            continue
        val = entry.get(field)
        if val is None:
            continue
        series.setdefault((method, strategy), {})[noise] = float(val)
    return series


def validate_complete(
    series: Dict[Tuple[str, str], Dict[str, float]],
    *,
    noise_axis: List[str],
    expected_lines: List[Tuple[str, str]],
) -> List[str]:
    missing: List[str] = []
    for method, strategy in expected_lines:
        points = series.get((method, strategy))
        if not points:
            missing.append(f"{method}-{strategy}: missing entire line")
            continue
        if method == "single":
            if "0.0" not in points:
                missing.append(f"{method}-{strategy}: missing noise 0.0")
            continue
        for noise in noise_axis:
            if points.get(noise) is None:
                missing.append(f"{method}-{strategy}: missing noise {noise}")
    return missing


def plot_series(
    out_path: Path,
    *,
    title: str,
    series: Dict[Tuple[str, str], Dict[str, float]],
    noise_axis: List[str],
    ylabel: str,
) -> None:
    import matplotlib.pyplot as plt

    color_map = {
        "v2xregpp": "#1f77b4",
        "v2xregpp_occhint": "#0c5da5",
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
    for (method, strategy), points in sorted(series.items()):
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
            linewidth=1.8,
            label=f"{method}-{strategy}",
        )

    ax.set_xlabel("pos_std (m) / rot_std (deg)")
    ax.set_ylabel(ylabel)
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.set_title(title)
    ax.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200)


def plot_combined(
    out_path: Path,
    *,
    title: str,
    series_by_modality: Dict[str, Dict[Tuple[str, str], Dict[str, float]]],
    noise_axis: List[str],
    ylabel: str,
) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    color_map = {
        "v2xregpp": "#1f77b4",
        "v2xregpp_occhint": "#0c5da5",
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
    ax.set_ylabel(ylabel)
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


def main() -> None:
    p = argparse.ArgumentParser(description="Summarize OPV2V fullbench by scanning AP030507 YAMLs in model dirs.")
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--run-id", type=str, default=None, help="Defaults to basename after full_bench_.")
    p.add_argument("--out-json", type=Path, default=None)
    p.add_argument("--plot-dir", type=Path, default=None)
    p.add_argument("--allow-incomplete", action="store_true")
    args = p.parse_args()

    run_dir = args.run_dir
    if not args.run_id:
        # outputs/full_bench_<RUN_ID>
        name = run_dir.name
        args.run_id = name[len("full_bench_") :] if name.startswith("full_bench_") else name

    cfg = load_config_snapshot(run_dir)
    camera_model = Path(cfg["camera_model"])
    lidar_model = Path(cfg["lidar_model"])
    # Respect the actual benchmark scope recorded by the scheduler.
    # Smoke runs may only include a subset of sweeps/modalities.
    raw_modalities = cfg.get("modalities") or "camera,lidar"
    raw_sweeps = cfg.get("sweeps") or "noise10,drop20"
    modalities = [x.strip() for x in str(raw_modalities).split(",") if x.strip()]
    sweeps = [x.strip() for x in str(raw_sweeps).split(",") if x.strip()]
    if not modalities:
        modalities = ["camera", "lidar"]
    if not sweeps:
        sweeps = ["noise10", "drop20"]

    data = collect_entries(run_id=args.run_id, camera_model_dir=camera_model, lidar_model_dir=lidar_model)

    out_json = args.out_json or (run_dir / "results_ap50_from_yaml.json")
    out_json.write_text(
        json.dumps(
            {
                "run_id": args.run_id,
                "camera_model": str(camera_model),
                "lidar_model": str(lidar_model),
                "entries": [
                    {
                        "modality": k[0],
                        "sweep": k[1],
                        "method": k[2],
                        "strategy": k[3],
                        "noise": k[4],
                        **v,
                    }
                    for k, v in sorted(data.items())
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    plot_dir = args.plot_dir or (run_dir / "plots_yaml")
    plot_dir.mkdir(parents=True, exist_ok=True)

    # Prefer config snapshot noise axis; fall back to legacy 1..10.
    raw_noise_axis = cfg.get("noise_list") or []
    if isinstance(raw_noise_axis, list) and raw_noise_axis:
        noise_axis = [normalize_noise(str(x)) for x in raw_noise_axis]
    else:
        noise_axis = [normalize_noise(str(x)) for x in range(1, 11)]

    # Hard gate: if a pose-correction line exists but never applies pose updates, the comparison is invalid.
    if not args.allow_incomplete:
        problems = []
        raw_methods = cfg.get("methods") or ["v2xregpp", "freealign", "vips", "cbm"]
        if isinstance(raw_methods, str):
            methods = [x.strip() for x in raw_methods.split(",") if x.strip()]
        elif isinstance(raw_methods, list):
            methods = [str(x).strip() for x in raw_methods if str(x).strip()]
        else:
            methods = ["v2xregpp", "freealign", "vips", "cbm"]
        for modality in modalities:
            for sweep in sweeps:
                for method in methods:
                    for strategy in ("best", "stable"):
                        applied_vals = []
                        missing = 0
                        for noise in noise_axis:
                            entry = data.get((modality, sweep, method, strategy, noise))
                            if not entry:
                                missing += 1
                                continue
                            if "pose_solver_applied" not in entry:
                                missing += 1
                                continue
                            v = entry.get("pose_solver_applied")
                            if isinstance(v, int):
                                applied_vals.append(v)
                        if applied_vals and all(v == 0 for v in applied_vals):
                            problems.append(f"{modality}/{sweep}/{method}/{strategy}: pose_solver.applied all zero")
                        if applied_vals and missing:
                            problems.append(f"{modality}/{sweep}/{method}/{strategy}: missing pose_solver_applied for {missing} points")
        if problems:
            raise SystemExit("Invalid pose-correction results (pose solver never applied): " + "; ".join(problems[:6]))

    for sweep in sweeps:
        for modality in modalities:
            for field, label in (("ap30", "AP30"), ("ap50", "AP50"), ("ap70", "AP70")):
                series = build_series(data, modality=modality, sweep=sweep, field=field)
                # Determine expected lines from config snapshot for stricter completeness checks.
                raw_methods = cfg.get("methods") or ["v2xregpp", "freealign", "vips", "cbm"]
                if isinstance(raw_methods, str):
                    methods = [x.strip() for x in raw_methods.split(",") if x.strip()]
                elif isinstance(raw_methods, list):
                    methods = [str(x).strip() for x in raw_methods if str(x).strip()]
                else:
                    methods = ["v2xregpp", "freealign", "vips", "cbm"]
                include_baseline = not bool(cfg.get("skip_baseline", False))
                include_oracle = not bool(cfg.get("skip_oracle", False))
                include_single = not bool(cfg.get("skip_single", False))

                expected_lines = []
                if include_baseline:
                    expected_lines.append(("baseline", "bounds"))
                if include_oracle:
                    expected_lines.append(("oracle", "bounds"))
                for m in methods:
                    expected_lines.append((m, "best"))
                    expected_lines.append((m, "stable"))
                if include_single:
                    expected_lines.append(("single", "bounds"))

                missing = validate_complete(series, noise_axis=noise_axis, expected_lines=expected_lines)
                if missing and not args.allow_incomplete:
                    raise SystemExit(f"Incomplete {modality}-{sweep}-{field}: {missing[:12]}")
                out_path = plot_dir / f"{sweep}_{modality}_{field}.png"
                plot_series(
                    out_path,
                    title=f"OPV2V {modality} {sweep} {label}",
                    series=series,
                    noise_axis=noise_axis,
                    ylabel=label,
                )

        # Only plot combined figure if both modalities are present in this run.
        if "camera" in modalities and "lidar" in modalities:
            for field, label in (("ap30", "AP30"), ("ap50", "AP50"), ("ap70", "AP70")):
                series_by_mod = {
                    "camera": build_series(data, modality="camera", sweep=sweep, field=field),
                    "lidar": build_series(data, modality="lidar", sweep=sweep, field=field),
                }
                out_path = plot_dir / f"{sweep}_combined_{field}.png"
                plot_combined(
                    out_path,
                    title=f"OPV2V combined {sweep} {label}",
                    series_by_modality=series_by_mod,
                    noise_axis=noise_axis,
                    ylabel=label,
                )


if __name__ == "__main__":
    main()
