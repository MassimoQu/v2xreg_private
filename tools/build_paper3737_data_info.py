#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple


def _stem(path_str: str | None) -> str:
    if not path_str:
        return ""
    name = str(path_str).replace("\\", "/").split("/")[-1]
    return name.split(".")[0] if "." in name else name


def _scene_key(infra_id: str, veh_id: str) -> str:
    return f"{infra_id}-{veh_id}"


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _cooperative_root(dataset_root: Path) -> Path:
    dataset_root = dataset_root.expanduser().resolve()
    if (dataset_root / "cooperative").is_dir():
        return dataset_root / "cooperative"
    candidate = dataset_root / "cooperative-vehicle-infrastructure" / "cooperative"
    if candidate.is_dir():
        return candidate
    raise FileNotFoundError(
        f"Could not find cooperative folder under: {dataset_root} (expected cooperative/ or cooperative-vehicle-infrastructure/cooperative/)"
    )


def _load_exclude_keys(paths: Sequence[Path]) -> Set[str]:
    keys: Set[str] = set()
    for p in paths:
        if not p.exists():
            continue
        obj = _load_json(p)
        if not isinstance(obj, list):
            continue
        for row in obj:
            if not isinstance(row, Mapping):
                continue
            infra = str(row.get("infra_file_name") or "")
            veh = str(row.get("vehicle_file_name") or "")
            if infra and veh:
                keys.add(_scene_key(infra, veh))
    return keys


def build_paper3737(
    *,
    dataset_root: Path,
    metric_path: Path,
    full_data_info_path: Path,
    target_size: int,
    min_common_boxes: int,
    exclude_paths: Sequence[Path],
) -> List[Mapping[str, Any]]:
    metrics = _load_json(metric_path)
    if not isinstance(metrics, list):
        raise ValueError(f"metrics must be a list, got {type(metrics)} from {metric_path}")

    full = _load_json(full_data_info_path)
    if not isinstance(full, list):
        raise ValueError(f"full data_info must be a list, got {type(full)} from {full_data_info_path}")

    full_by_key: Dict[str, Mapping[str, Any]] = {}
    dup = 0
    for item in full:
        if not isinstance(item, Mapping):
            continue
        infra_id = _stem(str(item.get("infrastructure_pointcloud_path") or item.get("infrastructure_image_path") or ""))
        veh_id = _stem(str(item.get("vehicle_pointcloud_path") or item.get("vehicle_image_path") or ""))
        if not infra_id or not veh_id:
            continue
        key = _scene_key(infra_id, veh_id)
        if key in full_by_key:
            dup += 1
        full_by_key[key] = item

    exclude_keys = _load_exclude_keys(exclude_paths)

    candidates: List[Tuple[int, str, str]] = []
    for row in metrics:
        if not isinstance(row, Mapping):
            continue
        infra = str(row.get("infra_file_name") or "")
        veh = str(row.get("vehicle_file_name") or "")
        if not infra or not veh:
            continue
        try:
            common = int(row.get("common_boxes_num") or 0)
        except Exception:
            common = 0
        if common < int(min_common_boxes):
            continue
        key = _scene_key(infra, veh)
        if key in exclude_keys:
            continue
        candidates.append((common, infra, veh))

    # Prefer more common objects; stable tie-break by ids for reproducibility.
    candidates.sort(key=lambda x: (-x[0], x[1], x[2]))

    selected: List[Mapping[str, Any]] = []
    used: Set[str] = set()
    missing = 0
    for common, infra, veh in candidates:
        if len(selected) >= int(target_size):
            break
        key = _scene_key(infra, veh)
        if key in used:
            continue
        item = full_by_key.get(key)
        if item is None:
            missing += 1
            continue
        selected.append(item)
        used.add(key)

    if len(selected) < int(target_size):
        raise RuntimeError(
            f"Could not build target_size={target_size} (got {len(selected)}). "
            f"candidates={len(candidates)} missing_in_full={missing} dup_in_full={dup} "
            f"exclude_keys={len(exclude_keys)}"
        )

    return selected


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build DAIR-V2X paper3737 subset data_info.json (best-effort).")
    p.add_argument(
        "--dataset-root",
        default="data/DAIR-V2X/cooperative-vehicle-infrastructure",
        help="Path to cooperative-vehicle-infrastructure (symlink is fine).",
    )
    p.add_argument(
        "--metric",
        default="legacy/v2x_calib/dataset_division/common_boxes_num_scenes_list.json",
        help="Scene-level metric list containing common_boxes_num.",
    )
    p.add_argument(
        "--full-data-info",
        default=None,
        help="Full cooperative data_info.json (defaults to <dataset-root>/cooperative/data_info.json).",
    )
    p.add_argument("--target-size", type=int, default=3737, help="Number of frames to select.")
    p.add_argument(
        "--min-common-boxes",
        type=int,
        default=1,
        help="Only keep scenes with at least this many common boxes (default: 1).",
    )
    p.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Optional scene list json (entries with infra_file_name/vehicle_file_name) to exclude; repeatable.",
    )
    p.add_argument(
        "--out",
        default="data/data_info_dair_paper3737.json",
        help="Output JSON list path.",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]

    dataset_root = Path(args.dataset_root)
    if not dataset_root.is_absolute():
        dataset_root = (repo_root / dataset_root).resolve()
    coop_root = _cooperative_root(dataset_root)

    metric_path = Path(args.metric)
    if not metric_path.is_absolute():
        metric_path = (repo_root / metric_path).resolve()

    full_data_info_path = Path(args.full_data_info) if args.full_data_info else coop_root / "data_info.json"
    if not full_data_info_path.is_absolute():
        full_data_info_path = (repo_root / full_data_info_path).resolve()

    exclude_paths = [Path(p) for p in (args.exclude or [])]
    exclude_paths = [(repo_root / p).resolve() if not p.is_absolute() else p for p in exclude_paths]

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = (repo_root / out_path).resolve()

    selected = build_paper3737(
        dataset_root=dataset_root,
        metric_path=metric_path,
        full_data_info_path=full_data_info_path,
        target_size=int(args.target_size),
        min_common_boxes=int(args.min_common_boxes),
        exclude_paths=exclude_paths,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(selected, f, indent=2)

    print(f"[paper3737] wrote {len(selected)} entries to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

