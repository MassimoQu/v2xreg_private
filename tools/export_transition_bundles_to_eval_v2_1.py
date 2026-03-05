#!/usr/bin/env python3
"""Export local benchmark summaries to coopVGGT eval_v2_1 transition bundles.

This adapter converts one or more local benchmark run folders (each containing
`results_ap50_from_yaml.json`) into eval_v2_1 bundle directories with:

- manifest.yaml
- metrics_geometry.csv
- metrics_detection.csv
- metrics_robustness.csv
- summary.md
- required visuals placeholders

Exported bundles are intentionally marked as transition artifacts:
`legacy_geometry_proxy=true` and depth/scale metrics are placeholders.
"""

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import pathlib
import re
import subprocess
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import yaml


Path = pathlib.Path

PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6360000002000154a25f9b0000000049454e44ae426082"
)

RUN_ID_RE = re.compile(
    r"^[0-9]{8}_[0-9]{6}_[A-Za-z0-9]+_(smoke10|dev100|report500)_M[01]_N[0-3]_D[0-2]_[0-2]$"
)

GEOMETRY_COLUMNS = [
    "rpe_xy_obj_p50",
    "rpe_xy_obj_p95",
    "rpe_yaw_obj_p50",
    "rpe_yaw_obj_p95",
    "depth_abs_rel_fg",
    "depth_rmse_fg_0_20",
    "depth_rmse_fg_20_40",
    "depth_rmse_fg_40_70",
    "scale_err_global",
    "scale_err_obj_lwh",
    "range_scale_err_obj",
    # Transition extras (still numeric-only for validator compatibility)
    "noise_min",
    "noise_max",
    "target_ap50_mean",
    "baseline_ap50_mean",
    "oracle_ap50_mean",
    "target_minus_baseline_mean",
    "oracle_minus_target_mean",
]

DETECTION_COLUMNS = [
    "ap_0_5",
    "ap_0_7",
    "baseline_ap_0_5",
    "baseline_ap_0_7",
    # Transition extras
    "oracle_ap_0_5",
    "oracle_ap_0_7",
    "target_ap_0_5",
    "target_ap_0_7",
    "anchor_noise",
]

