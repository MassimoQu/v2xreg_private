#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calib.evaluation.metrics import FrameMetrics, aggregate_metrics


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Merge jsonl details and recompute paper-style metrics.")
    p.add_argument(
        "--inputs",
        nargs="+",
        required=True,
        help="One or more jsonl files (supports globs like outputs/**/details.jsonl).",
    )
    p.add_argument("--output-dir", required=True, help="Directory to write merged jsonl + metrics.json.")
    p.add_argument(
        "--thresholds",
        default="1,2,3",
        help="Comma-separated success thresholds (same value used for meters+degrees), default: 1,2,3.",
    )
    p.add_argument(
        "--merged-name",
        default="details_merged.jsonl",
        help="Merged jsonl filename (default: details_merged.jsonl).",
    )
    return p.parse_args()


def iter_input_files(patterns: Iterable[str]) -> list[Path]:
    files: list[Path] = []
    for raw in patterns:
        matches = [Path(p) for p in sorted(Path().glob(raw))] if any(ch in raw for ch in "*?[]") else [Path(raw)]
        files.extend(matches)
    # De-dup while preserving order.
    seen: set[Path] = set()
    uniq: list[Path] = []
    for f in files:
        f = f.resolve()
        if f in seen:
            continue
        seen.add(f)
        uniq.append(f)
    return uniq


def _get_float(obj: dict, *keys: str) -> Optional[float]:
    for k in keys:
        if k not in obj:
            continue
        v = obj.get(k)
        if v is None:
            continue
        try:
            return float(v)
        except Exception:
            continue
    return None


def main() -> None:
    args = parse_args()
    thresholds = [float(x.strip()) for x in str(args.thresholds).split(",") if x.strip()]
    input_files = iter_input_files(args.inputs)
    if not input_files:
        raise SystemExit("No inputs matched.")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    merged_path = out_dir / args.merged_name

    records: list[FrameMetrics] = []
    written = 0
    with merged_path.open("w", encoding="utf-8") as f_out:
        for path in input_files:
            if not path.exists():
                raise FileNotFoundError(str(path))
            with path.open("r", encoding="utf-8", errors="replace") as f_in:
                for line in f_in:
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)

                    # Normalize keys (most scripts already use RE/TE/time).
                    re_deg = _get_float(obj, "RE", "rotation_error_deg", "mRE")  # noqa: E741
                    te_m = _get_float(obj, "TE", "translation_error_m", "mTE")
                    time_s = _get_float(obj, "time", "time_cost", "runtime_s", "avg_time") or 0.0
                    if re_deg is None or te_m is None:
                        raise ValueError(f"Missing RE/TE in {path}: {obj.keys()}")

                    matches_count = int(obj.get("num_matches") or obj.get("matches_count") or 0)
                    records.append(FrameMetrics(
                        infra_id=str(obj.get("infra_id", "")),
                        veh_id=str(obj.get("veh_id", "")),
                        RE=float(re_deg),
                        TE=float(te_m),
                        stability=0.0,
                        time_cost=float(time_s),
                        matches_count=matches_count,
                    ))
                    f_out.write(line + "\n")
                    written += 1

    metrics = aggregate_metrics(records, thresholds)
    metrics["merged_inputs"] = [str(p) for p in input_files]
    metrics["merged_records"] = int(written)
    metrics_path = out_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"Merged {written} records -> {merged_path}")
    print(f"Metrics -> {metrics_path}")


if __name__ == "__main__":
    main()
