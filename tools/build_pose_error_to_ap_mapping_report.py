#!/usr/bin/env python3
"""
Build a reproducible report that links registration quality metrics to downstream coop-perception AP.

Inputs:
  - long-format CSV (default: outputs/benchmark_fullmatrix_20260220/combined_noise_curve_long.csv)
    Each row corresponds to one (dataset, suite, modality, method, strategy, noise) point and
    includes ap50 + registration stats (success_at_2m, mean_rel_trans_m, mean_rel_yaw_deg).

Outputs (under --out-dir):
  - mapping_summary.json: per-group correlations + linear fit coefficients + errors
  - pred_points.csv: per-point actual/pred AP50
  - plots/*.png: quick visuals (actual-vs-pred scatter)

Design goals:
  - Minimal dependencies (csv/json/math). Plots require matplotlib (optional).
  - Keep the mapping simple and inspectable:
      ap50 ~= b0 + b1*success_at_2m + b2*mean_rel_yaw_deg
"""

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


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


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    n = float(len(xs))
    sx = float(sum(xs))
    sy = float(sum(ys))
    sxx = float(sum(x * x for x in xs))
    syy = float(sum(y * y for y in ys))
    sxy = float(sum(x * y for x, y in zip(xs, ys)))
    num = n * sxy - sx * sy
    den_x = n * sxx - sx * sx
    den_y = n * syy - sy * sy
    if den_x <= 0.0 or den_y <= 0.0:
        return None
    return float(num / math.sqrt(den_x * den_y))


def _solve_linear_3x3(A: List[List[float]], b: List[float]) -> Optional[List[float]]:
    if len(A) != 3 or any(len(row) != 3 for row in A) or len(b) != 3:
        return None
    M = [list(map(float, row)) + [float(bi)] for row, bi in zip(A, b)]
    for col in range(3):
        pivot = None
        for r in range(col, 3):
            if abs(M[r][col]) > 1e-12:
                pivot = r
                break
        if pivot is None:
            return None
        if pivot != col:
            M[col], M[pivot] = M[pivot], M[col]
        pv = float(M[col][col])
        if abs(pv) <= 1e-12:
            return None
        inv = 1.0 / pv
        for j in range(col, 4):
            M[col][j] *= inv
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

    se = 0.0
    for (s, y), ap in zip(xs, ys):
        pred = coef[0] + coef[1] * s + coef[2] * y
        se += float((pred - ap) ** 2)
    rmse = math.sqrt(se / float(len(ys)))
    return {"n": int(len(ys)), "coef": coef, "rmse": float(rmse)}


def _group_key(r: dict) -> Tuple[str, str, str]:
    return (str(r.get("dataset")), str(r.get("suite")), str(r.get("modality")))


def _method_key(r: dict) -> Tuple[str, str]:
    return (str(r.get("method")), str(r.get("strategy")))


