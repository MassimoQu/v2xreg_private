#!/usr/bin/env python3
"""Build full-matrix AP+registration benchmark tables/plots across DAIR and OPV2V.

This script unifies method lines by fixed noise axis (1..10) and emits:
- long-format CSV for traceability
- method registry with init/no-init tags and completeness status
- AP50 / registration curve plots in the same style used by no-init AP reviews
"""

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DAIR_JSONL = ROOT / "outputs" / "pose_sweep_1to10_full_gpuvoxel20260218_results.jsonl"
DEFAULT_OPV2V_RUN_DIR = ROOT / "outputs" / "full_bench_opv2v_autopilot_full_20260216_auto3_a1"

NOISE_AXIS = ["%.1f" % float(i) for i in range(1, 11)]

METHOD_FAMILY = {
    "baseline": "bound",
    "oracle": "bound",
    "single": "bound",
    "v2xregpp": "v2xregpp",
    "v2xregpp_occhint": "v2xregpp",
    "freealign": "freealign",
    "vips": "vips",
    "vips_prior": "vips",
    "cbm": "cbm",
    "cbm_prior": "cbm",
    "imagematch_noinit": "imagematch",
    "imagematch_current": "imagematch",
    "lidarreg_ransac": "hkust_like",
    "hkust_teaser": "hkust",
    "hkust_fgr": "hkust",
    "hkust_quatro": "hkust",
}

METHOD_INIT_CLASS = {
    "baseline": "bound",
    "oracle": "bound",
    "single": "bound",
    "vips_prior": "with_init",
    "cbm_prior": "with_init",
    "imagematch_current": "with_init",
    "vips": "no_init",
    "cbm": "no_init",
    "v2xregpp": "no_init",
    "freealign": "no_init",
    "v2xregpp_occhint": "no_init",
    "imagematch_noinit": "no_init",
    "lidarreg_ransac": "no_init_hkust_like",
    "hkust_teaser": "no_init_hkust",
    "hkust_fgr": "no_init_hkust",
    "hkust_quatro": "no_init_hkust",
}

COLOR_FAMILY = {
    "v2xregpp": "#1f77b4",
    "freealign": "#ff7f0e",
    "vips": "#2ca02c",
    "cbm": "#d62728",
    "imagematch": "#17becf",
    "hkust": "#8c564b",
    "hkust_like": "#bcbd22",
    "bound": "#7f7f7f",
    "other": "#444444",
}

LINESTYLE_STRATEGY = {
    "best": "-",
    "stable": "--",
    "bounds": "-.",
}

MARKER_INIT = {
    "with_init": "s",
    "no_init": "o",
    "no_init_hkust": "^",
    "no_init_hkust_like": "v",
    "bound": "x",
    "unknown": "D",
}


def _norm_noise(v):
    return "%.1f" % float(v)


def _mean(values):
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None
    return float(sum(vals) / float(len(vals)))


def _method_family(method):
    return METHOD_FAMILY.get(str(method), "other")


def _method_init_class(method):
    return METHOD_INIT_CLASS.get(str(method), "unknown")


