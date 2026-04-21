#!/usr/bin/env python3
"""Summarize + plot V2V4Real core benchmark curves from merged AP030507 YAMLs.

This mirrors the OPV2V fullbench YAML summarizer style:
- Emit a long-format JSON (entries = one point per noise/method/strategy).
- Generate `plots_yaml/` AP30/AP50/AP70 curves with the same color/linestyle
  conventions used by OPV2V plots.

Input is the V2V4Real core run dir produced by:
  tools/run_v2v4real_core_benchmark.py
which contains a `manifest.json` with `method_specs` + `noise_pairs`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _norm_noise(v: Any) -> str:
    return f"{float(v):.1f}"


def _first_float(v: Any) -> Optional[float]:
    if isinstance(v, list) and v:
        try:
            return float(v[0])
        except Exception:
            return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _safe_get_list(obj: dict, key: str) -> List[Any]:
    v = obj.get(key) or []
    return list(v) if isinstance(v, list) else []


def _first_spec_force_pose_confidence(spec: dict, fallback: Any) -> Optional[float]:
    value = spec.get("force_pose_confidence", fallback)
    return _first_float(value)


def _map_spec_to_method_strategy(spec_name: str, pose_correction: str) -> Tuple[str, str]:
    n = str(spec_name).strip().lower()
    pc = str(pose_correction or "").strip()
    pc_l = pc.lower()
    if n == "none":
        return "baseline", "bounds"
    if n == "single":
        return "single", "bounds"
    if n == "oracle":
        # Keep oracle variants explicit in outputs/plots:
        # - oracle_gt: dataset clean poses, noise disabled -> should be a flat line
        # - v2vloc_oracle_*: pose override from cached clean poses -> may not be flat
        if pc_l.startswith("v2vloc_oracle"):
            return pc, "bounds"
        if pc_l == "oracle_gt":
            return "oracle_gt", "bounds"
        # Fallback: treat as oracle_gt for backward-compat manifests that omit pose_correction.
        return "oracle_gt", "bounds"
    if n.startswith("v2xregpp_"):
        return "v2xregpp", "stable" if "stable" in n else "best"
    if n.startswith("freealign"):
        return "freealign", "stable" if "stable" in n else "best"
    if n.startswith("vips_"):
        return "vips", "stable" if "stable" in n else "best"
    if n.startswith("cbm_"):
        return "cbm", "stable" if "stable" in n else "best"
    # Fallback: keep name as method, treat as best.
    return spec_name, "best"


def _infer_sweep_tag(noise_axis: List[str]) -> str:
    """
    Name the sweep like OPV2V: noise{max}. For example:
      - [0..4]  -> noise4
      - [0..10] -> noise10
    This keeps filenames/JSON consistent when we change the sweep range.
    """
    try:
        mx = max(float(x) for x in noise_axis)
    except Exception:
        return "noise"
    if abs(mx - round(mx)) < 1e-6:
        return f"noise{int(round(mx))}"
    # Fallback: keep a compact float.
    return f"noise{mx:g}"


def _yaml_complete(path: Path, expected_len: int) -> bool:
    if not path.exists():
        return False
    try:
        obj = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore")) or {}
    except Exception:
        return False
    for key in ("ap30", "ap50", "ap70"):
        arr = obj.get(key) or []
        if not isinstance(arr, list) or len(arr) != int(expected_len):
            return False
    return True


def _build_series(entries: List[dict], *, field: str) -> Dict[Tuple[str, str], Dict[str, float]]:
    series: Dict[Tuple[str, str], Dict[str, float]] = {}
    for e in entries:
        method = str(e.get("method"))
        strategy = str(e.get("strategy"))
        noise = _norm_noise(e.get("noise"))
        v = e.get(field)
        if v is None:
            continue
        series.setdefault((method, strategy), {})[noise] = float(v)
    return series


def _validate_complete(
    series: Dict[Tuple[str, str], Dict[str, float]],
    *,
    noise_axis: List[str],
    expected_lines: List[Tuple[str, str]],
) -> List[str]:
    missing: List[str] = []
    for method, strategy in expected_lines:
        pts = series.get((method, strategy))
        if not pts:
            missing.append(f"{method}-{strategy}: missing entire line")
            continue
        for n in noise_axis:
            if pts.get(n) is None:
                missing.append(f"{method}-{strategy}: missing noise {n}")
    return missing


def _gate_sample_consistency(entries: List[dict], *, noise_axis: List[str]) -> List[str]:
    """
    Hard gate for benchmark comparability:
      for each noise point, all non-single lines must report the same `samples`.
    """
    problems: List[str] = []
    for n in noise_axis:
        vals = []
        for e in entries:
            if str(e.get("noise")) != str(n):
                continue
            if str(e.get("method")) == "single":
                continue
            s = e.get("samples")
            if s is None:
                problems.append(f"noise {n}: missing samples for {e.get('method')}-{e.get('strategy')}")
                continue
            try:
                vals.append(int(s))
            except Exception:
                problems.append(f"noise {n}: non-int samples={s!r} for {e.get('method')}-{e.get('strategy')}")
        uniq = sorted(set(vals))
        if len(uniq) > 1:
            problems.append(f"noise {n}: sample_count_mismatch {uniq}")
    return problems


def _gate_nonbounds_applied(entries: List[dict]) -> List[str]:
    """
    No-op gate:
      for each non-bounds method line, pose_provider_applied_count must be >0 at least once.
    """
    max_applied: Dict[Tuple[str, str], float] = {}
    seen_line: set[Tuple[str, str]] = set()
    for e in entries:
        method = str(e.get("method"))
        strategy = str(e.get("strategy"))
        if strategy == "bounds":
            continue
        seen_line.add((method, strategy))
        v = e.get("pose_provider_applied_count")
        if v is None:
            continue
        try:
            fv = float(v)
        except Exception:
            continue
        key = (method, strategy)
        max_applied[key] = max(max_applied.get(key, 0.0), fv)
    problems: List[str] = []
    for method, strategy in sorted(seen_line):
        v = max_applied.get((method, strategy))
        if v is None:
            problems.append(f"{method}-{strategy}: missing pose_provider_applied_count (pose_timing absent?)")
        elif float(v) <= 0.0:
            problems.append(f"{method}-{strategy}: pose_provider_applied_count never >0 (no-op)")
    return problems


def _plot_series(
    out_path: Path,
    *,
    title: str,
    series,
    noise_axis: List[str],
    ylabel: str,
    exclude_methods: Optional[set[str]] = None,
    ylim: Optional[Tuple[float, float]] = None,
) -> None:
    # Keep plot style consistent with tools/summarize_opv2v_fullbench_from_yaml.py.
    import matplotlib.pyplot as plt

    exclude_methods = set(exclude_methods or set())

    color_map = {
        "v2xregpp": "#1f77b4",
        "v2xregpp_occhint": "#0c5da5",
        "freealign": "#ff7f0e",
        "vips": "#2ca02c",
        "cbm": "#d62728",
        "baseline": "#7f7f7f",
        "oracle_gt": "#9467bd",
        # Backward-compat: some older summaries used the generic token.
        "oracle": "#9467bd",
        "single": "#000000",
    }
    style_map = {"best": "-", "stable": "--", "bounds": "-"}

    x_vals = [float(x) for x in noise_axis]
    fig, ax = plt.subplots(figsize=(8.0, 5.0))
    for (method, strategy), points in sorted(series.items()):
        if method in exclude_methods:
            continue
        ys = []
        for n in noise_axis:
            val = points.get(n)
            # Match OPV2V plot convention: single-agent baseline is only recorded at
            # noise=0.0, but we still draw it as a flat line across the sweep axis.
            if val is None and method == "single":
                val = points.get("0.0")
            ys.append(val)
        if all(v is None for v in ys):
            continue
        ax.plot(
            x_vals,
            ys,
            color=color_map.get(method, "#9467bd" if str(method).startswith("v2vloc_oracle") else "#333333"),
            linestyle=style_map.get(strategy, "-"),
            linewidth=1.8,
            label=f"{method}-{strategy}",
        )
    ax.set_xlabel("pos_std (m) / rot_std (deg)")
    ax.set_ylabel(ylabel)
    # Make x-axis limits/ticks explicit for small sweeps (e.g., 0..4) so we don't
    # end up with confusing default ticks like -0.5..4.5 in 0.5 increments.
    if x_vals:
        ax.set_xlim(min(x_vals), max(x_vals))
        ax.set_xticks(x_vals)
    if ylim is not None:
        ax.set_ylim(float(ylim[0]), float(ylim[1]))
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.set_title(title)
    ax.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200)


def main() -> None:
    ap = argparse.ArgumentParser(description="Summarize + plot V2V4Real core benchmark curves.")
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--dataset", type=str, default="V2V4Real", help="Dataset name used in JSON + plot titles.")
    ap.add_argument("--modality", type=str, default="lidar", help="Modality label used in JSON + plot filenames.")
    ap.add_argument("--out-json", type=Path, default=None)
    ap.add_argument("--plot-dir", type=Path, default=None)
    ap.add_argument(
        "--clean-plot-dir",
        action="store_true",
        help="Remove existing *.png in plot_dir before writing new plots (avoids stale noise4/noise10 mix).",
    )
    ap.add_argument("--allow-incomplete", action="store_true")
    args = ap.parse_args()

    run_dir = args.run_dir
    dataset_name = str(args.dataset or "").strip() or "V2V4Real"
    modality_name = str(args.modality or "").strip() or "lidar"
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"Missing manifest.json: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    noise_pairs = manifest.get("noise_pairs") or []
    if not isinstance(noise_pairs, list) or not noise_pairs:
        raise SystemExit("manifest missing noise_pairs")
    noise_axis_full = [_norm_noise(p) for p, _r in noise_pairs]
    expected_len_full = len(noise_axis_full)
    sweep_tag = _infer_sweep_tag(noise_axis_full)

    method_specs = manifest.get("method_specs") or []
    if not isinstance(method_specs, list) or not method_specs:
        raise SystemExit("manifest missing method_specs")
    run_force_pose_confidence = _first_float(manifest.get("force_pose_confidence"))

    entries: List[dict] = []
    expected_lines: List[Tuple[str, str]] = []
    for spec in method_specs:
        spec_name = str(spec.get("name") or "")
        method, strategy = _map_spec_to_method_strategy(spec_name, str(spec.get("pose_correction") or ""))
        spec_force_pose_confidence = _first_spec_force_pose_confidence(spec, run_force_pose_confidence)
        spec_expected_len = int(spec.get("expected_len") or expected_len_full)
        noise_axis = noise_axis_full[:spec_expected_len]
        if spec_expected_len == expected_len_full and method != "single":
            expected_lines.append((method, strategy))
        yaml_path = Path(str(spec.get("final_yaml_path") or ""))
        if not yaml_path.is_absolute():
            yaml_path = (ROOT / yaml_path).resolve()
        if not _yaml_complete(yaml_path, expected_len=spec_expected_len):
            if bool(args.allow_incomplete):
                continue
            raise SystemExit(
                f"Incomplete or missing final YAML: {yaml_path} (expected_len={spec_expected_len})"
            )

        yobj = yaml.safe_load(yaml_path.read_text(encoding="utf-8", errors="ignore")) or {}
        ap30 = _safe_get_list(yobj, "ap30")
        ap50 = _safe_get_list(yobj, "ap50")
        ap70 = _safe_get_list(yobj, "ap70")
        ts = _safe_get_list(yobj, "timing_stats")
        rel = _safe_get_list(yobj, "rel_error_stats")

        for i, noise in enumerate(noise_axis):
            ts_i = ts[i] if i < len(ts) and isinstance(ts[i], dict) else {}
            pt = ts_i.get("pose_timing") if isinstance(ts_i, dict) else None
            pt = pt if isinstance(pt, dict) else {}
            rel_i = rel[i] if i < len(rel) and isinstance(rel[i], dict) else {}
            rel_t = (rel_i.get("rel_trans_m") or {}).get("mean") if isinstance(rel_i, dict) else None
            rel_y = (rel_i.get("rel_yaw_deg") or {}).get("mean") if isinstance(rel_i, dict) else None
            succ2 = (rel_i.get("rel_success_at_m") or {}).get("2") if isinstance(rel_i, dict) else None
            entries.append(
                {
                    "dataset_name": dataset_name,
                    "modality": modality_name,
                    "sweep": sweep_tag,
                    "method": method,
                    "strategy": strategy,
                    "noise": noise,
                    "ap30": float(ap30[i]) if i < len(ap30) and ap30[i] is not None else None,
                    "ap50": float(ap50[i]) if i < len(ap50) and ap50[i] is not None else None,
                    "ap70": float(ap70[i]) if i < len(ap70) and ap70[i] is not None else None,
                    "infer_fps": _first_float(ts_i.get("infer_fps")) if isinstance(ts_i, dict) else None,
                    "infer_sec": _first_float(ts_i.get("infer_sec")) if isinstance(ts_i, dict) else None,
                    "pose_fps": _first_float(ts_i.get("pose_fps")) if isinstance(ts_i, dict) else None,
                    "pose_sec": _first_float(ts_i.get("pose_sec")) if isinstance(ts_i, dict) else None,
                    "samples": ts_i.get("samples") if isinstance(ts_i, dict) else None,
                    "pose_provider_applied_count": pt.get("pose_provider_applied_count"),
                    "pose_provider_total_sec": pt.get("pose_provider_total_sec"),
                    "pose_match_sec": pt.get("match_sec"),
                    "pose_solver_sec": pt.get("solver_sec"),
                    # Optional pose-correction reason breakdown (stage1 correctors: freealign/vips/cbm).
                    "pose_corr_pair_total_count": pt.get("pose_corr_pair_total_count"),
                    "pose_corr_applied_pair_count": pt.get("pose_corr_applied_pair_count"),
                    "pose_corr_skip_empty_boxes_count": pt.get("pose_corr_skip_empty_boxes_count"),
                    "pose_corr_skip_no_matches_count": pt.get("pose_corr_skip_no_matches_count"),
                    "pose_corr_skip_svd_failed_count": pt.get("pose_corr_skip_svd_failed_count"),
                    "pose_corr_skip_compare_gate_count": pt.get("pose_corr_skip_compare_gate_count"),
                    "pose_corr_skip_exception_count": pt.get("pose_corr_skip_exception_count"),
                    "pose_corr_skip_other_count": pt.get("pose_corr_skip_other_count"),
                    "force_pose_confidence": spec_force_pose_confidence,
                    "mean_rel_trans_m": float(rel_t) if rel_t is not None else None,
                    "mean_rel_yaw_deg": float(rel_y) if rel_y is not None else None,
                    "success_at_2m": float(succ2) if succ2 is not None else None,
                    "source_yaml": str(yaml_path),
                }
            )

    out_json = args.out_json or (run_dir / "results_ap50_from_yaml.json")
    out_json.write_text(
        json.dumps(
            {
                "run_id": str(manifest.get("tag") or run_dir.name),
                "dataset": dataset_name,
                "dataset_name": dataset_name,
                "force_pose_confidence": run_force_pose_confidence,
                "model_dir": str(manifest.get("method_specs", [{}])[0].get("final_yaml_path", "")),
                "entries": entries,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    plot_dir = args.plot_dir or (run_dir / "plots_yaml")
    plot_dir.mkdir(parents=True, exist_ok=True)
    if bool(args.clean_plot_dir):
        for p in plot_dir.glob("*.png"):
            try:
                p.unlink()
            except Exception:
                pass
    expected_lines = sorted(set(expected_lines), key=lambda x: (x[0], x[1]))

    # Comparability gates (skip only when explicitly allow-incomplete).
    if not bool(args.allow_incomplete):
        sample_problems = _gate_sample_consistency(entries, noise_axis=noise_axis_full)
        applied_problems = _gate_nonbounds_applied(entries)
        if sample_problems:
            raise SystemExit(f"Sample consistency gate failed: {sample_problems[:12]}")
        if applied_problems:
            raise SystemExit(f"No-op gate failed: {applied_problems[:12]}")

    for field, label in (("ap30", "AP30"), ("ap50", "AP50"), ("ap70", "AP70")):
        series = _build_series(entries, field=field)
        missing = _validate_complete(series, noise_axis=noise_axis_full, expected_lines=expected_lines)
        if missing and not bool(args.allow_incomplete):
            raise SystemExit(f"Incomplete V2V4Real curves for {field}: {missing[:12]}")
        out_path = plot_dir / f"{sweep_tag}_{modality_name}_{field}.png"
        _plot_series(
            out_path,
            title=f"{dataset_name} {modality_name} {sweep_tag} {label}",
            series=series,
            noise_axis=noise_axis_full,
            ylabel=label,
            # Keep AP plots comparable to OPV2V/DAIR by using a fixed [0, 1] range.
            ylim=(0.0, 1.0),
        )

        # Extra readability plot: exclude the single-agent baseline so the y-range
        # focuses on the cooperative methods (single is a flat reference line).
        vals = []
        for (method, _strategy), points in series.items():
            if method == "single":
                continue
            for n in noise_axis_full:
                v = points.get(n)
                if v is not None:
                    vals.append(float(v))
        if vals:
            y0, y1 = min(vals), max(vals)
            margin = max(0.005, 0.02 * (y1 - y0))
            out_path_core = plot_dir / f"{sweep_tag}_{modality_name}_{field}_core.png"
            _plot_series(
                out_path_core,
                title=f"{dataset_name} {modality_name} {sweep_tag} {label} (core zoom)",
                series=series,
                noise_axis=noise_axis_full,
                ylabel=label,
                exclude_methods={"single"},
                ylim=(y0 - margin, y1 + margin),
            )

    print("run_dir:", run_dir)
    print("out_json:", out_json)
    print("plots:", plot_dir)


if __name__ == "__main__":
    main()
