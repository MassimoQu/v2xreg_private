#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class _Row:
    infra_id: str
    veh_id: str
    re: float
    te: float
    time_s: float
    matches: int


def _read_jsonl(paths: Sequence[Path]) -> List[_Row]:
    rows: List[_Row] = []
    for path in paths:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    continue

                infra_id = str(obj.get("infra_id") or obj.get("inf_id") or obj.get("source_id") or "")
                veh_id = str(obj.get("veh_id") or obj.get("target_id") or "")
                re = obj.get("RE")
                te = obj.get("TE")

                if re is None:
                    re = obj.get("rotation_error_deg")
                if te is None:
                    te = obj.get("translation_error_m")

                time_s = obj.get("time")
                if time_s is None:
                    time_s = obj.get("runtime_s")

                matches = 0
                if isinstance(obj.get("matches"), list):
                    matches = len(obj["matches"])
                elif isinstance(obj.get("num_matches"), (int, float)):
                    matches = int(obj["num_matches"])
                elif isinstance(obj.get("matches_count"), (int, float)):
                    matches = int(obj["matches_count"])

                try:
                    re_f = float(re)
                except Exception:
                    re_f = float("inf")
                try:
                    te_f = float(te)
                except Exception:
                    te_f = float("inf")
                try:
                    time_f = float(time_s) if time_s is not None else 0.0
                except Exception:
                    time_f = 0.0

                if not math.isfinite(re_f):
                    re_f = float("inf")
                if not math.isfinite(te_f):
                    te_f = float("inf")
                if not math.isfinite(time_f):
                    time_f = 0.0

                rows.append(
                    _Row(
                        infra_id=infra_id,
                        veh_id=veh_id,
                        re=re_f,
                        te=te_f,
                        time_s=time_f,
                        matches=matches,
                    )
                )
    return rows


def _parse_thresholds(raw: str) -> List[float]:
    out: List[float] = []
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        out.append(float(part))
    return out


def _format_thr(value: float) -> str:
    if float(value).is_integer():
        return f"{int(value)}"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def summarize(rows: Sequence[_Row], thresholds: Sequence[float]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    if not rows:
        return summary
    n = len(rows)
    summary["avg_time"] = sum(r.time_s for r in rows) / n
    summary["num_frames"] = n
    summary["frames_with_matches"] = sum(1 for r in rows if r.matches > 0)
    summary["avg_matches"] = sum(r.matches for r in rows) / n

    if not thresholds:
        summary["success_frames"] = n
        return summary

    for idx, thr in enumerate(thresholds):
        thr_f = float(thr)
        label = _format_thr(thr_f)
        # Table-III protocol (paper Eq.20): success at threshold λ iff translation error < λ meters.
        # Rotation errors are summarized over the successful subset (mRRE@λ).
        filtered = [r for r in rows if r.te < thr_f]
        filtered_with_matches = [r for r in filtered if r.matches > 0]

        summary[f"success_at_{label}m"] = len(filtered) / n
        summary[f"success_with_matches_at_{label}m"] = len(filtered_with_matches) / n
        if filtered:
            summary[f"mRE@{label}m"] = sum(r.re for r in filtered) / len(filtered)
            summary[f"mTE@{label}m"] = sum(r.te for r in filtered) / len(filtered)
        else:
            summary[f"mRE@{label}m"] = None
            summary[f"mTE@{label}m"] = None
        if idx == 0:
            summary["success_frames"] = len(filtered)
            summary["success_with_matches_frames"] = len(filtered_with_matches)

    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize matches/details jsonl into Table-III style metrics.json.")
    parser.add_argument("inputs", nargs="+", help="One or more *.jsonl files (matches.jsonl, details.jsonl, etc).")
    parser.add_argument("--thresholds", type=str, default="1,2,3", help="Comma-separated success thresholds in meters.")
    parser.add_argument("--out", type=str, default=None, help="Optional output path for metrics.json.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = [Path(p) for p in args.inputs]
    rows = _read_jsonl(paths)
    thresholds = _parse_thresholds(args.thresholds)
    summary = summarize(rows, thresholds)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
