#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Override avg_time in a metrics.json (keep the old value for traceability).")
    p.add_argument("--metrics", required=True, help="Target metrics.json to patch in-place.")
    p.add_argument("--time-metrics", required=True, help="Metrics.json produced by a timing-only run.")
    p.add_argument(
        "--keep-old-key",
        default="avg_time_parallel",
        help="Key used to store the previous avg_time value (default: avg_time_parallel).",
    )
    p.add_argument(
        "--source",
        default="single_process_timing_run",
        help="Human-readable label written into avg_time_source (default: single_process_timing_run).",
    )
    p.add_argument("--dry-run", action="store_true", help="Print the patch but do not write anything.")
    return p.parse_args()


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    args = parse_args()
    metrics_path = Path(args.metrics)
    time_metrics_path = Path(args.time_metrics)

    metrics = _load_json(metrics_path)
    time_metrics = _load_json(time_metrics_path)

    new_avg_time = time_metrics.get("avg_time")
    if new_avg_time is None:
        raise SystemExit(f"Missing avg_time in timing metrics: {time_metrics_path}")

    try:
        new_avg_time = float(new_avg_time)
    except Exception as exc:
        raise SystemExit(f"Invalid avg_time in timing metrics: {time_metrics_path}: {exc}") from exc

    old_avg_time = metrics.get("avg_time")
    if args.keep_old_key:
        metrics[args.keep_old_key] = old_avg_time
    metrics["avg_time"] = new_avg_time
    metrics["avg_time_source"] = str(args.source)
    metrics["avg_time_timing_metrics"] = str(time_metrics_path)
    if isinstance(time_metrics.get("num_frames"), int):
        metrics["avg_time_num_frames"] = int(time_metrics["num_frames"])

    if args.dry_run:
        print(json.dumps(metrics, indent=2))
        return

    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"Patched avg_time in {metrics_path} from {time_metrics_path}")


if __name__ == "__main__":
    main()

