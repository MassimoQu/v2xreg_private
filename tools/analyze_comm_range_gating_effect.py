#!/usr/bin/env python3
"""
Analyze how comm-range pruning (clean vs noisy pose) can change the set of cooperating agents.

We approximate sensitivity using a stage1_boxes.json cache (because it contains per-sample clean poses):
  - For each sample, take ego pose (index 0) and non-ego poses (index>=1) from `lidar_pose_clean_np`.
  - Compute clean ego->non-ego distances.
  - Estimate, via Monte-Carlo, the probability that an in-range link (d<=R) becomes out-of-range after
    translation noise (dx,dy ~ N(0, sigma^2)) is added to non-ego agents (ego stays fixed; matches
    `--noise-target non-ego` in inference_w_noise.py).

This is NOT a full end-to-end AP analysis; it is an evidence tool to explain why some datasets
are more sensitive than others when `--comm-range-gating noisy` is used.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np


def _sorted_int_keys(d: Dict[str, Any]) -> List[str]:
    buf: List[Tuple[int, str]] = []
    for k in d.keys():
        try:
            buf.append((int(str(k)), str(k)))
        except Exception:
            continue
    buf.sort(key=lambda x: x[0])
    return [k for _, k in buf]


def _collect_rel_vectors(
    stage1: Dict[str, Any], *, comm_range: float, max_records: int
) -> Tuple[np.ndarray, Dict[str, float]]:
    keys = _sorted_int_keys(stage1)
    if max_records > 0:
        keys = keys[: int(max_records)]

    rel = []
    total_pairs = 0
    inrange_pairs = 0
    per_sample_pairs = []
    per_sample_inrange = []
    near_boundary = 0

    for k in keys:
        rec = stage1.get(k) or {}
        poses = rec.get("lidar_pose_clean_np") or []
        if not isinstance(poses, list) or len(poses) < 2:
            continue
        try:
            ex, ey = float(poses[0][0]), float(poses[0][1])
        except Exception:
            continue
        cnt = 0
        inr = 0
        for p in poses[1:]:
            try:
                x, y = float(p[0]), float(p[1])
            except Exception:
                continue
            dx, dy = x - ex, y - ey
            d = math.hypot(dx, dy)
            total_pairs += 1
            cnt += 1
            if abs(d - float(comm_range)) <= 5.0:
                near_boundary += 1
            if d <= float(comm_range):
                inrange_pairs += 1
                inr += 1
                rel.append((dx, dy))
        per_sample_pairs.append(cnt)
        per_sample_inrange.append(inr)

    rel_arr = np.asarray(rel, dtype=np.float32)
    dists = np.sqrt(rel_arr[:, 0] ** 2 + rel_arr[:, 1] ** 2) if rel_arr.size else np.asarray([], dtype=np.float32)
    d_sorted = np.sort(dists) if dists.size else dists

    def _q(p: float) -> float:
        if d_sorted.size == 0:
            return float("nan")
        idx = int(p * (d_sorted.size - 1))
        return float(d_sorted[idx])

    summary = {
        "records_used": float(len(per_sample_pairs)),
        "total_pairs": float(total_pairs),
        "inrange_pairs": float(inrange_pairs),
        "mean_pairs_per_record": float(sum(per_sample_pairs) / len(per_sample_pairs)) if per_sample_pairs else 0.0,
        "mean_inrange_pairs_per_record": float(sum(per_sample_inrange) / len(per_sample_inrange)) if per_sample_inrange else 0.0,
        "inrange_rate": float(inrange_pairs / total_pairs) if total_pairs else float("nan"),
        "near_boundary_rate_pm5m": float(near_boundary / total_pairs) if total_pairs else float("nan"),
        "dist_q10": _q(0.10),
        "dist_q50": _q(0.50),
        "dist_q90": _q(0.90),
        "dist_q95": _q(0.95),
        "dist_q99": _q(0.99),
    }
    return rel_arr, summary


def _dropout_rate_mc(rel_vecs: np.ndarray, *, comm_range: float, sigma: float, draws: int, seed: int) -> float:
    """
    MC estimate of P(||r + n|| > R | ||r||<=R) averaged over all rel vectors r.
    """
    if rel_vecs.size == 0:
        return float("nan")
    R = float(comm_range)
    rng = np.random.default_rng(int(seed))
    K = int(draws)
    N = rel_vecs.shape[0]
    dx = rel_vecs[:, 0][None, :]  # (1, N)
    dy = rel_vecs[:, 1][None, :]
    nx = rng.normal(0.0, float(sigma), size=(K, N)).astype(np.float32)
    ny = rng.normal(0.0, float(sigma), size=(K, N)).astype(np.float32)
    dist = np.sqrt((dx + nx) ** 2 + (dy + ny) ** 2)
    return float((dist > R).mean())


def main() -> None:
    ap = argparse.ArgumentParser(description="Analyze comm-range gating sensitivity from a stage1_boxes.json cache.")
    ap.add_argument("--stage1", type=Path, required=True, help="Path to stage1_boxes.json")
    ap.add_argument("--comm-range", type=float, default=70.0)
    ap.add_argument("--max-records", type=int, default=0, help="0=all; >0=head N records")
    ap.add_argument("--sigmas", type=str, default="1,2,3,4,5,6,7,8,9,10", help="Comma-separated pos_std values (meters)")
    ap.add_argument("--mc-draws", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    stage1_path = Path(args.stage1)
    obj = json.loads(stage1_path.read_text(encoding="utf-8", errors="ignore"))
    if not isinstance(obj, dict):
        raise SystemExit(f"Invalid stage1 json (expected dict): {stage1_path}")

    rel_vecs, summary = _collect_rel_vectors(obj, comm_range=float(args.comm_range), max_records=int(args.max_records))

    print("stage1:", str(stage1_path))
    print("comm_range:", float(args.comm_range))
    for k in sorted(summary.keys()):
        print(f"{k}: {summary[k]}")

    sigmas = []
    for tok in str(args.sigmas).split(","):
        tok = tok.strip()
        if not tok:
            continue
        sigmas.append(float(tok))
    if not sigmas:
        return

    print("\n[MC] in-range link dropout rate under translation noise (noise-target=non-ego)")
    for s in sigmas:
        p = _dropout_rate_mc(
            rel_vecs,
            comm_range=float(args.comm_range),
            sigma=float(s),
            draws=int(args.mc_draws),
            seed=int(args.seed),
        )
        print(f"sigma={s:g}m: dropout_rate~{p*100:.2f}% (draws={int(args.mc_draws)})")


if __name__ == "__main__":
    main()