ROBUSTNESS_COLUMNS = [
    "ap_drop_n3",
    "pose_tail_obj_p95_n3",
    "pose_tail_obj_p95_n0",
    "pose_tail_obj_p95_degrade_ratio",
    "robust_score",
    # Transition extras
    "target_ap_n0",
    "target_ap_n3",
    "baseline_ap_n0",
    "baseline_ap_n3",
    "oracle_ap_n0",
    "oracle_ap_n3",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        action="append",
        required=True,
        type=Path,
        help="Benchmark run directory containing results_ap50_from_yaml.json (repeatable).",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("eval_runs/inbox/local_transition"),
        help="Bundle output root. One subfolder is created per source.",
    )
    parser.add_argument("--pack", default="dev100", choices=["smoke10", "dev100", "report500"])
    parser.add_argument("--mode", default="M0", choices=["M0", "M1"])
    parser.add_argument("--noise", default="N2", choices=["N0", "N1", "N2", "N3"])
    parser.add_argument("--dropout", default="D0", choices=["D0", "D1", "D2"])
    parser.add_argument("--seed", type=int, default=0, choices=[0, 1, 2])
    parser.add_argument("--line", default="CAND", choices=["LA", "LB", "DENSE", "QUERY", "CAND"])
    parser.add_argument("--server", default="local")
    parser.add_argument("--owner", default="track1-governance")
    parser.add_argument(
        "--tag-prefix",
        default="v2xregpptrans",
        help="Alnum token prefix used inside run_id.",
    )
    parser.add_argument(
        "--prefer-sweep",
        default="noise10",
        help="Prefer entries from this sweep when available (default: noise10).",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sanitize_token(text: str, fallback: str = "TRANS") -> str:
    token = re.sub(r"[^A-Za-z0-9]", "", text or "")
    return token if token else fallback


def git_value(repo_root: Path, args: Sequence[str], fallback: str) -> str:
    try:
        return subprocess.check_output(["git", "-C", str(repo_root), *args], text=True).strip()
    except Exception:
        return fallback


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def load_json(path: Path) -> Dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def safe_float(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except Exception:
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def mean(values: Iterable[float], default: float = 0.0) -> float:
    vals = [float(v) for v in values if safe_float(v) is not None]
    if not vals:
        return default
    return float(sum(vals) / len(vals))


def percentile(values: Sequence[float], q: float, default: float = 999.0) -> float:
    vals = sorted(float(v) for v in values if safe_float(v) is not None)
    if not vals:
        return default
    q = clamp(float(q), 0.0, 1.0)
    idx = (len(vals) - 1) * q
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return vals[lo]
    frac = idx - lo
    return vals[lo] * (1.0 - frac) + vals[hi] * frac


def as_number(value: Optional[float], default: float) -> float:
    if value is None:
        return float(default)
    v = safe_float(value)
    if v is None:
        return float(default)
    return float(v)


def normalize_noise(value: Any) -> Optional[str]:
    v = safe_float(value)
    if v is None:
        return None
    return f"{v:.1f}"


def pick_by_noise_token(noises: Sequence[str], noise_token: str) -> str:
    if not noises:
        raise ValueError("empty noise axis")
    ordered = sorted({normalize_noise(n) for n in noises if normalize_noise(n) is not None}, key=lambda x: float(x))
    if not ordered:
        raise ValueError("noise axis has no parseable values")
    if len(ordered) == 1:
        return ordered[0]

    frac = {"N0": 0.0, "N1": 1.0 / 3.0, "N2": 2.0 / 3.0, "N3": 1.0}.get(noise_token, 2.0 / 3.0)
    idx = int(round(frac * (len(ordered) - 1)))
    idx = max(0, min(len(ordered) - 1, idx))
    return ordered[idx]


def build_line_groups(entries: Sequence[Mapping[str, Any]]) -> Dict[Tuple[str, str], List[Mapping[str, Any]]]:
    grouped: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {}
    for e in entries:
        method = str(e.get("method") or "").strip()
        strategy = str(e.get("strategy") or "").strip() or "bounds"
        if not method:
            continue
        if normalize_noise(e.get("noise")) is None:
            continue
        if safe_float(e.get("ap50")) is None:
            continue
        grouped.setdefault((method, strategy), []).append(e)
    return grouped


def line_ap50_score(rows: Sequence[Mapping[str, Any]]) -> float:
    return mean([safe_float(r.get("ap50")) for r in rows if safe_float(r.get("ap50")) is not None], default=-1e9)


def _best_line_key(keys: Sequence[Tuple[str, str]], grouped: Mapping[Tuple[str, str], Sequence[Mapping[str, Any]]]) -> Tuple[str, str]:
    if not keys:
        raise ValueError("no candidate line keys")
    return max(
        keys,
        key=lambda k: (
            len(grouped.get(k, [])),
            line_ap50_score(grouped.get(k, [])),
            k[0],
            k[1],
        ),
    )


def choose_baseline_key(grouped: Mapping[Tuple[str, str], Sequence[Mapping[str, Any]]]) -> Tuple[str, str]:
    keys = list(grouped.keys())
    baseline_exact = [k for k in keys if k[0].lower() == "baseline"]
    if baseline_exact:
        return _best_line_key(baseline_exact, grouped)
    baseline_alias = [k for k in keys if k[0].lower() in {"none", "baseline"}]
    if baseline_alias:
        return _best_line_key(baseline_alias, grouped)
    raise ValueError("cannot find baseline line")


def choose_oracle_key(grouped: Mapping[Tuple[str, str], Sequence[Mapping[str, Any]]]) -> Tuple[str, str]:
    keys = list(grouped.keys())
    oracle_keys = [k for k in keys if "oracle" in k[0].lower()]
    if oracle_keys:
        return _best_line_key(oracle_keys, grouped)
    raise ValueError("cannot find oracle line")


def choose_target_key(
    grouped: Mapping[Tuple[str, str], Sequence[Mapping[str, Any]]],
    baseline_key: Tuple[str, str],
    oracle_key: Tuple[str, str],
) -> Tuple[str, str]:
    keys = list(grouped.keys())

    v2xregpp_keys = [k for k in keys if k[0].lower() == "v2xregpp"]
    if v2xregpp_keys:
        return _best_line_key(v2xregpp_keys, grouped)

    baseline_methods = {baseline_key[0].lower(), "baseline", "none"}
    oracle_methods = {oracle_key[0].lower()}

    primary = [
        k
        for k in keys
        if k[0].lower() not in baseline_methods
        and k[0].lower() not in oracle_methods
        and k[0].lower() != "single"
    ]
    if primary:
        return _best_line_key(primary, grouped)

    fallback = [k for k in keys if k[0].lower() not in baseline_methods]
    if fallback:
        return _best_line_key(fallback, grouped)

    return _best_line_key(keys, grouped)


def build_curve(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, float]]:
    metrics = [
        "ap30",
        "ap50",
        "ap70",
        "mean_rel_trans_m",
        "mean_rel_yaw_deg",
        "success_at_2m",
        "pose_applied_count",
        "pose_provider_applied_count",
        "pose_match_sec",
        "pose_solver_sec",
    ]
    agg: Dict[str, Dict[str, List[float]]] = {}
    for row in rows:
        noise = normalize_noise(row.get("noise"))
        if noise is None:
            continue
        slot = agg.setdefault(noise, {})
        for key in metrics:
            val = safe_float(row.get(key))
            if val is None:
                continue
            slot.setdefault(key, []).append(val)

    out: Dict[str, Dict[str, float]] = {}
    for noise in sorted(agg.keys(), key=lambda x: float(x)):
        out[noise] = {k: mean(vs, default=0.0) for k, vs in agg[noise].items()}
    return out


def metric_at(curve: Mapping[str, Mapping[str, float]], noise: str, key: str, default: float) -> float:
    if noise in curve:
        val = safe_float(curve[noise].get(key))
        if val is not None:
            return float(val)
    return float(default)


def robust_score(ap05: float, ap07: float, ap_drop_n3: float, pose_tail_n3: float) -> float:
    ap50_norm = clamp(ap05, 0.0, 1.0)
    ap70_norm = clamp(ap07, 0.0, 1.0)
    ap_drop_norm = clamp(ap_drop_n3 / 0.30, 0.0, 1.0)
    pose_tail_norm = clamp(pose_tail_n3 / 3.0, 0.0, 1.0)
    score = 0.4 * ap50_norm + 0.2 * ap70_norm + 0.2 * (1.0 - ap_drop_norm) + 0.2 * (1.0 - pose_tail_norm)
    return clamp(score, 0.0, 1.0)


def write_csv(path: Path, columns: Sequence[str], row: Mapping[str, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(columns))
        writer.writeheader()
        writer.writerow({k: float(row.get(k, 0.0)) for k in columns})


def write_required_visuals(bundle_dir: Path, summary_hint: str) -> None:
    html_path = bundle_dir / "visuals" / "html" / "scene_overview.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(
        "<html><body>"
        "<h2>Transition Bundle (legacy_geometry_proxy)</h2>"
        f"<p>{summary_hint}</p>"
        "</body></html>\n",
        encoding="utf-8",
    )

    for rel in ("visuals/png/bev_overlay.png", "visuals/png/depth_fg_error.png"):
        p = bundle_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(PNG_1X1)


def yaml_dump_text(payload: Mapping[str, Any]) -> str:
    try:
        return yaml.safe_dump(payload, sort_keys=False, allow_unicode=False)
    except TypeError:
        return yaml.safe_dump(payload, allow_unicode=False)


def load_entries(results_path: Path) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    obj = json.loads(results_path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"results json must be an object: {results_path}")
    entries = obj.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"results json has no entries: {results_path}")
    clean_entries = [e for e in entries if isinstance(e, dict)]
    if not clean_entries:
        raise ValueError(f"results json has no valid dict entries: {results_path}")
    return obj, clean_entries