def _load_jsonl(path):
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _write_csv(path, rows, header):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _parse_dair_curves(dair_jsonl):
    out = []
    rows = _load_jsonl(dair_jsonl)
    for row in rows:
        yaml_path = Path(row.get("yaml_path") or "")
        if not yaml_path.is_absolute():
            yaml_path = ROOT / yaml_path
        if not yaml_path.exists():
            continue
        try:
            yobj = yaml.safe_load(yaml_path.read_text(encoding="utf-8", errors="ignore")) or {}
        except Exception:
            continue

        ap30 = yobj.get("ap30") or []
        ap50 = yobj.get("ap50") or []
        ap70 = yobj.get("ap70") or []
        rel = yobj.get("rel_error_stats") or []

        for i, noise in enumerate(NOISE_AXIS):
            if i >= len(ap50):
                break
            rel_i = rel[i] if i < len(rel) and isinstance(rel[i], dict) else {}
            rel_t = (rel_i.get("rel_trans_m") or {}).get("mean") if isinstance(rel_i, dict) else None
            rel_y = (rel_i.get("rel_yaw_deg") or {}).get("mean") if isinstance(rel_i, dict) else None
            succ2 = (rel_i.get("rel_success_at_m") or {}).get("2") if isinstance(rel_i, dict) else None
            method = str(row.get("method"))
            out.append(
                {
                    "dataset": "DAIR-V2X",
                    "suite": "noise10",
                    "modality": str(row.get("modality")),
                    "method": method,
                    "strategy": str(row.get("strategy")),
                    "noise": noise,
                    "method_family": _method_family(method),
                    "method_init_class": _method_init_class(method),
                    "ap30": float(ap30[i]) if i < len(ap30) else None,
                    "ap50": float(ap50[i]) if i < len(ap50) else None,
                    "ap70": float(ap70[i]) if i < len(ap70) else None,
                    "mean_rel_trans_m": float(rel_t) if rel_t is not None else None,
                    "mean_rel_yaw_deg": float(rel_y) if rel_y is not None else None,
                    "success_at_2m": float(succ2) if succ2 is not None else None,
                    "source": str(yaml_path.relative_to(ROOT)),
                }
            )
    return out


def _parse_opv2v_filename(path, run_id):
    stem = path.stem
    marker = "_%s_" % run_id
    pos = stem.find(marker)
    if pos < 0 or not stem.startswith("AP030507_"):
        return None
    remainder = stem[pos + len(marker) :]

    m = re.match(r"^(camera|lidar)_(noise10|drop20)_single$", remainder)
    if m:
        mod, sweep = m.groups()
        return (mod, sweep, "single", "bounds", "0.0")

    m = re.match(r"^(camera|lidar)_(noise10|drop20)_(baseline|oracle)_n([0-9.]+)$", remainder)
    if m:
        mod, sweep, method, noise = m.groups()
        return (mod, sweep, method, "bounds", _norm_noise(noise))

    m = re.match(r"^(camera|lidar)_(noise10|drop20)_([a-z0-9_]+)_(best|stable)_n([0-9.]+)$", remainder)
    if m:
        mod, sweep, method, strategy, noise = m.groups()
        return (mod, sweep, method, strategy, _norm_noise(noise))

    return None


def _parse_opv2v_rel_stats(run_dir, run_id):
    cfg = json.loads((run_dir / "config_snapshot.json").read_text(encoding="utf-8"))
    model_dirs = [Path(cfg["camera_model"]), Path(cfg["lidar_model"])]

    rel_map = {}
    for model_dir in model_dirs:
        if not model_dir.exists():
            continue
        for path in sorted(model_dir.glob("AP030507_*.yaml")):
            key = _parse_opv2v_filename(path, run_id=run_id)
            if key is None:
                continue
            try:
                obj = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
            rel_stats = obj.get("rel_error_stats") or []
            if not isinstance(rel_stats, list) or not rel_stats:
                continue
            entry0 = rel_stats[0] if isinstance(rel_stats[0], dict) else {}
            rel_t = (entry0.get("rel_trans_m") or {}).get("mean") if isinstance(entry0, dict) else None
            rel_y = (entry0.get("rel_yaw_deg") or {}).get("mean") if isinstance(entry0, dict) else None
            succ2 = (entry0.get("rel_success_at_m") or {}).get("2") if isinstance(entry0, dict) else None

            # Pose provider effectiveness / timing (optional, schema changed over time).
            pose_applied = None
            match_sec = None
            pose_provider_total_sec = None
            ts_list = obj.get("timing_stats") or []
            ts0 = ts_list[0] if isinstance(ts_list, list) and ts_list else {}
            if isinstance(ts0, dict):
                pt = ts0.get("pose_timing")
                if isinstance(pt, dict):
                    pose_applied = pt.get("pose_provider_applied_count")
                    match_sec = pt.get("match_sec")
                    pose_provider_total_sec = pt.get("pose_provider_total_sec")
                ps = ts0.get("pose_solver")
                if isinstance(ps, dict) and pose_applied is None:
                    pose_applied = ps.get("applied")
            rec = {
                "mean_rel_trans_m": float(rel_t) if rel_t is not None else None,
                "mean_rel_yaw_deg": float(rel_y) if rel_y is not None else None,
                "success_at_2m": float(succ2) if succ2 is not None else None,
                "pose_applied_count": float(pose_applied) if pose_applied is not None else None,
                "pose_match_sec": float(match_sec) if match_sec is not None else None,
                "pose_provider_total_sec": float(pose_provider_total_sec) if pose_provider_total_sec is not None else None,
                "source": str(path.relative_to(ROOT)),
                "mtime": path.stat().st_mtime,
            }
            old = rel_map.get(key)
            if old is None or rec["mtime"] >= old.get("mtime", -1):
                rel_map[key] = rec

    for v in rel_map.values():
        v.pop("mtime", None)
    return rel_map


