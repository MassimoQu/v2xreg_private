#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calib.config import FilterConfig, load_config  # noqa: E402
from calib.filters.pipeline import FilterPipeline  # noqa: E402
from v2x_calib.corresponding import CorrespondingDetector  # noqa: E402
from v2x_calib.reader import CooperativeBatchingReader  # noqa: E402
from v2x_calib.utils import implement_T_3dbox_object_list  # noqa: E402


def _stem(path_str: str) -> str:
    return Path(path_str).stem


def _pair_key(infra_id: str, veh_id: str) -> str:
    return f"{infra_id}_{veh_id}"


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _offset_nonzero(offset: object) -> bool:
    if not isinstance(offset, Mapping):
        return False
    dx = float(offset.get("delta_x", 0.0) or 0.0)
    dy = float(offset.get("delta_y", 0.0) or 0.0)
    return (abs(dx) + abs(dy)) > 1e-6


def _build_filters(
    *,
    top_k: int,
    distance_m: float,
    priority_categories: Sequence[str],
) -> FilterPipeline:
    cfg = FilterConfig(
        top_k=int(top_k),
        distance_m=float(distance_m),
        priority_categories=[str(x) for x in (priority_categories or [])],
    )
    return FilterPipeline(cfg)


def _parse_categories(raw: str) -> List[str]:
    items = [x.strip() for x in str(raw or "").split(",")]
    return [x for x in items if x]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the DAIR-V2X paper evaluation subset (|S|=3737) as a data_info.json list.\n\n"
            "Heuristic used in this repo (matches Table-I frame count):\n"
            "  1) Require system_error_offset != (0,0).\n"
            "  2) After applying the standard filter pipeline, require >= K shared objects under T_true.\n"
            "     Shared objects are counted by CorrespondingDetector(overall_distance) with threshold tau.\n\n"
            "This produces a deterministic subset that is reused across all Table-III baselines."
        )
    )
    parser.add_argument(
        "--data-info",
        type=str,
        default="data/DAIR-V2X/cooperative-vehicle-infrastructure/cooperative/data_info.json",
        help="Full cooperative data_info.json (list).",
    )
    parser.add_argument(
        "--data-root",
        type=str,
        default="data/DAIR-V2X/cooperative-vehicle-infrastructure",
        help="Dataset root (folder containing infrastructure-side/vehicle-side).",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="data/data_info_dair_paper3737.json",
        help="Output JSON path for the selected subset.",
    )
    parser.add_argument("--top-k", type=int, default=25, help="Keep top-K boxes on each side (by size priority).")
    parser.add_argument("--distance-m", type=float, default=120.0, help="Distance gate in meters (same as pipeline).")
    parser.add_argument(
        "--categories",
        type=str,
        default="bus,truck,car",
        help="Priority categories (comma-separated).",
    )
    parser.add_argument(
        "--tau",
        type=float,
        default=1.56,
        help="Correspondence distance threshold used inside CorrespondingDetector (meters).",
    )
    parser.add_argument(
        "--min-matches",
        type=int,
        default=3,
        help="Minimum number of shared objects required to keep a pair.",
    )
    parser.add_argument(
        "--expected",
        type=int,
        default=3737,
        help="Optional expected subset size (warning if mismatched).",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=None,
        help="Optional cap for debugging (process only the first N pairs).",
    )
    parser.add_argument("--quiet", action="store_true", help="Reduce per-1000 progress logs.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    data_info_path = Path(args.data_info)
    if not data_info_path.is_absolute():
        data_info_path = (ROOT / data_info_path).resolve()
    data_root = Path(args.data_root)
    if not data_root.is_absolute():
        data_root = (ROOT / data_root).resolve()

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = (ROOT / out_path).resolve()

    raw = _read_json(data_info_path)
    if not isinstance(raw, list):
        raise ValueError(f"data_info must be a JSON list, got {type(raw)} from {data_info_path}")

    pair_to_record: Dict[str, Mapping[str, Any]] = {}
    nonzero_pairs = 0
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        infra = _stem(str(entry.get("infrastructure_image_path", "")))
        veh = _stem(str(entry.get("vehicle_image_path", "")))
        if not infra or not veh:
            continue
        key = _pair_key(infra, veh)
        pair_to_record[key] = entry
        if _offset_nonzero(entry.get("system_error_offset")):
            nonzero_pairs += 1

    categories = _parse_categories(args.categories)
    filters = _build_filters(top_k=args.top_k, distance_m=args.distance_m, priority_categories=categories)

    reader = CooperativeBatchingReader(path_data_info=str(data_info_path), path_data_folder=str(data_root))

    tau = float(args.tau)
    min_matches = int(args.min_matches)
    if tau <= 0:
        raise ValueError("--tau must be > 0")
    if min_matches <= 0:
        raise ValueError("--min-matches must be >= 1")

    threshold_dict = {"detected": tau}
    selected_keys: List[str] = []
    processed = 0

    iterator = reader.generate_infra_vehicle_bboxes_object_list()
    for infra_id, veh_id, infra_boxes, veh_boxes, T_true in iterator:
        processed += 1
        if args.max_samples is not None and processed > int(args.max_samples):
            break
        if not args.quiet and processed % 1000 == 0:
            print(f"[paper3737] processed={processed} selected={len(selected_keys)}")

        key = _pair_key(str(infra_id), str(veh_id))
        record = pair_to_record.get(key)
        if record is None:
            continue
        if not _offset_nonzero(record.get("system_error_offset")):
            continue

        infra_filtered, veh_filtered = filters.apply(infra_boxes, veh_boxes, sensor_frame="lidar")
        if not infra_filtered or not veh_filtered:
            continue

        infra_in_vehicle = implement_T_3dbox_object_list(T_true, infra_filtered)
        detector = CorrespondingDetector(
            infra_in_vehicle,
            veh_filtered,
            core_similarity_component="overall_distance",
            distance_threshold=threshold_dict,
            parallel=False,
            resolve_180_ambiguity=False,
        )
        if detector.get_matched_num() >= min_matches:
            selected_keys.append(key)

    selected_set = set(selected_keys)
    selected: List[Mapping[str, Any]] = []
    missing_records = 0
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        infra = _stem(str(entry.get("infrastructure_image_path", "")))
        veh = _stem(str(entry.get("vehicle_image_path", "")))
        if not infra or not veh:
            continue
        key = _pair_key(infra, veh)
        if key in selected_set:
            selected.append(entry)
    # Sanity: selected keys should all exist in raw (but order/duplicates may differ).
    if len(selected) != len(selected_set):
        missing_records = len(selected_set) - len(selected)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(selected, f, indent=2)

    print(f"[paper3737] data_info={data_info_path} total_pairs={len(raw)} nonzero_offset_pairs={nonzero_pairs}")
    print(
        "[paper3737] "
        f"criteria: top_k={args.top_k} distance_m={args.distance_m} categories={categories} "
        f"tau={tau} min_matches={min_matches}"
    )
    print(f"[paper3737] processed_pairs={processed} selected_pairs={len(selected)} missing_records={missing_records}")
    print(f"[paper3737] wrote: {out_path}")
    expected = int(args.expected) if args.expected is not None else None
    if expected is not None and expected > 0 and len(selected) != expected:
        print(f"[paper3737][warn] expected {expected} pairs but got {len(selected)}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