def maybe_prefer_sweep(entries: Sequence[Mapping[str, Any]], prefer_sweep: str) -> List[Mapping[str, Any]]:
    preferred = [e for e in entries if str(e.get("sweep") or "") == prefer_sweep]
    return preferred if preferred else list(entries)


def infer_dataset_root(source_dir: Path, source_obj: Mapping[str, Any]) -> str:
    """Prefer stable dataset tokens over machine-local absolute paths.

    The cloud protocol treats dataset_root/split_file/frames_json_sha256 as part of
    the comparability contract, so avoid exporting paths under model/log dirs.
    """

    # If local run has a manifest/config snapshot, try to extract a stable `data/<DATASET>` root.
    candidates: List[str] = []
    dataset_hint: str = ""

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            for vv in v.values():
                walk(vv)
        elif isinstance(v, list):
            for vv in v:
                walk(vv)
        elif isinstance(v, str):
            m = re.search(r"(data/[^/\\]+)", v)
            if m:
                candidates.append(m.group(1))

    for fname in ("manifest.json", "config_snapshot.json"):
        p = source_dir / fname
        if not p.exists():
            continue
        obj = load_json(p)
        if not dataset_hint:
            dataset_hint = str(obj.get("dataset") or "").strip()
        walk(obj)

    # If dataset is known, prefer a candidate containing its token.
    dataset = (dataset_hint or str(source_obj.get("dataset") or "")).strip()
    if dataset:
        for c in candidates:
            if dataset.lower() in c.lower():
                return c

    if candidates:
        # Pick the shortest stable-looking token.
        return sorted(set(candidates), key=lambda s: (len(s), s))[0]

    dataset = str(source_obj.get("dataset") or "").strip()
    if dataset:
        return f"data/{dataset}"

    return "data/UNKNOWN"