def _parse_opv2v_curves(run_dir):
    obj = json.loads((run_dir / "results_ap50_from_yaml.json").read_text(encoding="utf-8"))
    entries = obj.get("entries") or []
    run_id = obj.get("run_id")
    if not run_id:
        name = run_dir.name
        run_id = name[len("full_bench_") :] if name.startswith("full_bench_") else name
    rel_map = _parse_opv2v_rel_stats(run_dir, run_id=run_id)

    out = []
    for e in entries:
        noise = _norm_noise(e.get("noise"))
        method = str(e.get("method"))
        strategy = str(e.get("strategy"))
        key = (
            str(e.get("modality")),
            str(e.get("sweep")),
            method,
            strategy,
            noise,
        )
        rel = rel_map.get(key) or {}
        out.append(
            {
                "dataset": "OPV2V",
                "suite": str(e.get("sweep")),
                "modality": str(e.get("modality")),
                "method": method,
                "strategy": strategy,
                "noise": noise,
                "method_family": _method_family(method),
                "method_init_class": _method_init_class(method),
                "ap30": float(e.get("ap30")) if e.get("ap30") is not None else None,
                "ap50": float(e.get("ap50")) if e.get("ap50") is not None else None,
                "ap70": float(e.get("ap70")) if e.get("ap70") is not None else None,
                "mean_rel_trans_m": rel.get("mean_rel_trans_m"),
                "mean_rel_yaw_deg": rel.get("mean_rel_yaw_deg"),
                "success_at_2m": rel.get("success_at_2m"),
                "pose_applied_count": rel.get("pose_applied_count"),
                "pose_match_sec": rel.get("pose_match_sec"),
                "pose_provider_total_sec": rel.get("pose_provider_total_sec"),
                "source": rel.get("source") or str((run_dir / "results_ap50_from_yaml.json").relative_to(ROOT)),
            }
        )
    return out


def _line_status(records):
    by = defaultdict(list)
    for r in records:
        key = (
            r["dataset"],
            r["suite"],
            r["modality"],
            r["method"],
            r["strategy"],
        )
        by[key].append(r)

    rows = []
    for key, vals in sorted(by.items()):
        dataset, suite, modality, method, strategy = key
        noises = sorted({_norm_noise(v["noise"]) for v in vals})
        expect = ["0.0"] if method == "single" else list(NOISE_AXIS)
        missing = [n for n in expect if n not in noises]
        ap50 = [v.get("ap50") for v in vals]
        rel_t = [v.get("mean_rel_trans_m") for v in vals]
        applied = [v.get("pose_applied_count") for v in vals]
        ap50_mean = _mean(ap50)
        rel_t_mean = _mean(rel_t)
        applied_mean = _mean(applied)

        status = "valid" if not missing else "incomplete"
        if not missing and method not in {"baseline", "oracle", "single"}:
            if applied_mean is None:
                status = "unknown_applied"
            else:
                # Many pose-correction methods should have non-zero applied_count;
                # if the whole curve is 0 it is effectively a no-op (often wiring bug).
                applied_vals = [float(v) for v in applied if v is not None]
                if applied_vals and all(v == 0.0 for v in applied_vals):
                    status = "noop"
        rows.append(
            {
                "dataset": dataset,
                "suite": suite,
                "modality": modality,
                "method": method,
                "strategy": strategy,
                "method_family": _method_family(method),
                "method_init_class": _method_init_class(method),
                "num_points": len(noises),
                "expected_points": len(expect),
                "missing_points": "|".join(missing),
                "status": status,
                "mean_ap50": ap50_mean,
                "mean_rel_trans_m": rel_t_mean,
                "mean_pose_applied_count": applied_mean,
            }
        )
    return rows


