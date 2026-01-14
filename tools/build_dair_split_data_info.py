#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping


def _extract_frame_id(path: str | None) -> str:
    if not path:
        return ''
    stem = str(path).replace('\\', '/').split('/')[-1]
    if '.' in stem:
        stem = stem.split('.')[0]
    return stem


def _load_json(path: Path) -> Any:
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def _cooperative_root(dataset_root: Path) -> Path:
    dataset_root = dataset_root.expanduser().resolve()
    if (dataset_root / 'cooperative').is_dir():
        return dataset_root / 'cooperative'
    candidate = dataset_root / 'cooperative-vehicle-infrastructure' / 'cooperative'
    if candidate.is_dir():
        return candidate
    raise FileNotFoundError(
        f"Could not find cooperative folder under: {dataset_root} (expected cooperative/ or cooperative-vehicle-infrastructure/cooperative/)"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description='Build split-specific data_info.json for DAIR-V2X-C.')
    parser.add_argument(
        '--dataset-root',
        type=str,
        default='data/DAIR-V2X/cooperative-vehicle-infrastructure',
        help='Path to cooperative-vehicle-infrastructure (symlink is fine).',
    )
    parser.add_argument(
        '--split',
        type=str,
        default='val',
        choices=['train', 'val'],
        help='Which split list to use (train.json or val.json).',
    )
    parser.add_argument(
        '--full-data-info',
        type=str,
        default=None,
        help='Path to full cooperative data_info.json (defaults to <dataset-root>/cooperative/data_info.json).',
    )
    parser.add_argument(
        '--split-list',
        type=str,
        default=None,
        help='Path to split id list json (defaults to <dataset-root>/(train|val).json).',
    )
    parser.add_argument(
        '--out',
        type=str,
        default=None,
        help='Output JSON path (defaults to data/DAIR-V2X/cooperative/<split>_data_info.json).',
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    dataset_root = Path(args.dataset_root)
    if not dataset_root.is_absolute():
        dataset_root = (repo_root / dataset_root).resolve()

    coop_root = _cooperative_root(dataset_root)
    full_data_info_path = Path(args.full_data_info) if args.full_data_info else coop_root / 'data_info.json'
    split_list_path = Path(args.split_list) if args.split_list else dataset_root / f'{args.split}.json'

    if not full_data_info_path.is_absolute():
        full_data_info_path = (repo_root / full_data_info_path).resolve()
    if not split_list_path.is_absolute():
        split_list_path = (repo_root / split_list_path).resolve()

    out_path: Path
    if args.out:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = (repo_root / out_path).resolve()
    else:
        out_path = (repo_root / 'data' / 'DAIR-V2X' / 'cooperative' / f'{args.split}_data_info.json').resolve()

    full = _load_json(full_data_info_path)
    if not isinstance(full, list):
        raise ValueError(f"full data_info must be a list, got {type(full)} from {full_data_info_path}")

    split_ids = _load_json(split_list_path)
    if not isinstance(split_ids, list) or not all(isinstance(x, str) for x in split_ids):
        raise ValueError(f"split list must be a list[str], got {type(split_ids)} from {split_list_path}")

    lookup: Dict[str, Mapping[str, Any]] = {}
    dup = 0
    for item in full:
        if not isinstance(item, Mapping):
            continue
        veh_path = item.get('vehicle_image_path') or item.get('vehicle_pointcloud_path')
        veh_id = _extract_frame_id(str(veh_path) if veh_path else None)
        if not veh_id:
            continue
        if veh_id in lookup:
            dup += 1
        # Keep the last occurrence to match OpenCOOD/HEAL DAIR-V2X loader behaviour.
        lookup[veh_id] = item

    missing: List[str] = []
    selected: List[Mapping[str, Any]] = []
    for veh_id in split_ids:
        item = lookup.get(veh_id)
        if item is None:
            missing.append(veh_id)
            continue
        selected.append(item)

    print(f"[split] {args.split} ids={len(split_ids)} selected={len(selected)} missing={len(missing)} dup_in_full={dup}")
    if missing:
        print('[missing] first 20:', missing[:20])
        raise SystemExit(1)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open('w', encoding='utf-8') as f:
        json.dump(selected, f, indent=2)
    print(f"[write] {out_path}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