def choose_config_path(source_dir: Path) -> Path:
    cfg = source_dir / "config_snapshot.json"
    if cfg.exists():
        return cfg
    # Local core benchmark outputs usually have a rich manifest.json (better than results).
    manifest = source_dir / "manifest.json"
    if manifest.exists():
        return manifest
    return source_dir / "results_ap50_from_yaml.json"


def find_existing_run_id(
    output_root: Path,
    *,
    results_path: Path,
    args: argparse.Namespace,
) -> Optional[str]:
    """Best-effort idempotency: reuse existing bundle dir if it matches the same source+matrix."""
    if not output_root.exists():
        return None
    results_path = results_path.resolve()
    for bundle_dir in sorted(output_root.glob("*")):
        if not bundle_dir.is_dir():
            continue
        manifest_path = bundle_dir / "manifest.yaml"
        if not manifest_path.exists():
            continue
        try:
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if not isinstance(manifest, dict):
            continue
        src = manifest.get("source_results_json")
        if not src:
            continue
        try:
            if Path(str(src)).resolve() != results_path:
                continue
        except Exception:
            continue

        if str(manifest.get("pack")) != str(args.pack):
            continue
        if str(manifest.get("mode")) != str(args.mode):
            continue
        if str(manifest.get("noise")) != str(args.noise):
            continue
        if str(manifest.get("dropout")) != str(args.dropout):
            continue
        if int(manifest.get("seed", -1)) != int(args.seed):
            continue
        if str(manifest.get("line")) != str(args.line):
            continue

        run_id = str(manifest.get("run_id") or bundle_dir.name).strip()
        if run_id and RUN_ID_RE.match(run_id):
            return run_id
    return None