def _try_plot_scatter(points: List[dict], out_png: Path, title: str) -> None:
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return

    xs = [float(p["ap50_pred"]) for p in points]
    ys = [float(p["ap50"]) for p in points]
    if not xs or not ys:
        return

    mn = min(xs + ys)
    mx = max(xs + ys)
    pad = 0.02 * (mx - mn) if mx > mn else 0.01
    lo = mn - pad
    hi = mx + pad

    plt.figure(figsize=(5, 5), dpi=160)
    plt.scatter(xs, ys, s=10, alpha=0.6)
    plt.plot([lo, hi], [lo, hi], "k--", linewidth=1)
    plt.xlim(lo, hi)
    plt.ylim(lo, hi)
    plt.xlabel("Pred AP50")
    plt.ylabel("Actual AP50")
    plt.title(title)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(str(out_png))
    plt.close()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--csv",
        type=Path,
        default=Path("outputs/benchmark_fullmatrix_20260220/combined_noise_curve_long.csv"),
        help="Long-format combined curve CSV.",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=Path("outputs/pose_error_to_ap_mapping_report_20260224"),
        help="Output directory.",
    )
    p.add_argument(
        "--methods",
        type=str,
        default="baseline,oracle,v2xregpp,freealign,vips,cbm",
        help="Comma-separated methods to include.",
    )
    args = p.parse_args()

    methods = {m.strip() for m in str(args.methods).split(",") if m.strip()}
    rows: List[dict] = []
    with args.csv.open("r", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("method") not in methods:
                continue
            rows.append(
                {
                    **r,
                    "noise": _to_float(r.get("noise")),
                    "ap50": _to_float(r.get("ap50")),
                    "success_at_2m": _to_float(r.get("success_at_2m")),
                    "mean_rel_trans_m": _to_float(r.get("mean_rel_trans_m")),
                    "mean_rel_yaw_deg": _to_float(r.get("mean_rel_yaw_deg")),
                }
            )

    by_group: Dict[Tuple[str, str, str], List[dict]] = defaultdict(list)
    for r in rows:
        if r.get("ap50") is None or r.get("success_at_2m") is None or r.get("mean_rel_yaw_deg") is None:
            continue
        by_group[_group_key(r)].append(r)

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    plot_dir = out_dir / "plots"

    pred_points: List[dict] = []
    summary: Dict[str, object] = {"source_csv": str(args.csv), "methods": sorted(methods), "groups": []}

    for (dataset, suite, modality), recs in sorted(by_group.items()):
        fit = _fit_ap_from_success_and_yaw(recs)
        coef = fit.get("coef")
        if not isinstance(coef, list) or len(coef) != 3:
            continue
        b0, b1, b2 = float(coef[0]), float(coef[1]), float(coef[2])

        ap = [float(r["ap50"]) for r in recs if r.get("ap50") is not None]
        succ = [float(r["success_at_2m"]) for r in recs if r.get("success_at_2m") is not None]
        yaw = [float(r["mean_rel_yaw_deg"]) for r in recs if r.get("mean_rel_yaw_deg") is not None]
        trans = [float(r["mean_rel_trans_m"]) for r in recs if r.get("mean_rel_trans_m") is not None]

        corr_succ = _pearson(ap, succ) if len(ap) == len(succ) else None
        corr_yaw = _pearson(ap, yaw) if len(ap) == len(yaw) else None
        corr_trans = _pearson(ap, trans) if len(ap) == len(trans) else None

        # Per-method mean error (for quick bias inspection).
        per_method: Dict[Tuple[str, str], Dict[str, float]] = defaultdict(lambda: {"n": 0.0, "mean_ap50": 0.0, "mean_pred": 0.0, "mean_abs_err": 0.0})
        for r in recs:
            pred = b0 + b1 * float(r["success_at_2m"]) + b2 * float(r["mean_rel_yaw_deg"])
            point = {
                "dataset": dataset,
                "suite": suite,
                "modality": modality,
                "method": str(r.get("method")),
                "strategy": str(r.get("strategy")),
                "noise": float(r["noise"]) if r.get("noise") is not None else None,
                "ap50": float(r["ap50"]),
                "ap50_pred": float(pred),
                "success_at_2m": float(r["success_at_2m"]),
                "mean_rel_yaw_deg": float(r["mean_rel_yaw_deg"]),
                "mean_rel_trans_m": float(r["mean_rel_trans_m"]) if r.get("mean_rel_trans_m") is not None else None,
                "source": str(r.get("source") or ""),
            }
            pred_points.append(point)

            mk = _method_key(r)
            buf = per_method[mk]
            buf["n"] += 1.0
            buf["mean_ap50"] += float(point["ap50"])
            buf["mean_pred"] += float(point["ap50_pred"])
            buf["mean_abs_err"] += abs(float(point["ap50_pred"]) - float(point["ap50"]))

        per_method_out = []
        for (m, s), v in sorted(per_method.items()):
            n = max(1.0, float(v["n"]))
            per_method_out.append(
                {
                    "method": m,
                    "strategy": s,
                    "n": int(n),
                    "mean_ap50": float(v["mean_ap50"] / n),
                    "mean_ap50_pred": float(v["mean_pred"] / n),
                    "mean_abs_err": float(v["mean_abs_err"] / n),
                }
            )

        summary["groups"].append(
            {
                "dataset": dataset,
                "suite": suite,
                "modality": modality,
                "n_points": int(len(recs)),
                "pearson_ap50_success_at_2m": corr_succ,
                "pearson_ap50_mean_rel_trans_m": corr_trans,
                "pearson_ap50_mean_rel_yaw_deg": corr_yaw,
                "fit_ap50_from_success2m_and_yaw": fit,
                "per_method_mean_error": per_method_out,
            }
        )

        # Plot actual-vs-pred scatter for this group.
        pts = [p for p in pred_points if p["dataset"] == dataset and p["suite"] == suite and p["modality"] == modality]
        title = f"{dataset} {suite} {modality} (n={len(pts)})"
        out_png = plot_dir / f"scatter_{dataset}_{suite}_{modality}.png"
        _try_plot_scatter(pts, out_png, title)

    (out_dir / "mapping_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    # Stable column order for downstream greps.
    cols = [
        "dataset",
        "suite",
        "modality",
        "method",
        "strategy",
        "noise",
        "ap50",
        "ap50_pred",
        "success_at_2m",
        "mean_rel_trans_m",
        "mean_rel_yaw_deg",
        "source",
    ]
    with (out_dir / "pred_points.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in pred_points:
            w.writerow({k: r.get(k) for k in cols})

    print(str(out_dir))


if __name__ == "__main__":
    main()
