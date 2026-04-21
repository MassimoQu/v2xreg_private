#!/usr/bin/env python3
"""
Analyze whether corner-index permutations are needed between two box sets.

This script quantifies how often the *best* dihedral permutation (D4 on the bottom
face, extended to 8 corners) is non-identity when comparing corresponding boxes.

It is primarily intended to answer:
  1) Do GT (7D-derived) boxes exhibit corner-index ambiguity like detector boxes?
  2) For detector boxes, is the ambiguity mostly 180° (shift=2) or broader?

Method:
  - Load samples via the normal DatasetManager (GT or detection boxes depending on config).
  - Apply the filter pipeline (top-k, distance filtering, etc.).
  - Use GT extrinsic T_true to transform infra boxes into vehicle frame.
  - Match boxes by Hungarian assignment on center distance, then keep pairs under a threshold.
  - For each paired box, compute vertex mean distance under all 8 dihedral permutations
    and record which permutation is best.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy.optimize import linear_sum_assignment

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calib.config import load_config
from calib.data.dataset_manager import DatasetManager
from calib.filters.pipeline import FilterPipeline
from v2x_calib.utils import implement_T_3dbox_object_list


DIHEDRAL_4: List[Tuple[int, int, int, int]] = [
    (0, 1, 2, 3),
    (1, 2, 3, 0),
    (2, 3, 0, 1),
    (3, 0, 1, 2),
    (0, 3, 2, 1),
    (3, 2, 1, 0),
    (2, 1, 0, 3),
    (1, 0, 3, 2),
]
DIHEDRAL_8: List[Tuple[int, ...]] = [tuple(p) + tuple(i + 4 for i in p) for p in DIHEDRAL_4]


def _corners(box) -> np.ndarray:
    return np.asarray(box.get_bbox3d_8_3(), dtype=np.float32).reshape(-1, 3)


def _centers(boxes) -> np.ndarray:
    if not boxes:
        return np.zeros((0, 3), dtype=np.float32)
    return np.stack([_corners(b).mean(axis=0) for b in boxes], axis=0)


def _vertex_mean_dist(a: np.ndarray, b: np.ndarray, perm: Sequence[int]) -> float:
    diff = a[list(perm)] - b
    return float(np.linalg.norm(diff, axis=1).mean())


def _best_perm(a: np.ndarray, b: np.ndarray) -> Tuple[int, float, float]:
    errs = [_vertex_mean_dist(a, b, perm) for perm in DIHEDRAL_8]
    best = int(np.argmin(errs))
    return best, float(errs[best]), float(errs[0])


def _stats(values: Sequence[float]) -> Dict[str, float]:
    arr = np.asarray(list(values), dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return {"n": 0}
    return {
        "n": int(arr.size),
        "median": float(np.median(arr)),
        "p90": float(np.percentile(arr, 90)),
        "p99": float(np.percentile(arr, 99)),
        "mean": float(np.mean(arr)),
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--config",
        default="configs/paper3737/dair/pipeline_paper_dair3737_gt.yaml",
        help="Pipeline config YAML.",
    )
    p.add_argument("--max-samples", type=int, default=None, help="Optional cap on number of frames.")
    p.add_argument("--center-threshold", type=float, default=1.0, help="Max center distance for paired boxes.")
    p.add_argument(
        "--require-same-type",
        action="store_true",
        help="Only keep paired boxes if bbox_type matches (GT only; detections usually all 'detected').",
    )
    p.add_argument("--out", type=str, default=None, help="Optional JSON output path for the report.")
    p.add_argument("--examples", type=int, default=10, help="How many mismatch examples to store.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    if args.max_samples is not None:
        cfg.data.max_samples = int(args.max_samples)
    dataset = DatasetManager(cfg.data)
    filters = FilterPipeline(cfg.filters)

    center_thr = float(args.center_threshold)

    perm_counts = {i: 0 for i in range(len(DIHEDRAL_8))}
    id_err: List[float] = []
    best_err: List[float] = []
    improvements: List[float] = []
    pairs = 0
    frames = 0
    mismatch_examples: List[Dict[str, Any]] = []

    for sample in dataset.samples():
        frames += 1
        if cfg.data.use_detection:
            infra_boxes = sample.detections_infra or []
            veh_boxes = sample.detections_vehicle or []
        else:
            infra_boxes = sample.infra_boxes or []
            veh_boxes = sample.veh_boxes or []

        infra_boxes, veh_boxes = filters.apply(infra_boxes, veh_boxes)
        if not infra_boxes or not veh_boxes:
            continue

        infra_in_vehicle = implement_T_3dbox_object_list(sample.T_true, infra_boxes)
        c_infra = _centers(infra_in_vehicle)
        c_veh = _centers(veh_boxes)
        dist = np.linalg.norm(c_infra[:, None, :] - c_veh[None, :, :], axis=2)
        row_ind, col_ind = linear_sum_assignment(dist)

        for i, j in zip(row_ind.tolist(), col_ind.tolist()):
            d = float(dist[i, j])
            if not math.isfinite(d) or d > center_thr:
                continue
            if args.require_same_type:
                if str(infra_boxes[i].get_bbox_type()).lower() != str(veh_boxes[j].get_bbox_type()).lower():
                    continue
            a = _corners(infra_in_vehicle[i])
            b = _corners(veh_boxes[j])
            if a.shape != (8, 3) or b.shape != (8, 3):
                continue
            best_idx, e_best, e_id = _best_perm(a, b)
            pairs += 1
            perm_counts[best_idx] += 1
            id_err.append(e_id)
            best_err.append(e_best)
            improvements.append(e_id - e_best)

            if best_idx != 0 and len(mismatch_examples) < int(args.examples):
                mismatch_examples.append(
                    {
                        "infra_id": sample.infra_id,
                        "veh_id": sample.veh_id,
                        "index": int(sample.index),
                        "center_dist_m": d,
                        "best_perm": int(best_idx),
                        "id_err": float(e_id),
                        "best_err": float(e_best),
                        "bbox_type_infra": str(infra_boxes[i].get_bbox_type()),
                        "bbox_type_vehicle": str(veh_boxes[j].get_bbox_type()),
                    }
                )

    identity = perm_counts[0]
    report: Dict[str, Any] = {
        "config": str(args.config),
        "use_detection": bool(cfg.data.use_detection),
        "frames_seen": int(frames),
        "pairs_used": int(pairs),
        "center_threshold_m": center_thr,
        "require_same_type": bool(args.require_same_type),
        "perm_counts": {str(k): int(v) for k, v in perm_counts.items()},
        "identity_ratio": float(identity / pairs) if pairs else 0.0,
        "non_identity_ratio": float((pairs - identity) / pairs) if pairs else 0.0,
        "id_err_stats": _stats(id_err),
        "best_err_stats": _stats(best_err),
        "improvement_stats": _stats(improvements),
        "mismatch_examples": mismatch_examples,
    }

    print(json.dumps(report, indent=2))
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