def build_frames_proxy(
    *,
    source_dir: Path,
    source_obj: Mapping[str, Any],
    dataset_root: str,
    pack: str,
    selected_entries: Sequence[Mapping[str, Any]],
    target_noises: Sequence[str],
) -> Dict[str, Any]:
    """Transition-friendly proxy for the (dataset, split) identity.

    We usually don't have the real frames list here. This proxy captures enough
    stable metadata to make `frames_json_sha256` meaningful across reruns.
    """
    samples = sorted(
        {
            int(float(e.get("samples")))
            for e in selected_entries
            if safe_float(e.get("samples")) is not None
        }
    )
    return {
        "proxy_version": 1,
        "note": "transition proxy; real frames list not exported yet",
        "dataset_root": dataset_root,
        "pack": pack,
        # A stable split tag (not an absolute path).
        "split_tag": source_obj.get("run_id", source_dir.name),
        "samples_axis": samples,
        "noise_axis": [float(n) for n in target_noises],
    }


def build_run_id(
    *,
    idx: int,
    args: argparse.Namespace,
    source_dir: Path,
    source_key_hash: str,
) -> str:
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = sanitize_token(args.tag_prefix, fallback="TRANS")[:14]
    src = sanitize_token(source_dir.name, fallback="SRC")[:10]
    uniq = sanitize_token(source_key_hash[:8], fallback="HASH")
    token = f"{prefix}{src}{idx:02d}{uniq}"
    run_id = f"{ts}_{token}_{args.pack}_{args.mode}_{args.noise}_{args.dropout}_{args.seed}"
    if not RUN_ID_RE.match(run_id):
        raise ValueError(f"generated run_id does not match protocol regex: {run_id}")
    return run_id


