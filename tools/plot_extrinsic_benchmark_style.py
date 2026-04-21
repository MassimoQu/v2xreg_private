#!/usr/bin/env python3
"""Create benchmark-style plots from run_extrinsic_benchmark outputs.

Input directory should contain:
- metrics.json
- matches.jsonl (optional for this script, kept for future extensions)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt


def _collect_threshold_series(summary: Dict[str, object], prefix: str) -> List[Tuple[float, float]]:
    """Extract ordered (threshold_m, value) pairs from summary keys like success_at_2m."""
    out: List[Tuple[float, float]] = []
    for k, v in summary.items():
        if not k.startswith(prefix):
            continue
        if not k.endswith("m"):
            continue
        # Example: success_at_2m -> "2"
        mid = k[len(prefix) : -1]
        try:
            thr = float(mid)
            val = float(v)  # type: ignore[arg-type]
        except Exception:
            continue
        out.append((thr, val))
    return sorted(out, key=lambda x: x[0])


def _plot_success_curves(summary: Dict[str, object], out_path: Path) -> None:
    a = _collect_threshold_series(summary, "success_at_")
    b = _collect_threshold_series(summary, "success_with_matches_at_")
    if not a:
        raise ValueError("No success_at_* fields found in metrics summary.")

    x1 = [t for t, _ in a]
    y1 = [v for _, v in a]

    fig, ax = plt.subplots(figsize=(9.2, 5.6), dpi=220)
    ax.plot(x1, y1, marker="o", linewidth=1.8, label="success_at_m")

    if b:
        x2 = [t for t, _ in b]
        y2 = [v for _, v in b]
        ax.plot(x2, y2, marker="s", linestyle="--", linewidth=1.8, label="success_with_matches_at_m")

    ax.set_title("V2XReg++ Smoke Success Curve")
    ax.set_xlabel("Threshold (m)")
    ax.set_ylabel("Success Rate")
    ax.set_ylim(0.0, 1.0)
    ax.grid(True, linestyle="--", alpha=0.35)
    ax.legend(loc="lower right", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def _plot_error_curves(summary: Dict[str, object], out_path: Path) -> None:
    te = _collect_threshold_series(summary, "mTE@")
    re = _collect_threshold_series(summary, "mRE@")
    if not te and not re:
        raise ValueError("No mTE@* or mRE@* fields found in metrics summary.")

    fig, ax = plt.subplots(figsize=(9.2, 5.6), dpi=220)

    if te:
        x = [t for t, _ in te]
        y = [v for _, v in te]
        ax.plot(x, y, marker="o", linewidth=1.8, label="mTE@thr (m)")

    if re:
        x = [t for t, _ in re]
        y = [v for _, v in re]
        ax.plot(x, y, marker="^", linewidth=1.8, label="mRE@thr (deg)")

    ax.set_title("V2XReg++ Smoke Error Curve")
    ax.set_xlabel("Threshold (m)")
    ax.set_ylabel("Error")
    ax.grid(True, linestyle="--", alpha=0.35)
    ax.legend(loc="upper right", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description="Plot benchmark-style curves from extrinsic benchmark outputs.")
    ap.add_argument("--run-dir", type=Path, required=True, help="Directory containing metrics.json.")
    args = ap.parse_args()

    run_dir = args.run_dir.resolve()
    metrics_path = run_dir / "metrics.json"
    if not metrics_path.exists():
        raise SystemExit(f"Missing file: {metrics_path}")

    with metrics_path.open("r", encoding="utf-8") as f:
        obj = json.load(f)
    summary = obj.get("summary") or {}
    if not isinstance(summary, dict):
        raise SystemExit("metrics.json: summary field is missing or invalid.")

    out_success = run_dir / "plot_benchmark_style_success.png"
    out_error = run_dir / "plot_benchmark_style_error_curve.png"

    _plot_success_curves(summary, out_success)
    _plot_error_curves(summary, out_error)

    print(f"SAVED={out_success}")
    print(f"SAVED={out_error}")


if __name__ == "__main__":
    main()

