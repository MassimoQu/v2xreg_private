#!/usr/bin/env python3
"""
Generate a unified `summary.md` for an OPV2V fullbench run directory.

Constraints (by design):
- Do NOT rerun evaluation. Only read:
  - results_ap50_from_yaml.json (source-of-truth metrics for this summary)
  - config_snapshot.json (run configuration recorded by the scheduler)
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]
HEAL = ROOT / "HEAL"

Key = Tuple[str, str, str, str]  # modality, sweep, method, strategy


def _read_json(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"Expected dict in {path}, got {type(obj)}")
    return obj


def _as_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [x.strip() for x in v.split(",") if x.strip()]
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [str(v).strip()] if str(v).strip() else []


def _normalize_noise(v: Any) -> str:
    try:
        return f"{float(v):.1f}"
    except Exception:
        return str(v)


def _mean(xs: Iterable[float]) -> Optional[float]:
    xs = list(xs)
    if not xs:
        return None
    return float(mean(xs))


def _fmt(v: Optional[float], *, nd: int) -> str:
    if v is None:
        return "NA"
    return f"{float(v):.{nd}f}"


def _fmt_list(vals: List[Any]) -> str:
    return ",".join(str(x) for x in vals)


def _maybe_rel(path_str: str, base: Path) -> Optional[str]:
    if not path_str:
        return None
    p = Path(path_str)
    try:
        rp = p.resolve()
    except Exception:
        rp = p
    try:
        return str(rp.relative_to(base.resolve()))
    except Exception:
        return None


def _pick_path_repr(path_str: str, *, prefer_rel_to: Optional[Path]) -> Tuple[str, Optional[str]]:
    """
    Returns (repr_str, note) where note is e.g. "relative to HEAL"/"relative to ROOT".
    """
    if not path_str:
        return ("", None)
    if prefer_rel_to is not None:
        rel = _maybe_rel(path_str, prefer_rel_to)
        if rel is not None:
            note = "relative to HEAL" if prefer_rel_to == HEAL else "relative to ROOT"
            return (rel, note)
    return (path_str, None)


def _group_entries(entries: List[dict]) -> Dict[Key, List[dict]]:
    grouped: Dict[Key, List[dict]] = defaultdict(list)
    for e in entries:
        mod = str(e.get("modality") or "").strip()
        sweep = str(e.get("sweep") or "").strip()
        method = str(e.get("method") or "").strip()
        strategy = str(e.get("strategy") or "").strip()
        if not (mod and sweep and method and strategy):
            continue
        grouped[(mod, sweep, method, strategy)].append(e)
    return grouped


def _compute_group_mean(
    pts: List[dict],
    *,
    expected_noise_axis: List[str],
) -> dict:
    # Metrics are already per-(noise point) in results_ap50_from_yaml.json.
    ap50_vals = [float(x["ap50"]) for x in pts if x.get("ap50") is not None]
    rel_t_vals = [float(x["mean_rel_trans_m"]) for x in pts if x.get("mean_rel_trans_m") is not None]
    rel_y_vals = [float(x["mean_rel_yaw_deg"]) for x in pts if x.get("mean_rel_yaw_deg") is not None]
    applied_vals = [float(x["pose_provider_applied_count"]) for x in pts if x.get("pose_provider_applied_count") is not None]

    present_noise = sorted({_normalize_noise(x.get("noise")) for x in pts}, key=lambda s: float(s) if s.replace(".", "", 1).isdigit() else s)  # type: ignore[arg-type]
    expected_set = {_normalize_noise(x) for x in expected_noise_axis}
    missing_noise = sorted(list(expected_set - set(present_noise)), key=lambda s: float(s) if s.replace(".", "", 1).isdigit() else s)

    return {
        "n_points": len(present_noise),
        "present_noise": present_noise,
        "missing_noise": missing_noise,
        "mean_ap50": _mean(ap50_vals),
        "mean_rel_trans_m": _mean(rel_t_vals),
        "mean_rel_yaw_deg": _mean(rel_y_vals),
        "mean_pose_provider_applied_count": _mean(applied_vals),
        "rel_pose_stats_missing": (len(rel_t_vals) == 0 and len(rel_y_vals) == 0),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Create summary.md for an OPV2V fullbench run_dir (no rerun).")
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=None, help="Output path (default: <run_dir>/summary.md).")
    args = ap.parse_args()

    run_dir = args.run_dir
    cfg_path = run_dir / "config_snapshot.json"
    results_path = run_dir / "results_ap50_from_yaml.json"

    cfg = _read_json(cfg_path)
    results = _read_json(results_path)
    entries = results.get("entries") or []
    if not isinstance(entries, list):
        raise ValueError(f"Expected list in {results_path}['entries'], got {type(entries)}")

    run_id = str(cfg.get("run_id") or results.get("run_id") or run_dir.name).strip()
    comm_range = cfg.get("comm_range_override")
    comm_range_gating = cfg.get("comm_range_gating")

    # Noise axis (unified naming to match DAIR/V2V4Real core summaries).
    pos_std_list = [_normalize_noise(x) for x in _as_list(cfg.get("noise_list"))]
    rot_std_list = [_normalize_noise(x) for x in _as_list(cfg.get("rot_list"))]
    expected_noise_axis = pos_std_list or sorted({_normalize_noise(e.get("noise")) for e in entries})

    modalities = _as_list(cfg.get("modalities")) or sorted({str(e.get("modality")) for e in entries if e.get("modality")})
    sweeps = _as_list(cfg.get("sweeps")) or sorted({str(e.get("sweep")) for e in entries if e.get("sweep")})

    camera_model = str(cfg.get("camera_model") or "").strip()
    lidar_model = str(cfg.get("lidar_model") or "").strip()
    camera_stage1 = str(cfg.get("camera_stage1") or "").strip()
    lidar_stage1 = str(cfg.get("lidar_stage1") or "").strip()

    out_path = args.out or (run_dir / "summary.md")

    grouped = _group_entries(entries)

    # Precompute means per group.
    mean_by_key: Dict[Key, dict] = {}
    for key, pts in grouped.items():
        _mod, _sweep, method, _strategy = key
        if method == "single":
            axis = ["0.0"]
        else:
            axis = expected_noise_axis
        mean_by_key[key] = _compute_group_mean(pts, expected_noise_axis=axis)

    # Build Markdown.
    lines: List[str] = []
    lines.append("# OPV2V Fullbench Benchmark Summary")
    lines.append("")
    lines.append(f"- tag: `{run_id}`")
    lines.append(f"- out_dir: `{run_dir.resolve()}`")

    cam_model_repr, cam_model_note = _pick_path_repr(camera_model, prefer_rel_to=HEAL)
    lidar_model_repr, lidar_model_note = _pick_path_repr(lidar_model, prefer_rel_to=HEAL)
    model_dir_map: Dict[str, str] = {}
    if cam_model_repr:
        model_dir_map["camera"] = cam_model_repr
    if lidar_model_repr:
        model_dir_map["lidar"] = lidar_model_repr
    model_dir_note = cam_model_note if cam_model_note and cam_model_note == lidar_model_note else None
    if model_dir_map:
        suffix = f" ({model_dir_note})" if model_dir_note else ""
        lines.append(f"- model_dir: `{json.dumps(model_dir_map, sort_keys=True)}`{suffix}")

    cam_s1_repr, cam_s1_note = _pick_path_repr(camera_stage1, prefer_rel_to=ROOT)
    lidar_s1_repr, lidar_s1_note = _pick_path_repr(lidar_stage1, prefer_rel_to=ROOT)
    stage1_map: Dict[str, str] = {}
    if cam_s1_repr:
        stage1_map["camera"] = cam_s1_repr
    if lidar_s1_repr:
        stage1_map["lidar"] = lidar_s1_repr
    stage1_note = cam_s1_note if cam_s1_note and cam_s1_note == lidar_s1_note else None
    if stage1_map:
        suffix = f" ({stage1_note})" if stage1_note else ""
        lines.append(f"- stage1_result: `{json.dumps(stage1_map, sort_keys=True)}`{suffix}")

    if comm_range is not None:
        lines.append(f"- comm_range: `{comm_range}`")
    if comm_range_gating is not None:
        lines.append(f"- gating: `{comm_range_gating}`")
    if cfg.get("noise_target") is not None:
        lines.append(f"- noise_target: `{cfg.get('noise_target')}`")
    if pos_std_list:
        lines.append(f"- pos_std_list: `{_fmt_list(pos_std_list)}`")
    if rot_std_list:
        lines.append(f"- rot_std_list: `{_fmt_list(rot_std_list)}`")
    if modalities:
        lines.append(f"- modalities: `{_fmt_list(modalities)}`")
    if sweeps:
        lines.append(f"- sweeps: `{_fmt_list(sweeps)}`")
    if cfg.get("include_dropout") is not None:
        lines.append(f"- include_dropout: `{bool(cfg.get('include_dropout'))}`")
    if cfg.get("dropout") is not None:
        lines.append(f"- dropout: `{cfg.get('dropout')}`")
    if cfg.get("sweep_mode") is not None:
        lines.append(f"- sweep_mode: `{cfg.get('sweep_mode')}`")
    if cfg.get("max_per_gpu") is not None:
        lines.append(f"- max_per_gpu: `{int(cfg.get('max_per_gpu'))}`")

    lines.append("")
    lines.append("## Sources of Truth (for reproducibility)")
    lines.append("")
    lines.append(f"- run_state: `{(run_dir / 'run_state.jsonl').resolve()}`")
    lines.append(f"- results_json: `{results_path.resolve()}`")
    lines.append(f"- plots_dir: `{(run_dir / 'plots_yaml').resolve()}`")
    lines.append(f"- config_snapshot: `{cfg_path.resolve()}`")
    lines.append(f"- logs_dir: `{(run_dir / 'logs').resolve()}`")
    if (run_dir / "task_summary_final.json").exists():
        lines.append(f"- task_summary_final: `{(run_dir / 'task_summary_final.json').resolve()}`")

    lines.append("")
    lines.append("## Results (mean AP50)")
    lines.append("")
    lines.append(f"- Means are arithmetic means over noise points in `config_snapshot.json` (pos_std_list/rot_std_list).")
    lines.append("")

    # Emit one table per (modality, sweep) to avoid mixing AP scales.
    for sweep in sweeps:
        for modality in modalities:
            keys = [k for k in mean_by_key.keys() if k[0] == modality and k[1] == sweep]
            if not keys:
                continue
            lines.append(f"### {modality} / {sweep}")
            lines.append("")
            lines.append("| method | mean_ap50 | mean_rel_trans_m | mean_rel_yaw_deg | mean_pose_provider_applied_count |")
            lines.append("|---|---:|---:|---:|---:|")
            rows = []
            for (_m, _s, method, strategy) in keys:
                stats = mean_by_key[(_m, _s, method, strategy)]
                method_tag = f"{method}-{strategy}"
                rows.append(
                    (
                        method_tag,
                        stats.get("mean_ap50"),
                        stats.get("mean_rel_trans_m"),
                        stats.get("mean_rel_yaw_deg"),
                        stats.get("mean_pose_provider_applied_count"),
                    )
                )
            rows = sorted(rows, key=lambda r: r[0])
            for method_tag, ap50, rt, ry, applied in rows:
                lines.append(
                    "| {} | {} | {} | {} | {} |".format(
                        method_tag,
                        _fmt(ap50, nd=6),
                        _fmt(rt, nd=3),
                        _fmt(ry, nd=3),
                        _fmt(applied, nd=1),
                    )
                )
            lines.append("")

    # Missing field explanation (explicit, evidence-first).
    missing_rel_rows: List[str] = []
    incomplete_rows: List[str] = []
    for (modality, sweep, method, strategy), stats in sorted(mean_by_key.items()):
        method_tag = f"{method}-{strategy}"
        if stats.get("rel_pose_stats_missing"):
            missing_rel_rows.append(f"- {modality}/{sweep}/{method_tag}: rel pose stats are NA (null in `{results_path.name}`).")
        if stats.get("missing_noise"):
            incomplete_rows.append(
                f"- {modality}/{sweep}/{method_tag}: missing noise points {stats.get('missing_noise')} (present={stats.get('present_noise')})."
            )

    if missing_rel_rows or incomplete_rows:
        lines.append("## Missing / Incomplete Fields")
        lines.append("")
        if missing_rel_rows:
            lines.append("- rel pose stats (mean_rel_trans_m/mean_rel_yaw_deg):")
            lines.extend(missing_rel_rows)
            lines.append("")
        if incomplete_rows:
            lines.append("- noise-axis coverage:")
            lines.extend(incomplete_rows)
            lines.append("")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
