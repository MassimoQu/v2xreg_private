#!/usr/bin/env python3
"""
Validate HEAL/OpenCOOD stage1_boxes.json *semantic* convention.

Why this exists:
  Box-based pose solvers (V2X-Reg++/FreeAlign/VIPS/CBM) assume that
  `pred_corner3d_np_list[k]` is expressed in the *k-th agent's local frame*.

If a stage1 cache was exported in a common/ego/world frame, then:
  - identity alignment between agent boxes can look *better* than applying the
    physical relative pose from `lidar_pose_clean_np`;
  - pose solvers tend to estimate near-identity and mis-apply, producing huge
    rel_error_stats even at noise=0.

This validator samples entries and compares CorrespondingDetector match counts:
  matched(identity) vs matched(rel_clean).
If identity consistently beats rel_clean, the cache is almost certainly in a
common frame and is INVALID for core pose-correction benchmarks.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
HEAL = ROOT / "HEAL"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(HEAL) not in sys.path:
    sys.path.insert(0, str(HEAL))


def _resolve_stage1_path(path: Path) -> Path:
    path = Path(path)
    if path.is_dir():
        return path / "stage1_boxes.json"
    return path


def _maybe_head200(path: Path, *, prefer_head200: bool) -> Tuple[Path, Optional[Path]]:
    """
    Returns:
      (semantic_path, original_path_if_swapped)
    """
    if not prefer_head200:
        return path, None
    if path.name != "stage1_boxes.json":
        return path, None
    head = path.with_name("stage1_boxes_head200.json")
    if head.exists():
        return head, path
    return path, None


def _sorted_sample_keys(stage1: Dict[str, Any]) -> List[str]:
    keys = list(stage1.keys())
    int_keys: List[Tuple[int, str]] = []
    other: List[str] = []
    for k in keys:
        ks = str(k)
        try:
            int_keys.append((int(ks), ks))
        except Exception:
            other.append(ks)
    int_keys.sort(key=lambda x: x[0])
    other.sort()
    return [ks for _, ks in int_keys] + other


def _pick_keys(
    stage1: Dict[str, Any],
    *,
    sample_mode: str,
    num_samples: int,
    seed: int,
    sample_keys: Optional[Sequence[str]] = None,
) -> List[str]:
    if sample_keys:
        out = []
        for k in sample_keys:
            ks = str(k)
            if ks in stage1:
                out.append(ks)
        return out

    keys = _sorted_sample_keys(stage1)
    n = max(1, int(num_samples))
    if not keys:
        return []
    mode = str(sample_mode or "head").lower().strip()
    if mode == "random":
        rng = random.Random(int(seed))
        if len(keys) <= n:
            return keys
        return sorted(rng.sample(keys, n), key=lambda x: int(x) if str(x).isdigit() else x)
    # default: head
    return keys[:n]


def _as_array(corners_like: Any) -> Optional[np.ndarray]:
    if corners_like is None:
        return None
    arr = np.asarray(corners_like, dtype=np.float64)
    if arr.size == 0:
        return None
    if arr.ndim != 3 or arr.shape[1:] != (8, 3):
        # stage1 JSON is often list[list[list]]; enforce (N,8,3)
        try:
            arr = arr.reshape(-1, 8, 3)
        except Exception:
            return None
    return arr


@dataclass(frozen=True)
class SampleSemanticRow:
    sample_key: str
    matched_identity: int
    matched_rel_clean: int
    precision_identity: float
    precision_rel_clean: float

    @property
    def delta(self) -> int:
        return int(self.matched_rel_clean) - int(self.matched_identity)


@dataclass(frozen=True)
class SemanticSummary:
    ok: bool
    valid_samples: int
    inverted_samples: int
    total_matched_identity: int
    total_matched_rel_clean: int
    match_ratio_rel_over_id: float
    inverted_rate: float
    rows: Tuple[SampleSemanticRow, ...]
    note: str = ""


def check_stage1_semantics_dict(
    stage1: Dict[str, Any],
    *,
    keys: Sequence[str],
    ref_idx: int = 0,
    src_idx: int = 1,
    corners_field: str = "pred_corner3d_np_list",
    pose_clean_field: str = "lidar_pose_clean_np",
    bbox_type: str = "detected",
    distance_threshold_m: float = 3.0,
    min_valid_samples: int = 5,
    fail_if_inverted_rate_ge: float = 0.6,
    fail_if_match_ratio_lt: float = 0.95,
) -> SemanticSummary:
    """
    Semantic gate:
      if identity alignment matches significantly better than rel_clean alignment,
      the stage1 cache is likely in a common frame and should be rejected.
    """
    # Heavy imports are kept inside the function to keep module import light.
    from opencood.extrinsics.bbox_utils import corners_to_bbox3d_list
    from opencood.utils.transformation_utils import pose_to_tfm
    from v2x_calib.corresponding import CorrespondingDetector
    from v2x_calib.utils import implement_T_3dbox_object_list

    rows: List[SampleSemanticRow] = []
    inverted = 0
    total_id = 0
    total_rel = 0

    th = {str(bbox_type or "detected"): float(distance_threshold_m)}
    for k in keys:
        rec = stage1.get(str(k))
        if not isinstance(rec, dict):
            continue

        corners_all = rec.get(corners_field) or []
        poses_clean = rec.get(pose_clean_field) or []
        if not isinstance(corners_all, list) or not isinstance(poses_clean, list):
            continue
        if len(corners_all) <= max(ref_idx, src_idx):
            continue
        if len(poses_clean) <= max(ref_idx, src_idx):
            continue

        ref_c = _as_array(corners_all[ref_idx])
        src_c = _as_array(corners_all[src_idx])
        if ref_c is None or src_c is None:
            continue

        try:
            boxes_ref = corners_to_bbox3d_list(ref_c, bbox_type=str(bbox_type or "detected"))
            boxes_src = corners_to_bbox3d_list(src_c, bbox_type=str(bbox_type or "detected"))
        except Exception:
            continue
        if not boxes_ref or not boxes_src:
            continue

        try:
            poses = np.asarray(poses_clean, dtype=np.float64)
            T_world = pose_to_tfm(poses)  # agent->world
            rel_clean = np.linalg.inv(T_world[int(ref_idx)]) @ T_world[int(src_idx)]  # src->ref
        except Exception:
            continue

        try:
            det_id = CorrespondingDetector(boxes_src, boxes_ref, distance_threshold=th)
            aligned_src = implement_T_3dbox_object_list(rel_clean, boxes_src)
            det_rel = CorrespondingDetector(aligned_src, boxes_ref, distance_threshold=th)
            matched_id = int(det_id.get_matched_num())
            matched_rel = int(det_rel.get_matched_num())
            prec_id = float(det_id.get_distance_corresponding_precision())
            prec_rel = float(det_rel.get_distance_corresponding_precision())
        except Exception:
            continue

        total_id += matched_id
        total_rel += matched_rel
        if matched_rel < matched_id:
            inverted += 1
        rows.append(
            SampleSemanticRow(
                sample_key=str(k),
                matched_identity=matched_id,
                matched_rel_clean=matched_rel,
                precision_identity=prec_id,
                precision_rel_clean=prec_rel,
            )
        )

    valid = len(rows)
    if valid == 0:
        return SemanticSummary(
            ok=False,
            valid_samples=0,
            inverted_samples=0,
            total_matched_identity=0,
            total_matched_rel_clean=0,
            match_ratio_rel_over_id=0.0,
            inverted_rate=0.0,
            rows=tuple(),
            note="no_valid_samples (no boxes/poses in sampled entries)",
        )

    ratio = float(total_rel / max(1, total_id))
    inv_rate = float(inverted / valid)
    # Fail only when we have enough evidence + the pattern is strong.
    ok = True
    note = ""
    if valid < int(min_valid_samples):
        ok = False
        note = f"insufficient_valid_samples: valid={valid} < min_valid_samples={int(min_valid_samples)}"
    else:
        if inv_rate >= float(fail_if_inverted_rate_ge) and ratio < float(fail_if_match_ratio_lt):
            ok = False
            note = "identity_beats_rel_clean (likely common-frame stage1 cache)"

    return SemanticSummary(
        ok=ok,
        valid_samples=valid,
        inverted_samples=int(inverted),
        total_matched_identity=int(total_id),
        total_matched_rel_clean=int(total_rel),
        match_ratio_rel_over_id=float(ratio),
        inverted_rate=float(inv_rate),
        rows=tuple(rows),
        note=note,
    )


def _parse_csv(value: str) -> List[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate stage1_boxes.json semantic frame convention (per-CAV expected).")
    ap.add_argument("--stage1", type=Path, required=True, help="Path to stage1_boxes.json (or its parent directory).")
    ap.add_argument("--prefer-head200", action="store_true", help="If stage1_boxes_head200.json exists, use it for semantic check.")
    ap.add_argument("--expected-samples", type=int, default=None, help="Optional expected number of samples (structural sanity only).")
    ap.add_argument("--sample-mode", type=str, default="head", choices=["head", "random"])
    ap.add_argument("--num-samples", type=int, default=20)
    ap.add_argument("--seed", type=int, default=303)
    ap.add_argument("--sample-keys", type=str, default="", help="Optional comma-separated explicit sample keys to check.")
    ap.add_argument("--ref-idx", type=int, default=0)
    ap.add_argument("--src-idx", type=int, default=1)
    ap.add_argument("--bbox-type", type=str, default="detected")
    ap.add_argument("--distance-threshold-m", type=float, default=3.0)
    ap.add_argument("--min-valid-samples", type=int, default=5)
    ap.add_argument("--fail-if-inverted-rate-ge", type=float, default=0.6)
    ap.add_argument("--fail-if-match-ratio-lt", type=float, default=0.95)
    ap.add_argument("--max-print-rows", type=int, default=8)
    args = ap.parse_args()

    stage1_path = _resolve_stage1_path(args.stage1)
    semantic_path, swapped_from = _maybe_head200(stage1_path, prefer_head200=bool(args.prefer_head200))
    if not semantic_path.exists():
        raise SystemExit(f"[FAIL] stage1 cache not found: {semantic_path}")

    try:
        stage1 = json.loads(semantic_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise SystemExit(f"[FAIL] failed to parse JSON: {semantic_path} ({e})")
    if not isinstance(stage1, dict):
        raise SystemExit(f"[FAIL] stage1 cache must be a dict: {semantic_path} (got {type(stage1)})")

    if args.expected_samples is not None and int(args.expected_samples) > 0:
        if len(stage1) != int(args.expected_samples):
            raise SystemExit(
                f"[FAIL] sample_count_mismatch: expected={int(args.expected_samples)} actual={len(stage1)} path={semantic_path}"
            )

    keys = _pick_keys(
        stage1,
        sample_mode=str(args.sample_mode),
        num_samples=int(args.num_samples),
        seed=int(args.seed),
        sample_keys=_parse_csv(args.sample_keys),
    )
    summary = check_stage1_semantics_dict(
        stage1,
        keys=keys,
        ref_idx=int(args.ref_idx),
        src_idx=int(args.src_idx),
        bbox_type=str(args.bbox_type),
        distance_threshold_m=float(args.distance_threshold_m),
        min_valid_samples=int(args.min_valid_samples),
        fail_if_inverted_rate_ge=float(args.fail_if_inverted_rate_ge),
        fail_if_match_ratio_lt=float(args.fail_if_match_ratio_lt),
    )

    header = "[OK]" if summary.ok else "[FAIL]"
    print(f"{header} stage1 semantic check: {semantic_path} (samples={len(stage1)})")
    if swapped_from is not None:
        print(f"  note: used head200 for semantic check (original={swapped_from})")
    print(
        "  valid_samples={} inverted_samples={} inverted_rate={:.3f} total_matched_id={} total_matched_rel={} ratio_rel_over_id={:.3f}".format(
            summary.valid_samples,
            summary.inverted_samples,
            summary.inverted_rate,
            summary.total_matched_identity,
            summary.total_matched_rel_clean,
            summary.match_ratio_rel_over_id,
        )
    )
    if summary.note:
        print("  note:", summary.note)

    max_rows = max(0, int(args.max_print_rows))
    for row in summary.rows[:max_rows]:
        print(
            "  sample[{}]: matched id={} rel={} delta={} | prec id={:.3f} rel={:.3f}".format(
                row.sample_key,
                row.matched_identity,
                row.matched_rel_clean,
                row.delta,
                row.precision_identity,
                row.precision_rel_clean,
            )
        )

    if not summary.ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
