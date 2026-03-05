#!/usr/bin/env python3
"""Estimate downstream AP50 for Table III rows using a fitted reg->AP mapping.

This is a *rough* estimator meant for triage/stop-loss:
- Table III metrics are computed on paper3737 pairs (registration-only).
- The mapping is fit on fullbench points that include downstream detection AP.

We plug Table III's `success@2m` and `mRRE@2m` into the fitted linear model:

    AP50 ~= b0 + b1 * success_at_2m + b2 * mean_rel_yaw_deg

where `success_at_2m` is in [0,1]. Here we approximate `mean_rel_yaw_deg` with
Table III's `mRRE@2m` (degrees). This mismatch is one of the major error sources.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class MappingGroup:
    dataset: str
    suite: str
    modality: str
    coef: Tuple[float, float, float]
    rmse: float


def _load_mapping_groups(path: Path) -> List[MappingGroup]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    groups = obj.get("groups") or []
    out: List[MappingGroup] = []
    for g in groups:
        if not isinstance(g, dict):
            continue
        fit = g.get("fit_ap50_from_success2m_and_yaw") or {}
        coef = fit.get("coef")
        rmse = fit.get("rmse")
        if not isinstance(coef, Sequence) or len(coef) != 3:
            continue
        if rmse is None:
            continue
        out.append(
            MappingGroup(
                dataset=str(g.get("dataset") or ""),
                suite=str(g.get("suite") or ""),
                modality=str(g.get("modality") or ""),
                coef=(float(coef[0]), float(coef[1]), float(coef[2])),
                rmse=float(rmse),
            )
        )
    return out


def _select_group(groups: List[MappingGroup], *, dataset: str, suite: str, modality: str) -> MappingGroup:
    want = (dataset, suite, modality)
    for g in groups:
        if (g.dataset, g.suite, g.modality) == want:
            return g
    available = sorted({(g.dataset, g.suite, g.modality) for g in groups})
    raise SystemExit(f"Mapping group not found: {want}. Available groups: {available}")


def _predict_ap(coef: Tuple[float, float, float], *, success2m_pct: float, yaw_deg: float) -> float:
    b0, b1, b2 = coef
    return float(b0 + b1 * (float(success2m_pct) / 100.0) + b2 * float(yaw_deg))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Estimate Table III AP50 from a reg->AP mapping summary.")
    p.add_argument(
        "--table3-csv",
        type=Path,
        default=REPO_ROOT / "outputs" / "benchmark_unified_20260220" / "dair_table3_best_te_re.csv",
        help="Input Table III best-rows CSV.",
    )
    p.add_argument(
        "--mapping-summary",
        type=Path,
        default=REPO_ROOT / "outputs" / "pose_error_to_ap_mapping_report_20260224" / "mapping_summary.json",
        help="Mapping summary JSON produced by tools/build_pose_error_to_ap_mapping_report.py.",
    )
    p.add_argument("--dataset", type=str, default="DAIR-V2X")
    p.add_argument("--suite", type=str, default="noise10")
    p.add_argument("--modality", type=str, default="lidar", choices=["camera", "lidar"])
    p.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "outputs" / "table3_ap_estimate_from_mapping_20260224.csv",
        help="Output CSV path.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    table3_csv = args.table3_csv
    mapping_summary = args.mapping_summary
    if not table3_csv.is_file():
        raise SystemExit(f"Missing table3 csv: {table3_csv}")
    if not mapping_summary.is_file():
        raise SystemExit(f"Missing mapping summary: {mapping_summary}")

    groups = _load_mapping_groups(mapping_summary)
    grp = _select_group(groups, dataset=str(args.dataset), suite=str(args.suite), modality=str(args.modality))
    print(
        "[mapping] "
        f"dataset={grp.dataset} suite={grp.suite} modality={grp.modality} "
        f"coef={grp.coef} rmse={grp.rmse}"
    )

    src_rows: List[Dict[str, Any]] = []
    with table3_csv.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            src_rows.append(row)

    out_rows: List[Dict[str, Any]] = []
    for row in src_rows:
        name = str(row.get("method_row") or "")
        succ2 = float(row.get("best_success_at_2m_pct") or 0.0)
        yaw2 = float(row.get("best_mRRE_at_2m") or 0.0)
        pred = _predict_ap(grp.coef, success2m_pct=succ2, yaw_deg=yaw2)
        out_rows.append(
            {
                "mapping_dataset": grp.dataset,
                "mapping_suite": grp.suite,
                "mapping_modality": grp.modality,
                "mapping_rmse": grp.rmse,
                "method_row": name,
                "best_success_at_2m_pct": succ2,
                "best_mRRE_at_2m_deg": yaw2,
                "best_time_sec": row.get("best_time_sec"),
                "ap50_pred": pred,
                "best_source": row.get("best_source"),
            }
        )

    out_rows.sort(key=lambda r: float(r["ap50_pred"]), reverse=True)

    out_path = args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = list(out_rows[0].keys()) if out_rows else []
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        for row in out_rows:
            writer.writerow(row)
    print(f"[write] {out_path} rows={len(out_rows)}")


if __name__ == "__main__":
    main()