def _plot_curves(records, out_dir):
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    grouped = defaultdict(list)
    for r in records:
        key = (r["dataset"], r["suite"], r["modality"])
        grouped[key].append(r)

    for (dataset, suite, modality), vals in sorted(grouped.items()):
        for metric, ylabel in (
            ("ap50", "AP50"),
            ("mean_rel_trans_m", "Rel Trans (m)"),
            ("mean_rel_yaw_deg", "Rel Yaw (deg)"),
        ):
            by_line = defaultdict(dict)
            by_line_applied = defaultdict(dict)
            line_meta = {}
            for r in vals:
                method = r["method"]
                strategy = r["strategy"]
                noise = _norm_noise(r["noise"])
                v = r.get(metric)
                if v is None or (isinstance(v, float) and math.isnan(v)):
                    continue
                k = (method, strategy)
                by_line[k][noise] = float(v)
                line_meta[k] = (r.get("method_family"), r.get("method_init_class"))
                a = r.get("pose_applied_count")
                if a is not None:
                    try:
                        by_line_applied[k][noise] = float(a)
                    except Exception:
                        pass

            if not by_line:
                continue

            def _should_include_filtered(method, strategy):
                if method in {"baseline", "oracle", "single"}:
                    return True
                pts = by_line_applied.get((method, strategy)) or {}
                if not pts:
                    # No applied-count signal (older YAML schema). Keep it in the filtered plot,
                    # but registry will mark it as unknown_applied.
                    return True
                vals = [float(v) for v in pts.values() if v is not None]
                return bool(vals) and any(v > 0.0 for v in vals)

            def _plot(*, out_path, title_suffix, include_filtered):
                fig, ax = plt.subplots(figsize=(9.2, 5.6))
                x_vals = [float(x) for x in NOISE_AXIS]
                for (method, strategy), points in sorted(by_line.items()):
                    if include_filtered and not _should_include_filtered(method, strategy):
                        continue
                    family, init_class = line_meta.get((method, strategy), ("other", "unknown"))
                    ys = [points.get(n) for n in NOISE_AXIS]
                    if all(v is None for v in ys):
                        continue
                    ax.plot(
                        x_vals,
                        ys,
                        color=COLOR_FAMILY.get(family, "#444444"),
                        linestyle=LINESTYLE_STRATEGY.get(strategy, "-"),
                        marker=MARKER_INIT.get(init_class, "o"),
                        markersize=3.8,
                        linewidth=1.6,
                        label="%s-%s" % (method, strategy),
                    )

                ax.set_xlabel("pos_std (m) / rot_std (deg)")
                ax.set_ylabel(ylabel)
                ax.set_title("%s %s %s %s%s" % (dataset, suite, modality, ylabel, title_suffix))
                ax.grid(True, linestyle="--", alpha=0.35)

                family_handles = [
                    Line2D([0], [0], color=v, linestyle="-", linewidth=2.0, label=k)
                    for k, v in sorted(COLOR_FAMILY.items())
                    if k in {meta[0] for meta in line_meta.values()}
                ]
                if family_handles:
                    leg1 = ax.legend(handles=family_handles, title="Family", fontsize=8, loc="upper right")
                    ax.add_artist(leg1)

                style_handles = [
                    Line2D([0], [0], color="black", linestyle="-", label="best"),
                    Line2D([0], [0], color="black", linestyle="--", label="stable"),
                    Line2D([0], [0], color="black", linestyle="-.", label="bounds"),
                ]
                leg2 = ax.legend(handles=style_handles, title="Strategy", fontsize=8, loc="lower left")
                ax.add_artist(leg2)

                init_handles = [
                    Line2D([0], [0], color="black", marker=v, linestyle="None", label=k)
                    for k, v in sorted(MARKER_INIT.items())
                    if k in {meta[1] for meta in line_meta.values()}
                ]
                ax.legend(handles=init_handles, title="Init Class", fontsize=8, loc="lower right")

                out_path.parent.mkdir(parents=True, exist_ok=True)
                fig.tight_layout()
                fig.savefig(out_path, dpi=220)
                plt.close(fig)

            # Default plots: filtered to only include methods that actually apply pose updates.
            out_path = out_dir / "plots" / ("%s_%s_%s_%s.png" % (dataset.lower(), suite, modality, metric))
            _plot(out_path=out_path, title_suffix=" (effective-only)", include_filtered=True)

            # Extra plots: include all lines for forensic comparison.
            out_path_all = out_dir / "plots" / ("%s_%s_%s_%s_all.png" % (dataset.lower(), suite, modality, metric))
            _plot(out_path=out_path_all, title_suffix=" (all)", include_filtered=False)


