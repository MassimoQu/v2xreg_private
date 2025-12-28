#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Table3Row:
    method: str
    noise: str  # "0" | "1" | "2" | "-" (no init)
    mrre_deg: Tuple[float, float, float]
    mrte_m: Tuple[float, float, float]
    success_pct: Tuple[float, float, float]
    time_s: Optional[float]


def canonical_method(name: str) -> str:
    s = " ".join(str(name).strip().split())
    s = s.replace("∞", "inf")
    s = s.replace("GT∞", "GT inf")
    s = s.replace("GT", "GT ")
    s = re.sub(r"\[\d+\]", "", s)  # strip citations like [55]
    s = s.replace("†", "").replace("‡", "")
    s = " ".join(s.split())
    return s


def parse_table3_from_table_txt(path: Path) -> Dict[Tuple[str, str], Table3Row]:
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = None
    for i, line in enumerate(text):
        if "Noise" in line and "SuccessRate" in line and "mRRE" in line:
            start = i
            break
    if start is None:
        raise RuntimeError(f"Failed to locate Table III header in {path}")

    rows: Dict[Tuple[str, str], Table3Row] = {}
    current_method: Optional[str] = None
    last_noise: Optional[str] = None
    pending_rows: List[Tuple[str, List[float], Optional[float]]] = []

    for line in text[start + 1 :]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("†") or stripped.startswith(": For CBM"):
            break

        # Split by >=2 spaces so method names (with internal single spaces) stay intact.
        fields = [f for f in re.split(r"\s{2,}", stripped) if f]
        if not fields:
            continue

        # Optional init marker column.
        if fields[0] in {"✓", "×"}:
            fields = fields[1:]
            if not fields:
                continue

        noise = fields[0]
        rest = fields[1:]

        method_in_line: Optional[str] = None
        if rest and re.search(r"[A-Za-z]", rest[0]):
            method_in_line = canonical_method(rest[0])
            rest = rest[1:]

        numeric: List[float] = []
        time_s: Optional[float] = None
        for token in rest:
            token = token.strip()
            if token == "-":
                time_s = None
                continue
            try:
                numeric.append(float(token))
            except ValueError:
                # Ignore non-numeric leftovers.
                continue

        if len(numeric) < 9:
            last_noise = noise
            continue

        # In table.txt extraction, some methods only appear on the noise=1 row (with noise=0/2 rows blank).
        # Additionally, the first row of a new 0/1/2 block might have a blank method while the previous block's
        # method is still "current_method". Detect this by observing the noise cycle reset "2 -> 0".
        if method_in_line is None and noise == "0" and last_noise == "2":
            current_method = None

        if method_in_line is None and current_method is None:
            pending_rows.append((noise, numeric, time_s))
            last_noise = noise
            continue

        if method_in_line is not None:
            current_method = method_in_line
            # Backfill any pending rows (typically noise=0) for this method.
            for pending_noise, pending_numeric, pending_time in pending_rows:
                mrre = tuple(pending_numeric[0:3])  # type: ignore[assignment]
                mrte = tuple(pending_numeric[3:6])  # type: ignore[assignment]
                succ = tuple(pending_numeric[6:9])  # type: ignore[assignment]
                t_s = pending_time
                if len(pending_numeric) >= 10:
                    t_s = float(pending_numeric[9])
                rows[(current_method, pending_noise)] = Table3Row(
                    method=current_method,
                    noise=pending_noise,
                    mrre_deg=mrre,  # type: ignore[arg-type]
                    mrte_m=mrte,  # type: ignore[arg-type]
                    success_pct=succ,  # type: ignore[arg-type]
                    time_s=t_s,
                )
            pending_rows.clear()

        assert current_method is not None
        mrre = tuple(numeric[0:3])  # type: ignore[assignment]
        mrte = tuple(numeric[3:6])  # type: ignore[assignment]
        succ = tuple(numeric[6:9])  # type: ignore[assignment]
        if len(numeric) >= 10:
            time_s = float(numeric[9])
        rows[(current_method, noise)] = Table3Row(
            method=current_method,
            noise=noise,
            mrre_deg=mrre,  # type: ignore[arg-type]
            mrte_m=mrte,  # type: ignore[arg-type]
            success_pct=succ,  # type: ignore[arg-type]
            time_s=time_s,
        )
        last_noise = noise

    if not rows:
        raise RuntimeError(f"Parsed 0 rows from {path}; check the Table III section.")
    return rows


