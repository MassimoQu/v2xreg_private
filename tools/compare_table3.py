#!/usr/bin/env python3
"""
Compare local `metrics.json` outputs against the paper's Table III numbers.

This script is intended for internal sanity checks when curating "paper-aligned"
reproduction outputs. It does NOT run any experiments.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class TableRow:
    name: str
    paper: Dict[str, float]
    rel_metrics_path: str


PAPER_TABLE_III: Dict[str, Dict[str, float]] = {
    # Init ✓ (noise in both translation meters and rotation degrees)
    "ICP_noise0": {
        "mRRE@1deg": 0.65,
        "mRRE@2deg": 0.98,
        "mRRE@3deg": 1.07,
        "mRTE@1m": 0.42,
        "mRTE@2m": 0.54,
        "mRTE@3m": 0.58,
        "success@1m": 47.52,
        "success@2m": 89.55,
        "success@3m": 96.01,
        "time": 2.91,
    },
    "ICP_noise1": {
        "mRRE@1deg": 0.80,
        "mRRE@2deg": 1.36,
        "mRRE@3deg": 1.72,
        "mRTE@1m": 0.66,
        "mRTE@2m": 1.31,
        "mRTE@3m": 1.62,
        "success@1m": 0.86,
        "success@2m": 37.93,
        "success@3m": 80.50,
        "time": 2.92,
    },
    "ICP_noise2": {
        "mRRE@1deg": 0.00,
        "mRRE@2deg": 1.48,
        "mRRE@3deg": 2.11,
        "mRTE@1m": 0.00,
        "mRTE@2m": 1.33,
        "mRTE@3m": 2.03,
        "success@1m": 0.00,
        "success@2m": 3.66,
        "success@3m": 19.94,
        "time": 2.86,
    },
    "PICP_noise0": {
        "mRRE@1deg": 0.52,
        "mRRE@2deg": 0.80,
        "mRRE@3deg": 0.88,
        "mRTE@1m": 0.42,
        "mRTE@2m": 0.54,
        "mRTE@3m": 0.57,
        "success@1m": 59.59,
        "success@2m": 90.41,
        "success@3m": 96.12,
        "time": 1.35,
    },
    "PICP_noise1": {
        "mRRE@1deg": 0.74,
        "mRRE@2deg": 1.31,
        "mRRE@3deg": 1.67,
        "mRTE@1m": 0.75,
        "mRTE@2m": 1.32,
        "mRTE@3m": 1.63,
        "success@1m": 2.91,
        "success@2m": 42.78,
        "success@3m": 87.93,
        "time": 1.76,
    },
    "PICP_noise2": {
        "mRRE@1deg": 0.80,
        "mRRE@2deg": 1.40,
        "mRRE@3deg": 2.11,
        "mRTE@1m": 0.53,
        "mRTE@2m": 1.45,
        "mRTE@3m": 2.10,
        "success@1m": 0.22,
        "success@2m": 2.69,
        "success@3m": 21.12,
        "time": 1.70,
    },
    "VIPS_noise0": {
        "mRRE@1deg": 0.63,
        "mRRE@2deg": 0.89,
        "mRRE@3deg": 0.99,
        "mRTE@1m": 0.54,
        "mRTE@2m": 0.78,
        "mRTE@3m": 0.89,
        "success@1m": 54.20,
        "success@2m": 88.69,
        "success@3m": 97.63,
        "time": 0.46,
    },
    "VIPS_noise1": {
        "mRRE@1deg": 0.66,
        "mRRE@2deg": 1.04,
        "mRRE@3deg": 1.24,
        "mRTE@1m": 0.54,
        "mRTE@2m": 0.82,
        "mRTE@3m": 1.02,
        "success@1m": 18.53,
        "success@2m": 39.01,
        "success@3m": 47.74,
        "time": 0.44,
    },
    "VIPS_noise2": {
        "mRRE@1deg": 0.58,
        "mRRE@2deg": 1.17,
        "mRRE@3deg": 1.56,
        "mRTE@1m": 0.48,
        "mRTE@2m": 0.96,
        "mRTE@3m": 1.39,
        "success@1m": 2.37,
        "success@2m": 7.87,
        "success@3m": 13.15,
        "time": 0.47,
    },
    "CBM_noise0": {
        "mRRE@1deg": 0.61,
        "mRRE@2deg": 0.97,
        "mRRE@3deg": 1.21,
        "mRTE@1m": 0.53,
        "mRTE@2m": 0.80,
        "mRTE@3m": 1.06,
        "success@1m": 17.11,
        "success@2m": 23.04,
        "success@3m": 26.49,
        "time": 0.35,
    },
    "CBM_noise1": {
        "mRRE@1deg": 0.71,
        "mRRE@2deg": 0.94,
        "mRRE@3deg": 1.14,
        "mRTE@1m": 0.61,
        "mRTE@2m": 0.74,
        "mRTE@3m": 1.00,
        "success@1m": 9.91,
        "success@2m": 15.63,
        "success@3m": 16.49,
        "time": 0.36,
    },
    "CBM_noise2": {
        "mRRE@1deg": 0.69,
        "mRRE@2deg": 1.09,
        "mRRE@3deg": 1.38,
        "mRTE@1m": 0.58,
        "mRTE@2m": 0.76,
        "mRTE@3m": 1.06,
        "success@1m": 6.03,
        "success@2m": 12.28,
        "success@3m": 16.81,
        "time": 0.35,
    },
    # Init × (no pose prior)
    "FGR": {
        "mRRE@1deg": 0.71,
        "mRRE@2deg": 1.15,
        "mRRE@3deg": 1.47,
        "mRTE@1m": 0.70,
        "mRTE@2m": 1.13,
        "mRTE@3m": 1.45,
        "success@1m": 14.76,
        "success@2m": 31.57,
        "success@3m": 35.34,
        "time": 22.73,
    },
    "Quatro": {
        "mRRE@1deg": 0.62,
        "mRRE@2deg": 1.22,
        "mRRE@3deg": 1.46,
        "mRTE@1m": 0.65,
        "mRTE@2m": 1.19,
        "mRTE@3m": 1.51,
        "success@1m": 12.07,
        "success@2m": 30.50,
        "success@3m": 45.04,
        "time": 21.58,
    },
    "Teaser++": {
        "mRRE@1deg": 0.69,
        "mRRE@2deg": 1.13,
        "mRRE@3deg": 1.47,
        "mRTE@1m": 0.66,
        "mRTE@2m": 1.09,
        "mRTE@3m": 1.44,
        "success@1m": 14.33,
        "success@2m": 29.74,
        "success@3m": 34.81,
        "time": 22.43,
    },
    "V2X-Reg": {
        "mRRE@1deg": 0.66,
        "mRRE@2deg": 1.03,
        "mRRE@3deg": 1.25,
        "mRTE@1m": 0.54,
        "mRTE@2m": 0.91,
        "mRTE@3m": 1.18,
        "success@1m": 25.54,
        "success@2m": 55.93,
        "success@3m": 72.31,
        "time": 0.21,
    },
    "V2X-Reg++GT_inf": {
        "mRRE@1deg": 0.62,
        "mRRE@2deg": 1.01,
        "mRRE@3deg": 1.26,
        "mRTE@1m": 0.49,
        "mRTE@2m": 0.83,
        "mRTE@3m": 1.07,
        "success@1m": 22.88,
        "success@2m": 48.03,
        "success@3m": 61.49,
        "time": 0.46,
    },
    "V2X-Reg++GT25": {
        "mRRE@1deg": 0.63,
        "mRRE@2deg": 1.01,
        "mRRE@3deg": 1.23,
        "mRTE@1m": 0.52,
        "mRTE@2m": 0.85,
        "mRTE@3m": 1.05,
        "success@1m": 32.27,
        "success@2m": 67.59,
        "success@3m": 82.93,
        "time": 0.12,
    },
    "V2X-Reg++GT15": {
        "mRRE@1deg": 0.65,
        "mRRE@2deg": 1.05,
        "mRRE@3deg": 1.30,
        "mRTE@1m": 0.54,
        "mRTE@2m": 0.87,
        "mRTE@3m": 1.10,
        "success@1m": 26.79,
        "success@2m": 61.17,
        "success@3m": 78.75,
        "time": 0.09,
    },
    "V2X-Reg++GT10": {
        "mRRE@1deg": 0.66,
        "mRRE@2deg": 1.11,
        "mRRE@3deg": 1.36,
        "mRTE@1m": 0.57,
        "mRTE@2m": 0.92,
        "mRTE@3m": 1.15,
        "success@1m": 20.02,
        "success@2m": 54.86,
        "success@3m": 71.98,
        "time": 0.04,
    },
    "V2X-Reg++PP15": {
        "mRRE@1deg": 0.66,
        "mRRE@2deg": 1.06,
        "mRRE@3deg": 1.29,
        "mRTE@1m": 0.55,
        "mRTE@2m": 0.86,
        "mRTE@3m": 1.07,
        "success@1m": 24.91,
        "success@2m": 56.62,
        "success@3m": 70.94,
    },
    "V2X-Reg++SC15": {
        "mRRE@1deg": 0.65,
        "mRRE@2deg": 1.05,
        "mRRE@3deg": 1.29,
        "mRTE@1m": 0.54,
        "mRTE@2m": 0.86,
        "mRTE@3m": 1.06,
        "success@1m": 25.15,
        "success@2m": 56.89,
        "success@3m": 71.23,
    },
    "V2X-Reg++GT25_hSVD": {
        "mRRE@1deg": 0.71,
        "mRRE@2deg": 1.13,
        "mRRE@3deg": 1.35,
        "mRTE@1m": 0.62,
        "mRTE@2m": 0.98,
        "mRTE@3m": 1.25,
        "success@1m": 21.82,
        "success@2m": 60.43,
        "success@3m": 74.92,
        "time": 0.12,
    },
    "V2X-Reg++GT25_mSVD": {
        "mRRE@1deg": 0.67,
        "mRRE@2deg": 1.08,
        "mRRE@3deg": 1.31,
        "mRTE@1m": 0.56,
        "mRTE@2m": 0.94,
        "mRTE@3m": 1.19,
        "success@1m": 25.22,
        "success@2m": 63.58,
        "success@3m": 80.22,
        "time": 0.12,
    },
}


DEFAULT_PATHS: Dict[str, str] = {
    # Proposed + ablations (paper subset outputs)
    "V2X-Reg": "dair_v2xreg_oiou_gt15/metrics.json",
    "V2X-Reg++GT_inf": "dair_v2xregpp_gt_inf/metrics.json",
    "V2X-Reg++GT25": "dair_v2xregpp_gt25/metrics.json",
    "V2X-Reg++GT15": "dair_v2xregpp_gt15/metrics.json",
    "V2X-Reg++GT10": "dair_v2xregpp_gt10/metrics.json",
    "V2X-Reg++PP15": "dair_v2xregpp_pp15/metrics.json",
    "V2X-Reg++SC15": "dair_v2xregpp_sc15/metrics.json",
    "V2X-Reg++GT25_hSVD": "dair_v2xregpp_gt25_hsvd/metrics.json",
    "V2X-Reg++GT25_mSVD": "dair_v2xregpp_gt25_msvd/metrics.json",
    # Baselines (default layout under outputs_paper_3737/baselines/)
    "ICP_noise0": "baselines/icp_paper_noise0/metrics.json",
    "ICP_noise1": "baselines/icp_paper_noise1/metrics.json",
    "ICP_noise2": "baselines/icp_paper_noise2/metrics.json",
    "PICP_noise0": "baselines/picp_paper_noise0/metrics.json",
    "PICP_noise1": "baselines/picp_paper_noise1/metrics.json",
    "PICP_noise2": "baselines/picp_paper_noise2/metrics.json",
}


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _fmt_num(value: Optional[float], ndigits: int = 2) -> str:
    if value is None:
        return "-"
    return f"{value:.{ndigits}f}"


def _fmt_pct(value: Optional[float], ndigits: int = 2) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.{ndigits}f}"


def _get_metrics_value(metrics: Dict[str, Any], key: str) -> Optional[float]:
    raw = metrics.get(key)
    if raw is None:
        return None
    try:
        return float(raw)
    except Exception:
        return None


def _extract_row(metrics: Dict[str, Any]) -> Dict[str, Optional[float]]:
    return {
        "mRRE@1deg": _get_metrics_value(metrics, "mRRE@1deg"),
        "mRRE@2deg": _get_metrics_value(metrics, "mRRE@2deg"),
        "mRRE@3deg": _get_metrics_value(metrics, "mRRE@3deg"),
        "mRTE@1m": _get_metrics_value(metrics, "mRTE@1m"),
        "mRTE@2m": _get_metrics_value(metrics, "mRTE@2m"),
        "mRTE@3m": _get_metrics_value(metrics, "mRTE@3m"),
        "success@1m": _get_metrics_value(metrics, "success_at_1m"),
        "success@2m": _get_metrics_value(metrics, "success_at_2m"),
        "success@3m": _get_metrics_value(metrics, "success_at_3m"),
        "time": _get_metrics_value(metrics, "avg_time"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        default="outputs_paper_3737",
        help="Folder that contains the Table III runs (default: outputs_paper_3737).",
    )
    parser.add_argument(
        "--paths-json",
        default=None,
        help="Optional JSON mapping of row-name -> metrics.json path relative to --root.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    paths = dict(DEFAULT_PATHS)
    if args.paths_json:
        extra = json.loads(Path(args.paths_json).read_text(encoding="utf-8"))
        if isinstance(extra, dict):
            paths.update({str(k): str(v) for k, v in extra.items()})

    headers = [
        "Row",
        "Our Succ@1/2/3 (%)",
        "Paper Succ@1/2/3 (%)",
        "Our mRTE@2m / mRRE@2deg",
        "Paper mRTE@2m / mRRE@2deg",
        "Our Time(s)",
        "Paper Time(s)",
        "Path",
    ]
    print(" | ".join(headers))
    print("-|-|-|-|-|-|-|-")

    for name, paper in PAPER_TABLE_III.items():
        rel = paths.get(name)
        path_display = rel or "-"
        metrics = _load_json(root / rel) if rel else None
        ours = _extract_row(metrics) if metrics else {}

        our_succ = "/".join(
            [
                _fmt_pct(ours.get("success@1m")),
                _fmt_pct(ours.get("success@2m")),
                _fmt_pct(ours.get("success@3m")),
            ]
        )
        paper_succ = "/".join(
            [
                _fmt_num(paper.get("success@1m")),
                _fmt_num(paper.get("success@2m")),
                _fmt_num(paper.get("success@3m")),
            ]
        )
        our_pair = f"{_fmt_num(ours.get('mRTE@2m'))} / {_fmt_num(ours.get('mRRE@2deg'))}"
        paper_pair = f"{_fmt_num(paper.get('mRTE@2m'))} / {_fmt_num(paper.get('mRRE@2deg'))}"
        our_time = _fmt_num(ours.get("time"))
        paper_time = _fmt_num(paper.get("time"))

        print(
            " | ".join(
                [
                    name,
                    our_succ,
                    paper_succ,
                    our_pair,
                    paper_pair,
                    our_time,
                    paper_time,
                    str(path_display),
                ]
            )
        )


if __name__ == "__main__":
    main()

