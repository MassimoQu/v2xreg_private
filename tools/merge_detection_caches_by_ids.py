#!/usr/bin/env python3
"""
Merge multiple detection cache JSONs into a single ID-keyed mapping.

Why: train/val caches are typically index-aligned (0..N) and will collide if
merged naively. The calibration pipeline can resolve records by
"<infra>_<veh>" when frame IDs are stored in each record.

Example:
  python tools/merge_detection_caches_by_ids.py \\
    --subset data/data_info_dair_paper3737.json \\
    --out data/DAIR-V2X/detected/veh_rsu_dual_ft_detection_cache_paper3737_trainval.json \\
    data/DAIR-V2X/detected/veh_rsu_dual_ft_detection_cache_valsplit.json \\
    data/DAIR-V2X/detected/veh_rsu_dual_ft_detection_cache_trainsplit.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional, Set, Tuple


def _extract_frame_id(path: str | None) -> str:
    if not path:
        return ''
    stem = str(path).replace('\\', '/').split('/')[-1]
    if '.' in stem:
        stem = stem.split('.')[0]
    return stem


def _pair_key(infra_id: str, veh_id: str) -> str:
    return f"{infra_id}_{veh_id}"


def _record_ids(record: Mapping[str, Any]) -> Tuple[str, str]:
    infra = record.get('infra_frame_id') or record.get('infra_id') or ''
    veh = record.get('veh_frame_id') or record.get('veh_id') or ''
    return str(infra), str(veh)


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"JSON not found: {path}")
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def _iter_records(obj: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(obj, list):
        for entry in obj:
            if isinstance(entry, Mapping):
                yield entry
        return
    if isinstance(obj, Mapping):
        for entry in obj.values():
            if isinstance(entry, Mapping):
                yield entry
        return
    raise ValueError(f"Detection cache must be a dict or list, got {type(obj)}")


def _load_subset_keys(path: Path) -> Set[str]:
    raw = _load_json(path)
    if not isinstance(raw, list):
        raise ValueError(f"subset must be a JSON list, got {type(raw)}")
    keys: Set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        infra_path = item.get('infrastructure_pointcloud_path') or item.get('infrastructure_image_path')
        veh_path = item.get('vehicle_pointcloud_path') or item.get('vehicle_image_path')
        infra_id = _extract_frame_id(str(infra_path) if infra_path else None)
        veh_id = _extract_frame_id(str(veh_path) if veh_path else None)
        if infra_id and veh_id:
            keys.add(_pair_key(infra_id, veh_id))
    if not keys:
        raise ValueError(f"No valid pairs found in subset file: {path}")
    return keys


def merge_caches(
    inputs: list[Path],
    subset_keys: Optional[Set[str]],
) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    seen_sources: Dict[str, str] = {}
    dropped_missing_ids = 0
    dropped_outside_subset = 0
    overridden = 0
    total_records = 0
    for path in inputs:
        raw = _load_json(path)
        for record in _iter_records(raw):
            total_records += 1
            infra_id, veh_id = _record_ids(record)
            if not infra_id or not veh_id:
                dropped_missing_ids += 1
                continue
            key = _pair_key(infra_id, veh_id)
            if subset_keys is not None and key not in subset_keys:
                dropped_outside_subset += 1
                continue
            if key in merged:
                overridden += 1
            merged[key] = record
            seen_sources[key] = str(path)
    print(f"inputs={len(inputs)} total_records_scanned={total_records}")
    print(f"merged_pairs={len(merged)} overridden={overridden}")
    print(f"dropped_missing_ids={dropped_missing_ids} dropped_outside_subset={dropped_outside_subset}")
    return merged


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge detection caches by <infra>_<veh> ID key.")
    parser.add_argument(
        'inputs',
        nargs='+',
        help='One or more detection cache JSON files (dict or list format).',
    )
    parser.add_argument('--subset', type=str, default=None, help='Optional data_info list to filter to (e.g. paper3737).')
    parser.add_argument('--out', required=True, help='Output JSON path for merged mapping.')
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    inputs = [Path(p) for p in args.inputs]
    subset_keys = _load_subset_keys(Path(args.subset)) if args.subset else None
    merged = merge_caches(inputs, subset_keys=subset_keys)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open('w', encoding='utf-8') as f:
        json.dump(merged, f, indent=2)
    print(f"Wrote {len(merged)} merged pairs to {out_path}")


if __name__ == '__main__':
    main()


