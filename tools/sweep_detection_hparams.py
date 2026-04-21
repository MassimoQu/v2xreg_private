#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calib.config import load_config
from calib.pipelines.object_level import ObjectLevelPipeline


def _parse_list(values: str) -> List[float]:
    out: List[float] = []
    for part in (values or "").split(","):
        part = part.strip()
        if not part:
            continue
        out.append(float(part))
    return out


def _parse_int_list(values: str) -> List[int]:
    out: List[int] = []
    for part in (values or "").split(","):
        part = part.strip()
        if not part:
            continue
        out.append(int(part))
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Quick sweep for PP/SC detection hyperparameters (private triage).")
    p.add_argument("--config", required=True, help="Base pipeline YAML (e.g., pipeline_paper3737_pp15_trainval.yaml).")
    p.add_argument("--tag-prefix", required=True, help="Output tag prefix.")
    p.add_argument("--max-samples", type=int, default=500, help="Number of frames for the sweep.")
    p.add_argument("--top-k", default="15,20,25", help="Comma-separated top_k values.")
    p.add_argument("--det-thr", default="1.0,1.5,2.0", help="Comma-separated distance_thresholds.detected values.")
    p.add_argument("--filter-thr", default="3,4", help="Comma-separated matching.filter_threshold values.")
    p.add_argument(
        "--perm-mode",
        default="rot2",
        help="V2X_DETECTED_CORNER_PERM_MODE value (default: rot2).",
    )
    p.add_argument("--out", default="outputs_tmp/sweep_detection_hparams.json", help="Summary JSON output.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    os.environ["V2X_DETECTED_CORNER_PERM_MODE"] = str(args.perm_mode)
    cfg_path = str(args.config)
    top_k_values = _parse_int_list(args.top_k)
    det_thr_values = _parse_list(args.det_thr)
    filter_thr_values = _parse_int_list(args.filter_thr)

    results: List[Dict[str, Any]] = []

    for top_k in top_k_values:
        for det_thr in det_thr_values:
            for filt_thr in filter_thr_values:
                cfg = load_config(cfg_path)
                cfg.data.max_samples = int(args.max_samples)
                cfg.filters.top_k = int(top_k)
                cfg.matching.filter_threshold = int(filt_thr)
                dt = dict(cfg.matching.distance_thresholds or {})
                dt["detected"] = float(det_thr)
                cfg.matching.distance_thresholds = dt
                tag = f"{args.tag_prefix}_k{top_k}_det{det_thr:g}_f{filt_thr}_n{args.max_samples}"
                cfg.output.root_dir = "outputs_tmp"
                cfg.output.tag = tag
                print(f"[sweep] {tag}")
                m = ObjectLevelPipeline(cfg).run()
                row = {
                    "tag": tag,
                    "top_k": int(top_k),
                    "detected_thr": float(det_thr),
                    "filter_threshold": int(filt_thr),
                    "success_at_1m": float(m.get("success_at_1m", 0.0)),
                    "success_at_2m": float(m.get("success_at_2m", 0.0)),
                    "success_at_3m": float(m.get("success_at_3m", 0.0)),
                    "avg_time": float(m.get("avg_time", 0.0)),
                    "avg_matches": float(m.get("avg_matches", 0.0)),
                    "frames_with_matches": int(m.get("frames_with_matches", 0) or 0),
                }
                results.append(row)

    results.sort(key=lambda r: (-r["success_at_2m"], r["avg_time"]))
    out = {
        "config": cfg_path,
        "perm_mode": str(args.perm_mode),
        "max_samples": int(args.max_samples),
        "results": results,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"[sweep] wrote {out_path}")
    print("[sweep] top5 by success@2m:")
    for row in results[:5]:
        print(row)


if __name__ == "__main__":
    main()


