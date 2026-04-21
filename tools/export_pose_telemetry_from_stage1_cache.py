#!/usr/bin/env python3
"""Export raw stage-1 pose estimation telemetry (raw matches + raw T) under a fixed stage1 cache.

This script is *pose-solver only* (no downstream AP inference). It is intended to:
- pick one stage1 cache (e.g. the most-used one) and
- dump per-sample/per-pair raw estimates + correspondence stats,
so we can later correlate geometry ↔ cooperative perception AP.

Outputs:
- one telemetry jsonl(.gz) per (method, strategy, noise)
- one metrics json per (method, strategy, noise)

Example (OPV2V lidar stage1, quick sanity):
  PYTHONPATH=HEAL ./.micromamba/envs/py39/bin/python \
    tools/export_pose_telemetry_from_stage1_cache.py \
    --model-dir HEAL/opencood/logs/freealign_repro_opv2v_baseline \
    --stage1-result data/OPV2V/detected/opv2v_lidar_v2xvit_stage1/test/stage1_boxes.json \
    --dataset OPV2V --modality lidar --lane track_d \
    --methods v2xregpp,freealign,vips,cbm --strategies best,stable \
    --pos-std-list 0,1,2,3,4,5,6,7,8,9,10 --rot-std-list 0,1,2,3,4,5,6,7,8,9,10 \
    --max-samples 200 --out-dir outputs/pose_telemetry/opv2v_lidar_stage1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
HEAL = ROOT / "HEAL"
if str(HEAL) not in sys.path:
    sys.path.insert(0, str(HEAL))

import opencood.hypes_yaml.yaml_utils as yaml_utils  # noqa: E402
from opencood.data_utils.datasets import build_dataset  # noqa: E402
from opencood.extrinsics.pose_correction import build_pose_corrector, run_pose_solver  # noqa: E402
from opencood.utils.common_utils import read_json  # noqa: E402


def _parse_float_list(raw: str) -> List[float]:
    values: List[float] = []
    for token in (raw or "").split(","):
        token = token.strip()
        if not token:
            continue
        values.append(float(token))
    return values


def _paired_noise_pairs(pos_list: Sequence[float], rot_list: Sequence[float]) -> List[Tuple[float, float]]:
    if not pos_list:
        pos_list = [0.0]
    if not rot_list:
        rot_list = [0.0]
    if len(pos_list) == 1 and len(rot_list) > 1:
        pos_list = list(pos_list) * len(rot_list)
    if len(rot_list) == 1 and len(pos_list) > 1:
        rot_list = list(rot_list) * len(pos_list)
    if len(pos_list) != len(rot_list):
        raise ValueError("paired sweep requires equal-length pos/rot lists (or one of them length=1)")
    return list(zip(pos_list, rot_list))


def _default_device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _v2xregpp_default_config() -> str:
    cand = ROOT / "configs" / "dair" / "midfusion" / "pipeline_midfusion_detection_occ.yaml"
    if cand.exists():
        return str(cand)
    legacy = ROOT / "configs" / "pipeline_midfusion_detection_occ.yaml"
    return str(legacy)


def _build_corrector_args(
    *,
    method: str,
    strategy: str,
    device: str,
    v2xregpp_config: str,
    compare_distance_threshold_m: float,
    apply_if_current_precision_below: float,
    min_precision_improvement: float,
    min_matched_improvement: int,
    min_precision: float,
    telemetry_max_pairs: int,
    telemetry_distance_threshold_m: float,
) -> Tuple[str, Dict]:
    """Return (pose_solver_method_tag, args) for build_pose_corrector."""
    strategy = str(strategy or "best").lower().strip()
    stable = strategy == "stable"
    compare_with_current = strategy == "best"

    method = str(method or "").lower().strip()
    if method == "v2xregpp":
        return (
            "v2xregpp",
            {
                "config_path": str(v2xregpp_config),
                "device": str(device),
                "mode": "stable" if stable else "initfree",
                "compare_with_current": bool(compare_with_current),
                "compare_distance_threshold_m": float(compare_distance_threshold_m),
                "apply_if_current_precision_below": float(apply_if_current_precision_below),
                "min_precision_improvement": float(min_precision_improvement),
                "min_matched_improvement": int(min_matched_improvement),
                "min_precision": float(min_precision),
                "telemetry_enable": True,
                "telemetry_max_pairs": int(telemetry_max_pairs),
                "telemetry_distance_threshold_m": float(telemetry_distance_threshold_m),
            },
        )

    if method == "freealign":
        return (
            "freealign",
            {
                "backend": "paper",
                "mode": "stable" if stable else "initfree",
                "device": str(device),
                "compare_with_current": bool(compare_with_current),
                "compare_distance_threshold_m": float(compare_distance_threshold_m),
                "apply_if_current_precision_below": float(apply_if_current_precision_below),
                "min_precision_improvement": float(min_precision_improvement),
                "min_matched_improvement": int(min_matched_improvement),
                "min_precision": float(min_precision),
                "telemetry_enable": True,
                "telemetry_max_pairs": int(telemetry_max_pairs),
                "telemetry_distance_threshold_m": float(telemetry_distance_threshold_m),
            },
        )

    if method in {"vips", "cbm"}:
        return (
            method,
            {
                "mode": "stable" if stable else "initfree",
                "device": str(device),
                "compare_with_current": bool(compare_with_current),
                "compare_distance_threshold_m": float(compare_distance_threshold_m),
                "apply_if_current_precision_below": float(apply_if_current_precision_below),
                "min_precision_improvement": float(min_precision_improvement),
                "min_matched_improvement": int(min_matched_improvement),
                "min_precision": float(min_precision),
                "telemetry_enable": True,
                "telemetry_max_pairs": int(telemetry_max_pairs),
                "telemetry_distance_threshold_m": float(telemetry_distance_threshold_m),
            },
        )

    raise ValueError(f"Unsupported method: {method}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, help="OpenCOOD log dir containing config.yaml")
    parser.add_argument("--stage1-result", required=True, help="stage1_boxes.json path")

    parser.add_argument("--dataset", default="", help="Optional dataset tag for telemetry_context")
    parser.add_argument("--modality", default="", help="Optional modality tag for telemetry_context")
    parser.add_argument("--lane", default="", help="Optional lane tag for telemetry_context")

    parser.add_argument("--methods", default="v2xregpp,freealign,vips,cbm")
    parser.add_argument("--strategies", default="best,stable")

    parser.add_argument("--pos-std-list", default="0,1,2,3,4,5,6,7,8,9,10")
    parser.add_argument("--rot-std-list", default="0,1,2,3,4,5,6,7,8,9,10")
    parser.add_argument("--noise-target", default="non-ego", choices=["all", "ego", "non-ego"])

    parser.add_argument("--device", default="auto", help="pose device: auto|cpu|cuda")
    parser.add_argument("--v2xregpp-config", default="", help="pipeline yaml for v2xregpp")

    parser.add_argument("--compare-distance-threshold-m", type=float, default=3.0)
    parser.add_argument("--apply-if-current-precision-below", type=float, default=1.8)
    parser.add_argument("--min-precision-improvement", type=float, default=0.0)
    parser.add_argument("--min-matched-improvement", type=int, default=0)
    parser.add_argument("--min-precision", type=float, default=0.0)

    parser.add_argument("--telemetry-max-pairs", type=int, default=50)
    parser.add_argument(
        "--telemetry-distance-threshold-m",
        type=float,
        default=3.0,
        help="Distance threshold for method-agnostic CorrespondingDetector telemetry.",
    )

    parser.add_argument("--max-samples", type=int, default=0)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    model_dir = Path(args.model_dir).expanduser().resolve()
    stage1_path = Path(args.stage1_result).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()

    if args.device == "auto":
        device = _default_device()
    else:
        device = str(args.device)

    v2xregpp_config = args.v2xregpp_config or _v2xregpp_default_config()

    # Load config.yaml via yaml_utils (same behavior as inference_w_noise.py)
    opt = argparse.Namespace(model_dir=str(model_dir))
    hypes = yaml_utils.load_yaml(None, opt)

    # Match inference_w_noise.py behavior: evaluate on test split.
    if "test_dir" in hypes and hypes.get("test_dir"):
        hypes["validate_dir"] = hypes["test_dir"]

    # Keep dataset-side noise disabled (or zero) so run_pose_solver is the single noise injector.
    noise_setting0 = OrderedDict()
    noise_setting0["add_noise"] = False
    noise_setting0["args"] = {
        "pos_std": 0.0,
        "rot_std": 0.0,
        "pos_mean": 0.0,
        "rot_mean": 0.0,
        "target": str(args.noise_target),
    }
    hypes["noise_setting"] = noise_setting0

    opencood_dataset = build_dataset(hypes, visualize=False, train=False)
    stage1_result = read_json(str(stage1_path))

    methods = [m.strip() for m in str(args.methods).split(",") if m.strip()]
    strategies = [s.strip() for s in str(args.strategies).split(",") if s.strip()]

    noise_pairs = _paired_noise_pairs(_parse_float_list(args.pos_std_list), _parse_float_list(args.rot_std_list))

    for method in methods:
        for strategy in strategies:
            for pos_std, rot_std in noise_pairs:
                tag = f"{method}_{strategy}_pos{pos_std:.1f}_rot{rot_std:.1f}"
                run_out = out_dir / method / strategy
                run_out.mkdir(parents=True, exist_ok=True)

                telemetry_path = run_out / f"telemetry_{tag}.jsonl.gz"
                metrics_path = run_out / f"metrics_{tag}.json"

                solver_method, corrector_args = _build_corrector_args(
                    method=method,
                    strategy=strategy,
                    device=device,
                    v2xregpp_config=v2xregpp_config,
                    compare_distance_threshold_m=float(args.compare_distance_threshold_m),
                    apply_if_current_precision_below=float(args.apply_if_current_precision_below),
                    min_precision_improvement=float(args.min_precision_improvement),
                    min_matched_improvement=int(args.min_matched_improvement),
                    min_precision=float(args.min_precision),
                    telemetry_max_pairs=int(args.telemetry_max_pairs),
                    telemetry_distance_threshold_m=float(args.telemetry_distance_threshold_m),
                )

                corrector = build_pose_corrector(solver_method, args=corrector_args)

                noise_setting = OrderedDict()
                noise_setting["add_noise"] = True
                noise_setting["args"] = {
                    "pos_std": float(pos_std),
                    "rot_std": float(rot_std),
                    "pos_mean": 0.0,
                    "rot_mean": 0.0,
                    "target": str(args.noise_target),
                }

                telemetry_context = {
                    "dataset": str(args.dataset),
                    "modality": str(args.modality),
                    "lane": str(args.lane),
                    "stage1_result": str(stage1_path),
                    "method": str(method),
                    "strategy": str(strategy),
                }

                solver_result = run_pose_solver(
                    opencood_dataset,
                    corrector=corrector,
                    stage1_result=stage1_result,
                    noise_setting=noise_setting,
                    max_samples=(int(args.max_samples) if int(args.max_samples or 0) > 0 else None),
                    seed=303,
                    telemetry_path=str(telemetry_path),
                    telemetry_context=telemetry_context,
                )

                payload = dict(solver_result.metrics)
                payload.update(
                    {
                        "dataset": str(args.dataset),
                        "modality": str(args.modality),
                        "lane": str(args.lane),
                        "stage1_result": str(stage1_path),
                        "method": str(method),
                        "strategy": str(strategy),
                        "noise_pos_std": float(pos_std),
                        "noise_rot_std": float(rot_std),
                        "telemetry_path": str(telemetry_path),
                    }
                )
                metrics_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
                print(f"[OK] {tag} -> {telemetry_path}")


if __name__ == "__main__":
    main()
