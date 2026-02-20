#!/usr/bin/env python3
"""
Merge occ-map fields from an occ-exported stage1 cache into a base stage1 cache.

Use case:
- You already have a trusted stage1_boxes.json (boxes + poses) used by prior benchmarks.
- You want to enable V2X-Reg++ occ-hint/occ-pose by adding `occ_map_level0(_path)` without
  perturbing any existing box fields.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Tuple


def _resolve_stage1_path(path: Path) -> Path:
    path = Path(path)
    if path.is_dir():
        return path / "stage1_boxes.json"
    return path


def _load_json(path: Path) -> Dict[str, Any]:
    obj = json.loads(Path(path).read_text(encoding="utf-8", errors="ignore"))
    if not isinstance(obj, dict):
        raise TypeError(f"stage1 cache must be a JSON object (dict): {path} (got {type(obj)})")
    return obj


def _as_tuple_list(v: Any) -> Tuple[str, ...]:
    if not isinstance(v, list):
        return tuple()
    return tuple(str(x) for x in v)


def main() -> None:
    ap = argparse.ArgumentParser(description="Merge occ-map fields into a base stage1 cache.")
    ap.add_argument("--base-stage1", type=Path, required=True, help="Base stage1_boxes.json (or its parent dir).")
    ap.add_argument("--occ-stage1", type=Path, required=True, help="Occ-exported stage1 cache containing occ fields.")
    ap.add_argument("--out", type=Path, required=True, help="Output stage1_boxes.json path.")
    ap.add_argument(
        "--field",
        type=str,
        default="occ_map_level0_path",
        choices=["occ_map_level0_path", "occ_map_level0"],
        help="Which occ field to merge.",
    )
    ap.add_argument(
        "--allow-missing-keys",
        action="store_true",
        help="Allow base keys to be missing from occ-stage1 (fill empty occ for those keys).",
    )
    ap.add_argument(
        "--no-strict-cav",
        action="store_true",
        help="Disable strict cav_id_list equality check (not recommended).",
    )
    args = ap.parse_args()

    base_path = _resolve_stage1_path(args.base_stage1)
    occ_path = _resolve_stage1_path(args.occ_stage1)
    base = _load_json(base_path)
    occ = _load_json(occ_path)

    field = str(args.field)
    strict_cav = not bool(args.no_strict_cav)

    out: Dict[str, Any] = {}
    missing_keys = 0
    missing_field = 0
    cav_mismatch = 0
    for k, rec in base.items():
        if not isinstance(rec, dict):
            out[str(k)] = rec
            continue
        ok = occ.get(str(k))
        if ok is None:
            missing_keys += 1
            if not args.allow_missing_keys:
                raise SystemExit(f"Missing sample key in occ-stage1: {k} (occ={occ_path})")
            merged = dict(rec)
            merged[field] = []
            out[str(k)] = merged
            continue
        if not isinstance(ok, dict):
            missing_keys += 1
            if not args.allow_missing_keys:
                raise SystemExit(f"Invalid sample[{k}] in occ-stage1: expected dict, got {type(ok)}")
            merged = dict(rec)
            merged[field] = []
            out[str(k)] = merged
            continue

        if strict_cav:
            cav_base = _as_tuple_list(rec.get("cav_id_list"))
            cav_occ = _as_tuple_list(ok.get("cav_id_list"))
            if cav_base and cav_occ and cav_base != cav_occ:
                cav_mismatch += 1
                raise SystemExit(
                    f"cav_id_list mismatch for sample[{k}]: base={list(cav_base)} occ={list(cav_occ)}"
                )

        merged = dict(rec)
        if field in ok:
            merged[field] = ok.get(field)
        else:
            missing_field += 1
            merged[field] = []
        out[str(k)] = merged

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, sort_keys=True), encoding="utf-8")
    print(
        "Wrote merged stage1 cache: {} (samples={} missing_keys={} missing_field={} cav_mismatch={})".format(
            args.out, len(out), missing_keys, missing_field, cav_mismatch
        )
    )


if __name__ == "__main__":
    main()

