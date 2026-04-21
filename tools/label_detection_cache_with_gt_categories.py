#!/usr/bin/env python3
"""
Debug utility: label detection boxes with GT categories (per-agent) using nearest-neighbour
assignment in the same local frame.

This is NOT a paper-aligned setting (it uses GT semantics), but it helps answer whether
missing category labels in the detection cache are a major cause of PP/SC failure.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, MutableMapping, Optional, Sequence, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2x_calib.reader import CooperativeBatchingReader


def _centers_and_types(gt_boxes) -> Tuple[np.ndarray, Sequence[str]]:
    centers = []
    types = []
    for box in gt_boxes or []:
        corners = np.asarray(box.get_bbox3d_8_3(), dtype=np.float32)
        if corners.size == 0:
            continue
        centers.append(corners.mean(axis=0)[:2])
        types.append(str(box.get_bbox_type() or 'detected').lower())
    if not centers:
        return np.zeros((0, 2), dtype=np.float32), []
    return np.stack(centers, axis=0), types


def _infer_agent_indices(record: Mapping[str, Any]) -> Tuple[int, int]:
    cav_ids = record.get("cav_id_list")
    if not isinstance(cav_ids, list):
        return 0, 1
    infra_idx = None
    veh_idx = None
    for idx, cav_id in enumerate(cav_ids):
        text = str(cav_id).lower()
        if infra_idx is None and ("infra" in text or "rsu" in text):
            infra_idx = idx
        if veh_idx is None and "veh" in text:
            veh_idx = idx
        if infra_idx is not None and veh_idx is not None:
            break
    if infra_idx is None:
        infra_idx = 0
    if veh_idx is None:
        veh_idx = 1 if len(cav_ids) > 1 else 0
    return int(infra_idx), int(veh_idx)


def _label_boxes(
    det_boxes: Any,
    gt_centers_xy: np.ndarray,
    gt_types: Sequence[str],
    max_center_dist_m: float,
) -> list[Any]:
    if not isinstance(det_boxes, list):
        return []
    labeled = []
    for entry in det_boxes:
        corners = None
        if isinstance(entry, dict):
            corners = entry.get("corners") or entry.get("points") or entry.get("bbox")
        else:
            corners = entry
        if corners is None:
            continue
        arr = np.asarray(corners, dtype=np.float32)
        if arr.size == 0:
            continue
        center_xy = arr.reshape(-1, 3).mean(axis=0)[:2]
        label = "detected"
        if gt_centers_xy.size > 0:
            diff = gt_centers_xy - center_xy[None, :]
            dists = np.linalg.norm(diff, axis=1)
            best = int(dists.argmin())
            if float(dists[best]) <= float(max_center_dist_m):
                label = str(gt_types[best]).lower()
        if isinstance(entry, dict):
            updated: Dict[str, Any] = dict(entry)
            if "corners" not in updated and corners is not None:
                updated["corners"] = corners
            updated["type"] = label
            updated.setdefault("score", updated.get("confidence", 1.0))
            labeled.append(updated)
        else:
            labeled.append({"corners": corners, "type": label, "score": 1.0})
    return labeled


def _load_cache(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"detection cache must be a JSON object, got {type(raw)}")
    return {str(k): v for k, v in raw.items()}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Label detection cache boxes with GT categories (debug only).")
    parser.add_argument("--data-info", required=True, help="Data-info JSON list (e.g. paper3737 subset).")
    parser.add_argument("--data-root", required=True, help="DAIR cooperative root folder.")
    parser.add_argument("--input", required=True, help="Input detection cache JSON (ID-keyed recommended).")
    parser.add_argument("--output", required=True, help="Output labeled detection cache JSON.")
    parser.add_argument(
        "--max-center-dist-m",
        type=float,
        default=2.0,
        help="Max XY distance to assign a GT category (default: 2.0m).",
    )
    parser.add_argument("--max-samples", type=int, default=None, help="Optional limit on number of frames.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_info_path = Path(args.data_info)
    data_root = Path(args.data_root)
    input_path = Path(args.input)
    output_path = Path(args.output)

    cache = _load_cache(input_path)
    reader = CooperativeBatchingReader(
        path_data_info=str(data_info_path),
        path_data_folder=str(data_root),
    )

    labeled_cache: Dict[str, Any] = {}
    missing = 0
    processed = 0
    for idx, (infra_id, veh_id, infra_gt, veh_gt, _T_true) in enumerate(
        reader.generate_infra_vehicle_bboxes_object_list()
    ):
        if args.max_samples is not None and processed >= int(args.max_samples):
            break
        key = f"{infra_id}_{veh_id}"
        record = cache.get(key)
        if record is None:
            record = cache.get(f"{veh_id}_{infra_id}")
        if not isinstance(record, Mapping):
            missing += 1
            continue
        pred_list = record.get("pred_corner3d_np_list")
        if not isinstance(pred_list, list) or len(pred_list) < 2:
            missing += 1
            continue
        infra_idx, veh_idx = _infer_agent_indices(record)
        infra_centers_xy, infra_types = _centers_and_types(infra_gt)
        veh_centers_xy, veh_types = _centers_and_types(veh_gt)

        updated_record: MutableMapping[str, Any] = dict(record)
        new_pred_list = list(pred_list)
        new_pred_list[infra_idx] = _label_boxes(
            pred_list[infra_idx], infra_centers_xy, infra_types, args.max_center_dist_m
        )
        new_pred_list[veh_idx] = _label_boxes(
            pred_list[veh_idx], veh_centers_xy, veh_types, args.max_center_dist_m
        )
        updated_record["pred_corner3d_np_list"] = new_pred_list
        labeled_cache[key] = updated_record

        processed += 1
        if processed <= 3 or processed % 200 == 0:
            print(f"[label] {processed} frames (missing={missing})")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(labeled_cache, f, indent=2)
    print(f"Wrote labeled cache: pairs={len(labeled_cache)} missing={missing} -> {output_path}")


if __name__ == "__main__":
    main()
