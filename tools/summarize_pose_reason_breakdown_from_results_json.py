#!/usr/bin/env python3
"""
Summarize pose-correction failure reasons from `results_ap50_from_yaml.json`.

Why this exists:
  - For stage-1 box-based correctors (freealign/vips/cbm), we need an evidence chain
    explaining *why* a method line looks like a no-op / low recall.
  - Online runtime now records per-sample reason counters (pose_corr_*_count) into
    `pose_timing`, which gets aggregated into `results_ap50_from_yaml.json`.
  - This tool turns those fields into a human-readable markdown report.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple


REASON_KEYS = [
    "pose_corr_skip_empty_boxes_count",
    "pose_corr_skip_no_matches_count",
    "pose_corr_skip_svd_failed_count",
    "pose_corr_skip_compare_gate_count",
    "pose_corr_skip_exception_count",
    "pose_corr_skip_other_count",
]


def _to_float(v: Any) -> float:
    try:
        if v is None:
            return float("nan")
        return float(v)
    except Exception:
        return float("nan")


def _fmt(v: Any, *, digits: int = 3) -> str:
    fv = _to_float(v)
    if math.isnan(fv):
        return "NA"
    return f"{fv:.{digits}f}"


def _fmt_int(v: Any) -> str:
    try:
        if v is None:
            return "NA"
        return str(int(v))
    except Exception:
        return "NA"


def _norm_noise(noise: Any) -> str:
    try:
        return f"{float(noise):.1f}"
    except Exception:
        return str(noise)


def main() -> None:
    ap = argparse.ArgumentParser(description="Summarize pose-correction reason breakdown from results JSON.")
    ap.add_argument("--run-dir", type=Path, default=None, help="Directory containing results_ap50_from_yaml.json")
    ap.add_argument("--results-json", type=Path, default=None, help="Path to results_ap50_from_yaml.json")
    ap.add_argument("--out", type=Path, default=None, help="Output markdown path")
    ap.add_argument("--dataset", type=str, default="", help="Optional dataset label for the report title")
    ap.add_argument("--only-sweep", type=str, default="", help="If set, only report this sweep (e.g., noise10)")
    ap.add_argument("--only-modality", type=str, default="", help="If set, only report this modality (camera/lidar)")
    args = ap.parse_args()

    if args.results_json is None:
        if args.run_dir is None:
            raise SystemExit("Need --run-dir or --results-json")
        args.results_json = args.run_dir / "results_ap50_from_yaml.json"
    results_json = Path(args.results_json)
    if not results_json.exists():
        raise SystemExit(f"Missing results json: {results_json}")

    run_dir = args.run_dir or results_json.parent
    out_path = args.out or (run_dir / "pose_reason_breakdown.md")

    obj = json.loads(results_json.read_text(encoding="utf-8"))
    entries = obj.get("entries") or []
    if not isinstance(entries, list) or not entries:
        raise SystemExit(f"No entries in {results_json}")

    dataset = str(args.dataset).strip() or str(obj.get("dataset") or "").strip() or "UNKNOWN_DATASET"

    # Group by (modality, sweep, method, strategy).
    groups: Dict[Tuple[str, str, str, str], List[dict]] = defaultdict(list)
    for e in entries:
        if not isinstance(e, dict):
            continue
        modality = str(e.get("modality") or "")
        sweep = str(e.get("sweep") or "")
        method = str(e.get("method") or "")
        strategy = str(e.get("strategy") or "")
        if args.only_sweep and sweep != args.only_sweep:
            continue
        if args.only_modality and modality != args.only_modality:
            continue
        groups[(modality, sweep, method, strategy)].append(e)

    def _sort_key(k: Tuple[str, str, str, str]) -> Tuple[str, str, str, str]:
        return (k[0], k[1], k[2], k[3])

    lines: List[str] = []
    lines.append(f"# Pose-Correction Reason Breakdown ({dataset})")
    lines.append("")
    lines.append(f"- run_dir: `{run_dir}`")
    lines.append(f"- results_json: `{results_json}`")
    lines.append("")
    lines.append("Notes:")
    lines.append("- `pose_corr_*_count` are per-sample counters (aggregated across pairs), then averaged over samples.")
    lines.append("- `est_total_* = mean_count * samples` is an *estimate* of total counts over the evaluated subset.")
    lines.append("")

    # Only report methods that contain at least one reason key in any entry.
    def _has_reason(e: dict) -> bool:
        return any(e.get(k) is not None for k in (["pose_corr_pair_total_count", "pose_corr_applied_pair_count"] + REASON_KEYS))

    for (modality, sweep, method, strategy) in sorted(groups.keys(), key=_sort_key):
        pts = groups[(modality, sweep, method, strategy)]
        if not any(_has_reason(p) for p in pts):
            continue
        pts_sorted = sorted(pts, key=lambda x: float(_norm_noise(x.get("noise"))) if str(x.get("noise", "")).replace(".", "", 1).isdigit() else 1e9)

        lines.append(f"## {modality} / {sweep} / {method}-{strategy}")
        lines.append("")
        lines.append("| noise | ap50 | samples | applied(sample) | pair_total(mean) | applied_pairs(mean) | " + " | ".join([k.replace('pose_corr_', '').replace('_count','') for k in REASON_KEYS]) + " |")
        lines.append("|---:|---:|---:|---:|---:|---:| " + " | ".join(["---:" for _ in REASON_KEYS]) + " |")

        for p in pts_sorted:
            noise = _norm_noise(p.get("noise"))
            ap50 = _fmt(p.get("ap50"), digits=6)
            samples = _fmt_int(p.get("samples"))
            applied = _fmt(p.get("pose_provider_applied_count"))
            pair_total = _fmt(p.get("pose_corr_pair_total_count"))
            applied_pairs = _fmt(p.get("pose_corr_applied_pair_count"))
            reason_vals = [_fmt(p.get(k)) for k in REASON_KEYS]
            lines.append(
                "| {} | {} | {} | {} | {} | {} | {} |".format(
                    noise, ap50, samples, applied, pair_total, applied_pairs, " | ".join(reason_vals)
                )
            )

        # Add a compact derived summary at the end (rates at max noise).
        try:
            last = pts_sorted[-1]
            denom = float(last.get("pose_corr_pair_total_count") or 0.0)
            lines.append("")
            lines.append("Derived (from the last noise point):")
            if denom > 0:
                for k in REASON_KEYS:
                    v = float(last.get(k) or 0.0)
                    lines.append(f"- {k}: rate≈{v/denom:.3f} (mean_count={v:.3f}, pair_total={denom:.3f})")
            else:
                lines.append("- pair_total is NA/0 -> skip rate summary")
        except Exception:
            pass
        lines.append("")

    if len(lines) <= 8:
        lines.append("No pose_corr_* fields found in entries. This run likely predates reason instrumentation.")
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print("out:", out_path)


if __name__ == "__main__":
    main()

