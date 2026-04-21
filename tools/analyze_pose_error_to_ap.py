#!/usr/bin/env python3
"""
Analyze the relationship between registration quality and downstream coop-perception AP.

Input: long-format CSV emitted by tools/build_fullmatrix_benchmark_report.py
Output: JSON summary with:
  - Pearson correlations between AP50 and {success_at_2m, mean_rel_trans_m, mean_rel_yaw_deg}
  - A small linear model: ap50 ~= b0 + b1*success_at_2m + b2*mean_rel_yaw_deg

This script intentionally avoids numpy/pandas so it can run with the system python3.
"""

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _to_float(raw: object) -> Optional[float]:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.lower() == "none":
        return None
    try:
        return float(s)
    except Exception:
        return None


def _pearson(xs: List[float], ys: List[float]) -> Optional[float]:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    n = float(len(xs))
    sx = sum(xs)
    sy = sum(ys)
    sxx = sum(x * x for x in xs)
    syy = sum(y * y for y in ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    num = n * sxy - sx * sy
    den_x = n * sxx - sx * sx
    den_y = n * syy - sy * sy
    if den_x <= 0.0 or den_y <= 0.0:
        return None
    return float(num / math.sqrt(den_x * den_y))


def _solve_linear_3x3(A: List[List[float]], b: List[float]) -> Optional[List[float]]:
    """
    Solve A x = b for 3x3 A using Gauss-Jordan elimination.
    Returns x or None if singular.
    """
    if len(A) != 3 or any(len(row) != 3 for row in A) or len(b) != 3:
        return None
    # Augmented matrix [A | b]
    M = [list(map(float, row)) + [float(bi)] for row, bi in zip(A, b)]
    for col in range(3):
        # pivot
        pivot = None
        for r in range(col, 3):
            if abs(M[r][col]) > 1e-12:
                pivot = r
                break
        if pivot is None:
            return None
        if pivot != col:
            M[col], M[pivot] = M[pivot], M[col]
        # normalize pivot row
        pv = float(M[col][col])
        if abs(pv) <= 1e-12:
            return None
        inv = 1.0 / pv
        for j in range(col, 4):
            M[col][j] *= inv
        # eliminate other rows
        for r in range(3):
            if r == col:
                continue
            factor = float(M[r][col])
            if abs(factor) <= 1e-12:
                continue
            for j in range(col, 4):
                M[r][j] -= factor * M[col][j]
    return [float(M[i][3]) for i in range(3)]


def _fit_ap_from_success_and_yaw(records: List[dict]) -> Dict[str, object]:
    xs: List[Tuple[float, float]] = []
    ys: List[float] = []
    for r in records:
        ap = r.get("ap50")
        succ2 = r.get("success_at_2m")
        yaw = r.get("mean_rel_yaw_deg")
        if ap is None or succ2 is None or yaw is None:
            continue
        xs.append((float(succ2), float(yaw)))
        ys.append(float(ap))

    if len(ys) < 3:
        return {"n": int(len(ys)), "coef": None, "rmse": None}

    # Normal equations for y ~= b0 + b1*s + b2*yaw
    # Build X^T X (3x3) and X^T y (3,)
    s00 = float(len(xs))
    s01 = sum(s for s, _ in xs)
    s02 = sum(y for _, y in xs)
    s11 = sum(s * s for s, _ in xs)
    s12 = sum(s * y for s, y in xs)
    s22 = sum(y * y for _, y in xs)
    xtx = [
        [s00, s01, s02],
        [s01, s11, s12],
        [s02, s12, s22],
    ]
    xty = [
        sum(ys),
        sum(s * ap for (s, _), ap in zip(xs, ys)),
        sum(y * ap for (_, y), ap in zip(xs, ys)),
    ]
    coef = _solve_linear_3x3(xtx, xty)
    if coef is None:
        return {"n": int(len(ys)), "coef": None, "rmse": None}

    # RMSE
    se = 0.0
    for (s, y), ap in zip(xs, ys):
        pred = coef[0] + coef[1] * s + coef[2] * y
        se += float((pred - ap) ** 2)
    rmse = math.sqrt(se / float(len(ys)))
    return {"n": int(len(ys)), "coef": coef, "rmse": float(rmse)}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--csv", type=Path, required=True, help="combined_noise_curve_long.csv")
    p.add_argument("--out", type=Path, default=None, help="Output JSON path (default: alongside CSV).")
    args = p.parse_args()

    rows: List[dict] = []
    with args.csv.open("r", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(
                {
                    **r,
                    "ap50": _to_float(r.get("ap50")),
                    "mean_rel_trans_m": _to_float(r.get("mean_rel_trans_m")),
                    "mean_rel_yaw_deg": _to_float(r.get("mean_rel_yaw_deg")),
                    "success_at_2m": _to_float(r.get("success_at_2m")),
                }
            )

    groups: Dict[Tuple[str, str, str], List[dict]] = defaultdict(list)
    for r in rows:
        key = (str(r.get("dataset")), str(r.get("suite")), str(r.get("modality")))
        groups[key].append(r)

    summary = {"groups": []}
    for (dataset, suite, modality), recs in sorted(groups.items()):
        usable = [r for r in recs if r.get("ap50") is not None]
        # Correlations: filter per-field missing values.
        ap = [r["ap50"] for r in usable if r.get("ap50") is not None]
        rel_pairs = [(r["ap50"], r["mean_rel_trans_m"]) for r in usable if r.get("mean_rel_trans_m") is not None]
        succ_pairs = [(r["ap50"], r["success_at_2m"]) for r in usable if r.get("success_at_2m") is not None]
        yaw_pairs = [(r["ap50"], r["mean_rel_yaw_deg"]) for r in usable if r.get("mean_rel_yaw_deg") is not None]

        corr_rel = _pearson([a for a, _ in rel_pairs], [b for _, b in rel_pairs]) if rel_pairs else None
        corr_succ = _pearson([a for a, _ in succ_pairs], [b for _, b in succ_pairs]) if succ_pairs else None
        corr_yaw = _pearson([a for a, _ in yaw_pairs], [b for _, b in yaw_pairs]) if yaw_pairs else None

        fit = _fit_ap_from_success_and_yaw(usable)

        summary["groups"].append(
            {
                "dataset": dataset,
                "suite": suite,
                "modality": modality,
                "n_rows": int(len(recs)),
                "n_ap50": int(len(ap)),
                "pearson_ap50_mean_rel_trans_m": corr_rel,
                "pearson_ap50_success_at_2m": corr_succ,
                "pearson_ap50_mean_rel_yaw_deg": corr_yaw,
                "fit_ap50_from_success2m_and_yaw": fit,
            }
        )

    out = args.out or (args.csv.parent / "pose_error_to_ap_summary.json")
    out.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(str(out))


if __name__ == "__main__":
    main()

