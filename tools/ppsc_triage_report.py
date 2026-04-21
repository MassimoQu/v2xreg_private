#!/usr/bin/env python3
"""PP/SC detection-cache & matching triage report.

This is a lightweight, deterministic report intended to be runnable by automation.
It helps answer:
- How much of the paper3737 subset is covered by the detection caches?
- Are PP/SC Table-III runs failing because of coverage, or because matches are wrong?
- What does the TE/RE distribution look like (best/worst examples)?

Default paths assume the v2xreg_private repo layout.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _stem(path_str: str) -> str:
    return Path(path_str).stem


def load_paper_pairs(path: Path) -> List[Tuple[str, str]]:
    data = _read_json(path)
    if not isinstance(data, list):
        raise ValueError(f"paper data must be a list, got {type(data)}")
    pairs: List[Tuple[str, str]] = []
    for e in data:
        if not isinstance(e, dict):
            continue
        infra = _stem(str(e.get("infrastructure_image_path", "")))
        veh = _stem(str(e.get("vehicle_image_path", "")))
        if infra and veh:
            pairs.append((infra, veh))
    return pairs


def _box_count(entry: Sequence[Any]) -> int:
    if not isinstance(entry, list):
        return 0
    return sum(1 for box in entry if box is not None)


@dataclass(frozen=True)
class CacheSummary:
    path: Path
    total_records: int
    non_null_entries: int
    pairs: List[Tuple[str, str]]
    infra_box_counts: List[int]
    veh_box_counts: List[int]


def load_detection_cache(path: Path, field: str = "pred_corner3d_np_list") -> CacheSummary:
    raw = _read_json(path)
    if not isinstance(raw, dict):
        raise ValueError(f"cache must be a dict, got {type(raw)}")

    pairs: List[Tuple[str, str]] = []
    infra_box_counts: List[int] = []
    veh_box_counts: List[int] = []
    non_null = 0

    for _, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        non_null += 1
        infra = str(entry.get("infra_frame_id", ""))
        veh = str(entry.get("veh_frame_id", ""))
        if infra and veh:
            pairs.append((infra, veh))

        pred_list = entry.get(field)
        if isinstance(pred_list, list) and len(pred_list) >= 2:
            infra_count = _box_count(pred_list[0] if isinstance(pred_list[0], list) else [])
            veh_count = _box_count(pred_list[1] if isinstance(pred_list[1], list) else [])
            infra_box_counts.append(infra_count)
            veh_box_counts.append(veh_count)

    return CacheSummary(
        path=path,
        total_records=len(raw),
        non_null_entries=non_null,
        pairs=pairs,
        infra_box_counts=infra_box_counts,
        veh_box_counts=veh_box_counts,
    )


def _fmt_counts(values: List[int]) -> str:
    if not values:
        return "n=0"
    return f"n={len(values)} avg={mean(values):.2f} min={min(values)} max={max(values)}"


def _quantile(sorted_values: List[float], q: float) -> Optional[float]:
    if not sorted_values:
        return None
    if q <= 0:
        return sorted_values[0]
    if q >= 1:
        return sorted_values[-1]
    idx = int(round((len(sorted_values) - 1) * q))
    return sorted_values[idx]


@dataclass(frozen=True)
class MatchRow:
    index: int
    infra_id: str
    veh_id: str
    te: float
    re: float
    stability: Optional[float]
    num_matches: int


def iter_matches(path: Path) -> Iterable[MatchRow]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            te = float(r.get("TE", math.nan))
            re = float(r.get("RE", math.nan))
            matches = r.get("matches")
            num_matches = len(matches) if isinstance(matches, list) else int(r.get("num_matches", 0) or 0)
            yield MatchRow(
                index=int(r.get("index", -1) or -1),
                infra_id=str(r.get("infra_id", "")),
                veh_id=str(r.get("veh_id", "")),
                te=te,
                re=re,
                stability=(float(r["stability"]) if isinstance(r.get("stability"), (int, float)) else None),
                num_matches=num_matches,
            )


def summarize_matches(path: Path, thresholds: List[float], top_k: int) -> None:
    rows = list(iter_matches(path))
    rows_valid = [r for r in rows if not (math.isnan(r.te) or math.isnan(r.re))]
    rows_sorted_by_te = sorted(rows_valid, key=lambda r: r.te)

    tes = sorted([r.te for r in rows_valid])
    res = sorted([r.re for r in rows_valid])

    def fmt(x: Optional[float]) -> str:
        return "NA" if x is None else f"{x:.3f}"

    print(f"[matches] {path}")
    print(f"frames={len(rows)} valid={len(rows_valid)}")
    print(f"with_matches={sum(1 for r in rows_valid if r.num_matches > 0)}")

    for thr in thresholds:
        ok = [r for r in rows_valid if (r.te < thr and r.re < thr)]
        print(f"success@{thr:.0f} (TE<thr & RE<thr): {len(ok)}/{len(rows_valid)} = {(len(ok)/len(rows_valid) if rows_valid else 0.0):.4f}")

    for q in (0.50, 0.90, 0.95, 0.99):
        print(f"TE_p{int(q*100)}={fmt(_quantile(tes, q))} RE_p{int(q*100)}={fmt(_quantile(res, q))}")

    print("best_examples:")
    for r in rows_sorted_by_te[:top_k]:
        print(f"  TE={r.te:.2f} RE={r.re:.2f} matches={r.num_matches} st={r.stability} {r.infra_id}-{r.veh_id} (idx={r.index})")

    print("worst_examples:")
    for r in list(reversed(rows_sorted_by_te[-top_k:])):
        print(f"  TE={r.te:.2f} RE={r.re:.2f} matches={r.num_matches} st={r.stability} {r.infra_id}-{r.veh_id} (idx={r.index})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--paper", default="data/data_info_dair_paper3737.json", help="paper3737 data_info json"
    )
    parser.add_argument(
        "--pp-cache",
        default="data/DAIR-V2X/detected/veh_rsu_dual_ft_detection_cache.json",
        help="PointPillars cache (json)",
    )
    parser.add_argument(
        "--sc-cache",
        default="data/DAIR-V2X/detected/veh_rsu_dual_m2_second_detection_cache.json",
        help="SECOND cache (json)",
    )
    parser.add_argument(
        "--pp-matches",
        default="outputs_paper_3737/dair_v2xregpp_pp15/matches.jsonl",
        help="PP15 matches.jsonl",
    )
    parser.add_argument(
        "--sc-matches",
        default="outputs_paper_3737/dair_v2xregpp_sc15/matches.jsonl",
        help="SC15 matches.jsonl",
    )
    parser.add_argument("--top-k", type=int, default=5, help="how many best/worst examples to print")
    parser.add_argument(
        "--thresholds",
        type=str,
        default="1,2,3",
        help="comma-separated success thresholds (same numeric for m & deg)",
    )
    parser.add_argument(
        "--dump-missing",
        type=str,
        default=None,
        help="Path to dump missing frames JSON",
    )
    args = parser.parse_args()

    try:
        thresholds = [float(x.strip()) for x in args.thresholds.split(",") if x.strip()]

        paper_pairs = load_paper_pairs(Path(args.paper))
        paper_set = set(paper_pairs)
        print(f"[paper3737] {args.paper} pairs={len(paper_pairs)}")
        missing_by_cache: Dict[str, Any] = {}

        for name, cache_path in (
            ("PP", Path(args.pp_cache)),
            ("SC", Path(args.sc_cache)),
        ):
            if not cache_path.exists():
                print(f"[cache] {name}: MISSING {cache_path}")
                continue
            summary = load_detection_cache(cache_path)
            cache_pairs = set(summary.pairs)
            inter = paper_set.intersection(cache_pairs)
            print(f"[cache] {name}: {cache_path}")
            print(f"  total_records={summary.total_records} non_null_entries={summary.non_null_entries}")
            print(f"  pairs_in_cache={len(cache_pairs)} paper3737_intersection={len(inter)}")
            print(f"  infra_boxes: {_fmt_counts(summary.infra_box_counts)}")
            print(f"  vehicle_boxes: {_fmt_counts(summary.veh_box_counts)}")
            missing_pairs = sorted(paper_set - cache_pairs)
            print(f"  missing_from_cache={len(missing_pairs)}")
            missing_by_cache[name] = [{"infra_id": i, "veh_id": v} for i, v in missing_pairs]

        if args.dump_missing:
            out_path = Path(args.dump_missing)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out = {
                "paper": str(args.paper),
                "paper_pairs": len(paper_pairs),
                "missing": missing_by_cache,
            }
            out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
            print(f"[dump] wrote {out_path}")

        pp_matches = Path(args.pp_matches)
        if pp_matches.exists():
            summarize_matches(pp_matches, thresholds, top_k=int(args.top_k))
        else:
            print(f"[matches] PP: MISSING {pp_matches}")

        sc_matches = Path(args.sc_matches)
        if sc_matches.exists():
            summarize_matches(sc_matches, thresholds, top_k=int(args.top_k))
        else:
            print(f"[matches] SC: MISSING {sc_matches}")
    except Exception as e:
        print(f"[error] {e}")
        raise


if __name__ == "__main__":
    main()