def load_metrics(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def ours_from_metrics(metrics: dict) -> dict:
    def _get(key: str) -> Optional[float]:
        val = metrics.get(key)
        if val is None:
            return None
        try:
            return float(val)
        except Exception:
            return None

    # Success is stored as ratio (0..1).
    succ = (
        _get("success_at_1m"),
        _get("success_at_2m"),
        _get("success_at_3m"),
    )
    succ_pct = tuple(None if v is None else v * 100.0 for v in succ)
    mrre = (
        _get("mRRE@1deg") or _get("mRE@1m"),
        _get("mRRE@2deg") or _get("mRE@2m"),
        _get("mRRE@3deg") or _get("mRE@3m"),
    )
    mrte = (
        _get("mRTE@1m") or _get("mTE@1m"),
        _get("mRTE@2m") or _get("mTE@2m"),
        _get("mRTE@3m") or _get("mTE@3m"),
    )
    return {
        "success_pct": succ_pct,
        "mrre_deg": mrre,
        "mrte_m": mrte,
        "time_s": _get("avg_time"),
        "path": metrics.get("_path"),
    }


def fmt_triplet(values: Tuple[Optional[float], Optional[float], Optional[float]], *, digits: int = 2) -> str:
    def _fmt(v: Optional[float]) -> str:
        if v is None:
            return "NA"
        return f"{v:.{digits}f}"

    return "/".join(_fmt(v) for v in values)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare current outputs against paper Table III.")
    parser.add_argument("--root", default="outputs_paper_3737", help="Output root for V2X-Reg++ runs (default: outputs_paper_3737).")
    args = parser.parse_args()

    table_txt = REPO_ROOT / "table.txt"
    paper = parse_table3_from_table_txt(table_txt)

    root = (REPO_ROOT / args.root).resolve()

    # Canonical mapping from (method, noise) -> metrics.json path.
    ours_paths: Dict[Tuple[str, str], Path] = {
        # Paper lower block (no-init)
        ("V2X-Reg", "-"): root / "dair_v2xreg_oiou_gt15" / "metrics.json",
        ("V2X-Reg++GT inf", "-"): root / "dair_v2xregpp_gt_inf" / "metrics.json",
        ("V2X-Reg++GT 25", "-"): root / "dair_v2xregpp_gt25" / "metrics.json",
        ("V2X-Reg++GT 15", "-"): root / "dair_v2xregpp_gt15" / "metrics.json",
        ("V2X-Reg++GT 10", "-"): root / "dair_v2xregpp_gt10" / "metrics.json",
        ("V2X-Reg++PP 15", "-"): root / "dair_v2xregpp_pp15" / "metrics.json",
        ("V2X-Reg++SC 15", "-"): root / "dair_v2xregpp_sc15" / "metrics.json",
        ("V2X-Reg++GT 25 (hSVD)", "-"): root / "dair_v2xregpp_gt25_hsvd" / "metrics.json",
        ("V2X-Reg++GT 25 (mSVD)", "-"): root / "dair_v2xregpp_gt25_msvd" / "metrics.json",
        # Upper block baselines (init noise)
        ("ICP", "0"): root / "baselines" / "icp_paper_noise0" / "metrics.json",
        ("ICP", "1"): root / "baselines" / "icp_paper_noise1" / "metrics.json",
        ("ICP", "2"): root / "baselines" / "icp_paper_noise2" / "metrics.json",
        ("PICP", "0"): root / "baselines" / "picp_paper_noise0" / "metrics.json",
        ("PICP", "1"): root / "baselines" / "picp_paper_noise1" / "metrics.json",
        ("PICP", "2"): root / "baselines" / "picp_paper_noise2" / "metrics.json",
        # VIPS/CBM runs live under outputs/ by default.
        # Prefer "paper3737_*" folders that follow the Table III noise levels (0/1/2) and any
        # additional gates needed to match the paper's reimplementations.
        ("VIPS", "0"): REPO_ROOT / "outputs" / "vips" / "paper3737_noise0_thr1p5" / "metrics.json",
        ("VIPS", "1"): REPO_ROOT / "outputs" / "vips" / "paper3737_noise1_thr1p5" / "metrics.json",
        ("VIPS", "2"): REPO_ROOT / "outputs" / "vips" / "paper3737_noise2_thr1p5" / "metrics.json",
        ("CBM", "0"): REPO_ROOT / "outputs" / "cbm" / "paper3737_noise0_min20" / "metrics.json",
        ("CBM", "1"): REPO_ROOT / "outputs" / "cbm" / "paper3737_noise1_min20" / "metrics.json",
        ("CBM", "2"): REPO_ROOT / "outputs" / "cbm" / "paper3737_noise2_min20" / "metrics.json",
    }

    targets = list(ours_paths.keys())

    print(f"[Table III] paper source: {table_txt}")
    print(f"[Table III] outputs root: {root}")
    print()

    for method, noise in targets:
        paper_row = paper.get((method, noise))
        path = ours_paths[(method, noise)]
        ours_metrics = load_metrics(path)
        ours: Optional[dict] = None
        if ours_metrics is not None:
            ours_metrics["_path"] = str(path)
            ours = ours_from_metrics(ours_metrics)

        print(f"- {method} (noise={noise})")
        if paper_row is None:
            print("  paper: MISSING (not found in table.txt parse)")
        else:
            print(
                "  paper: "
                f"succ%={paper_row.success_pct[0]:.2f}/{paper_row.success_pct[1]:.2f}/{paper_row.success_pct[2]:.2f} "
                f"mRRE={paper_row.mrre_deg[0]:.2f}/{paper_row.mrre_deg[1]:.2f}/{paper_row.mrre_deg[2]:.2f} "
                f"mRTE={paper_row.mrte_m[0]:.2f}/{paper_row.mrte_m[1]:.2f}/{paper_row.mrte_m[2]:.2f} "
                f"time={('NA' if paper_row.time_s is None else f'{paper_row.time_s:.2f}')}"
            )
        if ours is None:
            print(f"  ours : MISSING ({path})")
        else:
            ours_succ = ours["success_pct"]
            ours_mrre = ours["mrre_deg"]
            ours_mrte = ours["mrte_m"]
            ours_time = ours["time_s"]
            print(
                "  ours : "
                f"succ%={fmt_triplet(ours_succ)} "
                f"mRRE={fmt_triplet(ours_mrre, digits=2)} "
                f"mRTE={fmt_triplet(ours_mrte, digits=2)} "
                f"time={('NA' if ours_time is None else f'{ours_time:.2f}')} "
                f"({path})"
            )
        print()


if __name__ == "__main__":
    main()
