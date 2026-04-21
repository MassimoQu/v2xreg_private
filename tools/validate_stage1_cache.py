#!/usr/bin/env python3
"""
Validate HEAL/OpenCOOD stage1_boxes.json structural integrity.

This is a hard preflight gate for pose-correction benchmarks:
- OPV2V fullbench expects per-sample, per-agent lists where:
    len(cav_id_list) == len(pred_corner3d_np_list)
  (and usually len(lidar_pose_clean_np) matches too).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional


def resolve_stage1_path(path: Path) -> Path:
    path = Path(path)
    if path.is_dir():
        return path / "stage1_boxes.json"
    return path


def _parse_csv(value: str) -> List[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def load_stage1(path: Path) -> Dict[str, dict]:
    path = resolve_stage1_path(path)
    if not path.exists():
        raise FileNotFoundError(f"stage1 cache not found: {path}")
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise TypeError(f"stage1 cache must be a JSON object (dict), got {type(obj)} in {path}")
    return obj


def validate_stage1_dict(
    stage1: Dict[str, dict],
    *,
    expected_samples: Optional[int] = None,
    require_fields: Iterable[str] = (),
    require_contiguous_keys: bool = False,
    check_pose_len: bool = True,
    max_errors: int = 20,
) -> List[str]:
    errors: List[str] = []

    if expected_samples is not None and len(stage1) != int(expected_samples):
        errors.append(f"sample_count_mismatch: expected={expected_samples} actual={len(stage1)}")

    if require_contiguous_keys and expected_samples is not None:
        missing = []
        for i in range(int(expected_samples)):
            if str(i) not in stage1:
                missing.append(i)
                if len(missing) >= 10:
                    break
        if missing:
            errors.append(f"missing_sample_keys: first_missing={missing[:10]}")

    for sample_idx, rec in stage1.items():
        if not isinstance(rec, dict):
            errors.append(f"sample[{sample_idx}]: expected dict, got {type(rec)}")
            if len(errors) >= max_errors:
                break
            continue

        for f in require_fields:
            if f not in rec:
                errors.append(f"sample[{sample_idx}]: missing field {f}")
                if len(errors) >= max_errors:
                    break
        if len(errors) >= max_errors:
            break

        cav = rec.get("cav_id_list")
        pred = rec.get("pred_corner3d_np_list")
        if cav is not None and pred is not None:
            try:
                cav_len = len(cav)
                pred_len = len(pred)
            except Exception:
                errors.append(f"sample[{sample_idx}]: cav_id_list/pred_corner3d_np_list not sized")
                if len(errors) >= max_errors:
                    break
                continue
            if cav_len != pred_len:
                errors.append(
                    f"sample[{sample_idx}]: len(cav_id_list)={cav_len} != len(pred_corner3d_np_list)={pred_len}"
                )
                if len(errors) >= max_errors:
                    break

            if check_pose_len:
                clean_pose = rec.get("lidar_pose_clean_np")
                if clean_pose is not None:
                    try:
                        pose_len = len(clean_pose)
                    except Exception:
                        errors.append(f"sample[{sample_idx}]: lidar_pose_clean_np not sized")
                        if len(errors) >= max_errors:
                            break
                    else:
                        if pose_len != cav_len:
                            errors.append(
                                f"sample[{sample_idx}]: len(lidar_pose_clean_np)={pose_len} != len(cav_id_list)={cav_len}"
                            )
                            if len(errors) >= max_errors:
                                break

    return errors


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate stage1_boxes.json structural integrity.")
    ap.add_argument("--stage1", type=Path, required=True, help="Path to stage1_boxes.json (or its parent directory).")
    ap.add_argument("--expected-samples", type=int, default=None, help="Expected number of samples (e.g., OPV2V test=2170).")
    ap.add_argument(
        "--require-fields",
        type=str,
        default="pred_corner3d_np_list,cav_id_list,lidar_pose_clean_np",
        help="Comma-separated required fields per sample.",
    )
    ap.add_argument("--require-contiguous-keys", action="store_true", help="Require sample keys '0..N-1' to exist.")
    ap.add_argument("--no-pose-len-check", action="store_true", help="Skip lidar_pose_clean_np length check.")
    ap.add_argument("--max-errors", type=int, default=20)
    args = ap.parse_args()

    stage1_path = resolve_stage1_path(args.stage1)
    stage1 = load_stage1(stage1_path)
    errors = validate_stage1_dict(
        stage1,
        expected_samples=args.expected_samples,
        require_fields=_parse_csv(args.require_fields),
        require_contiguous_keys=bool(args.require_contiguous_keys),
        check_pose_len=not bool(args.no_pose_len_check),
        max_errors=int(args.max_errors),
    )

    if errors:
        print(f"[FAIL] stage1 cache invalid: {stage1_path}")
        for e in errors:
            print(" -", e)
        raise SystemExit(1)

    print(f"[OK] stage1 cache valid: {stage1_path} (samples={len(stage1)})")


if __name__ == "__main__":
    main()