def export_source(
    *,
    source_dir: Path,
    args: argparse.Namespace,
    repo_root: Path,
    repo_branch: str,
    repo_commit: str,
    idx: int,
) -> Path:
    source_dir = source_dir.resolve()
    results_path = source_dir / "results_ap50_from_yaml.json"
    if not results_path.exists():
        raise FileNotFoundError(f"missing results_ap50_from_yaml.json under source: {source_dir}")

    source_obj, raw_entries = load_entries(results_path)
    selected_entries = maybe_prefer_sweep(raw_entries, args.prefer_sweep)

    grouped = build_line_groups(selected_entries)
    if not grouped:
        raise ValueError(f"no valid method lines found in {results_path}")

    baseline_key = choose_baseline_key(grouped)
    oracle_key = choose_oracle_key(grouped)
    target_key = choose_target_key(grouped, baseline_key=baseline_key, oracle_key=oracle_key)

    baseline_curve = build_curve(grouped[baseline_key])
    oracle_curve = build_curve(grouped[oracle_key])
    target_curve = build_curve(grouped[target_key])

    target_noises = sorted(target_curve.keys(), key=lambda x: float(x))
    if not target_noises:
        raise ValueError(f"target line has empty noise curve in {results_path}")

    low_noise = target_noises[0]
    high_noise = target_noises[-1]
    anchor_noise = pick_by_noise_token(target_noises, args.noise)

    target_ap_anchor = metric_at(target_curve, anchor_noise, "ap50", default=0.0)
    target_ap70_anchor = metric_at(target_curve, anchor_noise, "ap70", default=max(0.0, target_ap_anchor - 0.05))
    baseline_ap_anchor = metric_at(baseline_curve, anchor_noise, "ap50", default=target_ap_anchor)
    baseline_ap70_anchor = metric_at(baseline_curve, anchor_noise, "ap70", default=target_ap70_anchor)
    oracle_ap_anchor = metric_at(oracle_curve, anchor_noise, "ap50", default=target_ap_anchor)
    oracle_ap70_anchor = metric_at(oracle_curve, anchor_noise, "ap70", default=target_ap70_anchor)

    target_ap_n0 = metric_at(target_curve, low_noise, "ap50", default=target_ap_anchor)
    target_ap_n3 = metric_at(target_curve, high_noise, "ap50", default=target_ap_anchor)
    baseline_ap_n0 = metric_at(baseline_curve, low_noise, "ap50", default=baseline_ap_anchor)
    baseline_ap_n3 = metric_at(baseline_curve, high_noise, "ap50", default=baseline_ap_anchor)
    oracle_ap_n0 = metric_at(oracle_curve, low_noise, "ap50", default=oracle_ap_anchor)
    oracle_ap_n3 = metric_at(oracle_curve, high_noise, "ap50", default=oracle_ap_anchor)

    ap_drop_n3 = max(0.0, target_ap_n0 - target_ap_n3)

    pose_tail_n0 = metric_at(target_curve, low_noise, "mean_rel_trans_m", default=1.0)
    pose_tail_n3 = metric_at(target_curve, high_noise, "mean_rel_trans_m", default=999.0)
    pose_ratio = pose_tail_n3 / max(pose_tail_n0, 1e-6)

    rel_trans_vals = [
        metric_at(target_curve, n, "mean_rel_trans_m", default=999.0)
        for n in target_noises
        if "mean_rel_trans_m" in target_curve.get(n, {})
    ]
    rel_yaw_vals = [
        metric_at(target_curve, n, "mean_rel_yaw_deg", default=999.0)
        for n in target_noises
        if "mean_rel_yaw_deg" in target_curve.get(n, {})
    ]

    geometry_row: Dict[str, float] = {
        "rpe_xy_obj_p50": percentile(rel_trans_vals, 0.50, default=999.0),
        "rpe_xy_obj_p95": percentile(rel_trans_vals, 0.95, default=999.0),
        "rpe_yaw_obj_p50": percentile(rel_yaw_vals, 0.50, default=999.0),
        "rpe_yaw_obj_p95": percentile(rel_yaw_vals, 0.95, default=999.0),
        # Missing in local benchmark export: explicit placeholders.
        "depth_abs_rel_fg": 999.0,
        "depth_rmse_fg_0_20": 999.0,
        "depth_rmse_fg_20_40": 999.0,
        "depth_rmse_fg_40_70": 999.0,
        "scale_err_global": 999.0,
        "scale_err_obj_lwh": 999.0,
        "range_scale_err_obj": 999.0,
        "noise_min": float(low_noise),
        "noise_max": float(high_noise),
        "target_ap50_mean": mean([metric_at(target_curve, n, "ap50", default=0.0) for n in target_noises], default=0.0),
        "baseline_ap50_mean": mean([metric_at(baseline_curve, n, "ap50", default=0.0) for n in target_noises], default=0.0),
        "oracle_ap50_mean": mean([metric_at(oracle_curve, n, "ap50", default=0.0) for n in target_noises], default=0.0),
        "target_minus_baseline_mean": 0.0,
        "oracle_minus_target_mean": 0.0,
    }
    geometry_row["target_minus_baseline_mean"] = geometry_row["target_ap50_mean"] - geometry_row["baseline_ap50_mean"]
    geometry_row["oracle_minus_target_mean"] = geometry_row["oracle_ap50_mean"] - geometry_row["target_ap50_mean"]

    detection_row: Dict[str, float] = {
        "ap_0_5": clamp(as_number(target_ap_anchor, 0.0), 0.0, 1.0),
        "ap_0_7": clamp(as_number(target_ap70_anchor, 0.0), 0.0, 1.0),
        "baseline_ap_0_5": clamp(as_number(baseline_ap_anchor, target_ap_anchor), 0.0, 1.0),
        "baseline_ap_0_7": clamp(as_number(baseline_ap70_anchor, target_ap70_anchor), 0.0, 1.0),
        "oracle_ap_0_5": clamp(as_number(oracle_ap_anchor, target_ap_anchor), 0.0, 1.0),
        "oracle_ap_0_7": clamp(as_number(oracle_ap70_anchor, target_ap70_anchor), 0.0, 1.0),
        "target_ap_0_5": clamp(as_number(target_ap_anchor, 0.0), 0.0, 1.0),
        "target_ap_0_7": clamp(as_number(target_ap70_anchor, 0.0), 0.0, 1.0),
        "anchor_noise": float(anchor_noise),
    }

    robust_row: Dict[str, float] = {
        "ap_drop_n3": clamp(as_number(ap_drop_n3, 1.0), 0.0, 1.0),
        "pose_tail_obj_p95_n3": as_number(pose_tail_n3, 999.0),
        "pose_tail_obj_p95_n0": as_number(pose_tail_n0, 1.0),
        "pose_tail_obj_p95_degrade_ratio": as_number(pose_ratio, 999.0),
        "robust_score": 0.0,
        "target_ap_n0": clamp(as_number(target_ap_n0, 0.0), 0.0, 1.0),
        "target_ap_n3": clamp(as_number(target_ap_n3, 0.0), 0.0, 1.0),
        "baseline_ap_n0": clamp(as_number(baseline_ap_n0, 0.0), 0.0, 1.0),
        "baseline_ap_n3": clamp(as_number(baseline_ap_n3, 0.0), 0.0, 1.0),
        "oracle_ap_n0": clamp(as_number(oracle_ap_n0, 0.0), 0.0, 1.0),
        "oracle_ap_n3": clamp(as_number(oracle_ap_n3, 0.0), 0.0, 1.0),
    }
    robust_row["robust_score"] = robust_score(
        ap05=detection_row["ap_0_5"],
        ap07=detection_row["ap_0_7"],
        ap_drop_n3=robust_row["ap_drop_n3"],
        pose_tail_n3=robust_row["pose_tail_obj_p95_n3"],
    )

    results_hash = sha256_of_file(results_path)
    source_key_hash = sha256_text(str(source_dir))

    # Idempotency: if a bundle already exists for this source+matrix, reuse its run_id
    # to avoid Project noise explosions on re-export.
    run_id = find_existing_run_id(args.output_root, results_path=results_path, args=args)
    if not run_id:
        run_id = build_run_id(idx=idx, args=args, source_dir=source_dir, source_key_hash=source_key_hash)

    bundle_dir = args.output_root / run_id
    config_path = choose_config_path(source_dir)
    dataset_root = infer_dataset_root(source_dir, source_obj)

    frames_proxy = build_frames_proxy(
        source_dir=source_dir,
        source_obj=source_obj,
        dataset_root=dataset_root,
        pack=str(args.pack),
        selected_entries=selected_entries,
        target_noises=target_noises,
    )
    frames_proxy_text = json.dumps(frames_proxy, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    # Make the hash equal to the on-disk split file bytes (more intuitive + reproducible).
    frames_json_sha256 = sha256_text(frames_proxy_text)
    split_file = "frames_proxy.json"

    manifest: Dict[str, Any] = {
        "run_id": run_id,
        "server": args.server,
        "line": args.line,
        "repo": repo_root.name,
        "branch": repo_branch,
        "commit": repo_commit,
        "config_path": str(config_path.resolve()),
        "pack": args.pack,
        "mode": args.mode,
        "noise": args.noise,
        "dropout": args.dropout,
        "seed": int(args.seed),
        "frames_json_sha256": frames_json_sha256,
        "input_contract": {
            "uses_cross_agent_gt_extrinsics": False,
            "uses_gt_depth_as_input": False,
            "uses_gps_init": bool(args.mode == "M1"),
            "notes": "transition export from local benchmark summary",
        },
        "dataset_root": dataset_root,
        "split_file": split_file,
        "metrics_schema_version": "eval_v2_1_transition_proxy_v1",
        "bundle_created_at": now_iso(),
        "owner": args.owner,
        "legacy_geometry_proxy": True,
        "legacy_det_only": False,
        "source_run_id": source_obj.get("run_id", source_dir.name),
        "source_results_json": str(results_path),
        "source_results_sha256": results_hash,
        "transition_proxy": True,
        "source_name": source_dir.name,
        "selection": {
            "prefer_sweep": args.prefer_sweep,
            "baseline": {"method": baseline_key[0], "strategy": baseline_key[1]},
            "oracle": {"method": oracle_key[0], "strategy": oracle_key[1]},
            "target": {"method": target_key[0], "strategy": target_key[1]},
            "noise_axis": [float(x) for x in target_noises],
            "anchor_noise": float(anchor_noise),
            "low_noise": float(low_noise),
            "high_noise": float(high_noise),
        },
        "baseline_detection": {
            "ap_0_5": detection_row["baseline_ap_0_5"],
            "ap_0_7": detection_row["baseline_ap_0_7"],
        },
    }

    summary_lines = [
        "# Transition Export Summary",
        "",
        f"- source_dir: `{source_dir}`",
        f"- source_results_json: `{results_path}`",
        f"- source_run_id: `{source_obj.get('run_id', source_dir.name)}`",
        f"- selected_entries: {len(selected_entries)} (prefer_sweep={args.prefer_sweep})",
        f"- dataset_root: `{dataset_root}`",
        f"- split_file: `{split_file}` (proxy)",
        f"- frames_json_sha256: `{frames_json_sha256}` (sha256(frames_proxy.json))",
        f"- baseline_line: `{baseline_key[0]}/{baseline_key[1]}`",
        f"- oracle_line: `{oracle_key[0]}/{oracle_key[1]}`",
        f"- target_line: `{target_key[0]}/{target_key[1]}`",
        f"- target_noise_axis: {', '.join(target_noises)}",
        f"- anchor_noise_for_{args.noise}: {anchor_noise}",
        f"- ap50(anchor): baseline={detection_row['baseline_ap_0_5']:.6f}, target={detection_row['ap_0_5']:.6f}, oracle={detection_row['oracle_ap_0_5']:.6f}",
        "",
        "## Transition Flags",
        "",
        "- `legacy_geometry_proxy=true`: transition-only governance ingestion artifact, not full object-level geometry eval.",
        "- `depth_*` / `scale_*` are currently missing and use `999.0` placeholders; G1/G2 are expected to be blocked.",
        "- CSV files keep required eval_v2_1 columns and all values remain numeric-parseable.",
        "",
        "## Notes",
        "",
        "- `frames_proxy.json` is a temporary stand-in for the real frames split; it is used only to make frames_json_sha256 stable across reruns.",
        "- Once object-level depth/scale metrics are available, replace placeholder columns and rerun gates.",
    ]

    if args.dry_run:
        return bundle_dir

    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "manifest.yaml").write_text(
        yaml_dump_text(manifest),
        encoding="utf-8",
    )
    (bundle_dir / split_file).write_text(
        frames_proxy_text,
        encoding="utf-8",
    )
    write_csv(bundle_dir / "metrics_geometry.csv", GEOMETRY_COLUMNS, geometry_row)
    write_csv(bundle_dir / "metrics_detection.csv", DETECTION_COLUMNS, detection_row)
    write_csv(bundle_dir / "metrics_robustness.csv", ROBUSTNESS_COLUMNS, robust_row)
    (bundle_dir / "summary.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    write_required_visuals(
        bundle_dir,
        summary_hint=(
            "legacy transition export; depth/scale placeholders are expected "
            "until object-level geometry metrics are integrated"
        ),
    )

    return bundle_dir


def main() -> int:
    args = parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    repo_branch = git_value(repo_root, ["rev-parse", "--abbrev-ref", "HEAD"], "unknown")
    repo_commit = git_value(repo_root, ["rev-parse", "HEAD"], "unknown")

    created: List[Path] = []
    for i, src in enumerate(args.source):
        bundle = export_source(
            source_dir=src,
            args=args,
            repo_root=repo_root,
            repo_branch=repo_branch,
            repo_commit=repo_commit,
            idx=i,
        )
        created.append(bundle)
        tag = "DRY" if args.dry_run else "OK"
        print(f"[{tag}] {src} -> {bundle}")

    print(f"total={len(created)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