def parse_args():
    p = argparse.ArgumentParser(description="Build full-matrix benchmark report (DAIR + OPV2V).")
    p.add_argument("--dair-jsonl", type=Path, default=DEFAULT_DAIR_JSONL)
    p.add_argument("--opv2v-run-dir", type=Path, default=DEFAULT_OPV2V_RUN_DIR)
    p.add_argument("--out-dir", type=Path, default=ROOT / "outputs" / "benchmark_fullmatrix_20260220")
    p.add_argument("--skip-plots", action="store_true", help="Only write CSV/JSON artifacts.")
    return p.parse_args()


def main():
    args = parse_args()

    dair_rows = _parse_dair_curves(args.dair_jsonl)
    opv2v_rows = _parse_opv2v_curves(args.opv2v_run_dir)
    combined = dair_rows + opv2v_rows

    if not combined:
        raise SystemExit("No benchmark rows found.")

    registry = _line_status(combined)

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    _write_csv(
        out_dir / "combined_noise_curve_long.csv",
        combined,
        header=[
            "dataset",
            "suite",
            "modality",
            "method",
            "strategy",
            "noise",
            "method_family",
            "method_init_class",
            "ap30",
            "ap50",
            "ap70",
            "mean_rel_trans_m",
            "mean_rel_yaw_deg",
            "success_at_2m",
            "pose_applied_count",
            "pose_match_sec",
            "pose_provider_total_sec",
            "source",
        ],
    )

    _write_csv(
        out_dir / "method_registry.csv",
        registry,
        header=[
            "dataset",
            "suite",
            "modality",
            "method",
            "strategy",
            "method_family",
            "method_init_class",
            "num_points",
            "expected_points",
            "missing_points",
            "status",
            "mean_ap50",
            "mean_rel_trans_m",
            "mean_pose_applied_count",
        ],
    )

    if not bool(args.skip_plots):
        _plot_curves(combined, out_dir)

    try:
        out_dir_disp = str(out_dir.resolve().relative_to(ROOT))
    except Exception:
        out_dir_disp = str(out_dir)

    summary = {
        "out_dir": out_dir_disp,
        "rows_combined": len(combined),
        "rows_registry": len(registry),
        "valid_lines": sum(1 for r in registry if r["status"] == "valid"),
        "incomplete_lines": sum(1 for r in registry if r["status"] != "valid"),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
