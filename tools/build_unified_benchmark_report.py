#!/usr/bin/env python3
"""Build unified benchmark tables from canonical DAIR/OPV2V/TableIII artifacts.

This script is intentionally read-only on experiment artifacts. It aggregates
existing outputs into traceable CSV/JSON files so comparisons can be reproduced
without re-running expensive benchmarks.
"""

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]

DEFAULT_DAIR_SWEEP = ROOT / "outputs" / "pose_sweep_1to10_full_gpuvoxel20260218_results.jsonl"
DEFAULT_OPV2V_RUN_DIR = ROOT / "outputs" / "full_bench_opv2v_autopilot_full_20260216_auto3_a1"
DEFAULT_TABLE3_MD = ROOT / "docs" / "operations" / "table3_paper3737_repro_status.md"

NOISE_AXIS_1_TO_10 = ["%.1f" % float(i) for i in range(1, 11)]
CORE_METHODS = (
    "baseline",
    "oracle",
    "v2xregpp",
    "freealign",
    "vips",
    "cbm",
    "vips_prior",
    "cbm_prior",
    "imagematch_noinit",
    "imagematch_current",
    "lidarreg_ransac",
    "hkust_teaser",
    "hkust_fgr",
    "hkust_quatro",
)

METHOD_FAMILY = {
    "baseline": "bound",
    "oracle": "bound",
    "single": "bound",
    "v2xregpp": "v2xregpp",
    "v2xregpp_occhint": "v2xregpp",
    "freealign": "freealign",
    "vips": "vips",
    "vips_prior": "vips",
    "cbm": "cbm",
    "cbm_prior": "cbm",
    "imagematch_noinit": "imagematch",
    "imagematch_current": "imagematch",
    "lidarreg_ransac": "hkust_like",
    "hkust_teaser": "hkust",
    "hkust_fgr": "hkust",
    "hkust_quatro": "hkust",
}

METHOD_INIT_CLASS = {
    "baseline": "bound",
    "oracle": "bound",
    "single": "bound",
    "vips_prior": "with_init",
    "cbm_prior": "with_init",
    "imagematch_current": "with_init",
    "vips": "no_init",
    "cbm": "no_init",
    "v2xregpp": "no_init",
    "freealign": "no_init",
    "v2xregpp_occhint": "no_init",
    "imagematch_noinit": "no_init",
    "lidarreg_ransac": "no_init_hkust_like",
    "hkust_teaser": "no_init_hkust",
    "hkust_fgr": "no_init_hkust",
    "hkust_quatro": "no_init_hkust",
}


def _norm_noise(v):
    return "%.1f" % float(v)


def _mean(values):
    if not values:
        return None
    return float(sum(values) / len(values))


def _method_family(method):
    return METHOD_FAMILY.get(str(method), "other")


def _method_init_class(method):
    return METHOD_INIT_CLASS.get(str(method), "unknown")


def _write_csv(path, rows, header):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _load_jsonl(path):
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def build_dair_table(dair_jsonl):
    rows = _load_jsonl(dair_jsonl)
    out = []
    for r in rows:
        out.append(
            {
                "dataset": "DAIR-V2X",
                "suite": "noise10",
                "noise_axis": "1..10",
                "modality": r.get("modality"),
                "method": r.get("method"),
                "strategy": r.get("strategy"),
                "method_family": _method_family(r.get("method")),
                "method_init_class": _method_init_class(r.get("method")),
                "mean_ap30": r.get("mean_ap30"),
                "mean_ap50": r.get("mean_ap50"),
                "mean_ap70": r.get("mean_ap70"),
                "success_at_1m": r.get("success_at_1m"),
                "success_at_2m": r.get("success_at_2m"),
                "success_at_3m": r.get("success_at_3m"),
                "success_at_5m": r.get("success_at_5m"),
                "mean_rel_trans_m": r.get("mean_rel_trans_m"),
                "mean_rel_yaw_deg": r.get("mean_rel_yaw_deg"),
                "mean_pose_time_sec": r.get("mean_pose_time_sec"),
                "mean_infer_fps": r.get("mean_infer_fps"),
                "source_yaml": r.get("yaml_path"),
                "source_jsonl": str(dair_jsonl.relative_to(ROOT)),
            }
        )
    return out


def _parse_opv2v_ap_entries(run_dir):
    obj = json.loads((run_dir / "results_ap50_from_yaml.json").read_text(encoding="utf-8"))
    entries = obj.get("entries") or []
    ap_map = {}
    for e in entries:
        key = (
            str(e.get("modality")),
            str(e.get("sweep")),
            str(e.get("method")),
            str(e.get("strategy")),
            _norm_noise(e.get("noise")),
        )
        ap_map[key] = e
    return obj, ap_map


def _parse_opv2v_filename(path, run_id):
    stem = path.stem
    marker = "_%s_" % run_id
    pos = stem.find(marker)
    if pos < 0 or not stem.startswith("AP030507_"):
        return None
    remainder = stem[pos + len(marker) :]

    m = re.match(r"^(camera|lidar)_(noise10|drop20)_single$", remainder)
    if m:
        mod, sweep = m.groups()
        return (mod, sweep, "single", "bounds", "0.0")

    m = re.match(r"^(camera|lidar)_(noise10|drop20)_(baseline|oracle)_n([0-9.]+)$", remainder)
    if m:
        mod, sweep, method, noise = m.groups()
        return (mod, sweep, method, "bounds", _norm_noise(noise))

    m = re.match(r"^(camera|lidar)_(noise10|drop20)_([a-z0-9_]+)_(best|stable)_n([0-9.]+)$", remainder)
    if m:
        mod, sweep, method, strategy, noise = m.groups()
        return (mod, sweep, method, strategy, _norm_noise(noise))

    return None


def _parse_opv2v_rel_stats(run_dir, run_id):
    cfg = json.loads((run_dir / "config_snapshot.json").read_text(encoding="utf-8"))
    model_dirs = [Path(cfg["camera_model"]), Path(cfg["lidar_model"])]

    rel_map = {}
    for model_dir in model_dirs:
        if not model_dir.exists():
            continue
        for path in sorted(model_dir.glob("AP030507_*.yaml")):
            key = _parse_opv2v_filename(path, run_id=run_id)
            if key is None:
                continue
            try:
                obj = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
            rel_stats = obj.get("rel_error_stats") or []
            if not isinstance(rel_stats, list) or not rel_stats:
                continue
            entry0 = rel_stats[0] if isinstance(rel_stats[0], dict) else {}
            rel_t = (entry0.get("rel_trans_m") or {}).get("mean") if isinstance(entry0, dict) else None
            rel_y = (entry0.get("rel_yaw_deg") or {}).get("mean") if isinstance(entry0, dict) else None
            succ2 = (entry0.get("rel_success_at_m") or {}).get("2") if isinstance(entry0, dict) else None
            rec = {
                "mean_rel_trans_m": float(rel_t) if rel_t is not None else None,
                "mean_rel_yaw_deg": float(rel_y) if rel_y is not None else None,
                "success_at_2m": float(succ2) if succ2 is not None else None,
                "source_yaml": str(path.relative_to(ROOT)),
            }
            # Prefer newer files if duplicated keys exist.
            mtime = path.stat().st_mtime
            old = rel_map.get(key)
            if old is None or mtime >= old.get("_mtime", -1):
                rec["_mtime"] = mtime
                rel_map[key] = rec

    for v in rel_map.values():
        v.pop("_mtime", None)
    return rel_map


def build_opv2v_table(opv2v_run_dir):
    obj, ap_map = _parse_opv2v_ap_entries(opv2v_run_dir)
    run_id = obj.get("run_id")
    if not run_id:
        # outputs/full_bench_<run_id>
        name = opv2v_run_dir.name
        run_id = name[len("full_bench_") :] if name.startswith("full_bench_") else name

    rel_map = _parse_opv2v_rel_stats(opv2v_run_dir, run_id=run_id)

    valid_methods = set(CORE_METHODS) | {"single"}
    sweeps = ("noise10", "drop20")
    modalities = ("camera", "lidar")

    out_rows = []
    grouped = defaultdict(list)

    for key, e in ap_map.items():
        mod, sweep, method, strategy, noise = key
        if method not in valid_methods:
            continue
        if sweep not in sweeps or mod not in modalities:
            continue

        # Unified rule: compare methods on noise 1..10; single uses its only point n=0.
        if method == "single":
            if noise != "0.0":
                continue
        else:
            if noise not in NOISE_AXIS_1_TO_10:
                continue

        grouped[(mod, sweep, method, strategy)].append((noise, e, rel_map.get(key)))

    for (mod, sweep, method, strategy), items in sorted(grouped.items()):
        items = sorted(items, key=lambda x: float(x[0]))
        ap30 = [float(it[1].get("ap30")) for it in items if it[1].get("ap30") is not None]
        ap50 = [float(it[1].get("ap50")) for it in items if it[1].get("ap50") is not None]
        ap70 = [float(it[1].get("ap70")) for it in items if it[1].get("ap70") is not None]
        infer_fps = [float(it[1].get("infer_fps")) for it in items if it[1].get("infer_fps") is not None]

        rel_t = [float(it[2]["mean_rel_trans_m"]) for it in items if it[2] and it[2].get("mean_rel_trans_m") is not None]
        rel_y = [float(it[2]["mean_rel_yaw_deg"]) for it in items if it[2] and it[2].get("mean_rel_yaw_deg") is not None]
        succ2 = [float(it[2]["success_at_2m"]) for it in items if it[2] and it[2].get("success_at_2m") is not None]

        source_yamls = [it[2].get("source_yaml") for it in items if it[2] and it[2].get("source_yaml")]
        source_yamls = sorted(set(source_yamls))

        out_rows.append(
            {
                "dataset": "OPV2V",
                "suite": sweep,
                "noise_axis": "0(single)" if method == "single" else "1..10",
                "modality": mod,
                "method": method,
                "strategy": strategy,
                "method_family": _method_family(method),
                "method_init_class": _method_init_class(method),
                "mean_ap30": _mean(ap30),
                "mean_ap50": _mean(ap50),
                "mean_ap70": _mean(ap70),
                "success_at_2m": _mean(succ2),
                "mean_rel_trans_m": _mean(rel_t),
                "mean_rel_yaw_deg": _mean(rel_y),
                "mean_infer_fps": _mean(infer_fps),
                "num_points": len(items),
                "run_id": run_id,
                "source_results_json": str((opv2v_run_dir / "results_ap50_from_yaml.json").relative_to(ROOT)),
                "source_yaml_count": len(source_yamls),
                "source_yaml_first": source_yamls[0] if source_yamls else "",
            }
        )

    return out_rows


def build_opv2v_coverage(opv2v_run_dir):
    obj = json.loads((opv2v_run_dir / "results_ap50_from_yaml.json").read_text(encoding="utf-8"))
    entries = obj.get("entries") or []

    def _has(mod, sweep, method, strategy, noise):
        noise = _norm_noise(noise)
        for e in entries:
            if (
                str(e.get("modality")) == mod
                and str(e.get("sweep")) == sweep
                and str(e.get("method")) == method
                and str(e.get("strategy")) == strategy
                and _norm_noise(e.get("noise")) == noise
            ):
                return True
        return False

    missing = []
    for mod in ("camera", "lidar"):
        for sweep in ("noise10", "drop20"):
            for method in ("baseline", "oracle"):
                for n in NOISE_AXIS_1_TO_10:
                    if not _has(mod, sweep, method, "bounds", n):
                        missing.append([mod, sweep, method, "bounds", n])
            if not _has(mod, sweep, "single", "bounds", "0.0"):
                missing.append([mod, sweep, "single", "bounds", "0.0"])
            for method in ("v2xregpp", "freealign", "vips", "cbm"):
                for strategy in ("best", "stable"):
                    for n in NOISE_AXIS_1_TO_10:
                        if not _has(mod, sweep, method, strategy, n):
                            missing.append([mod, sweep, method, strategy, n])

    occhint_counts = {}
    for mod in ("camera", "lidar"):
        for sweep in ("noise10", "drop20"):
            c = 0
            for e in entries:
                if (
                    str(e.get("modality")) == mod
                    and str(e.get("sweep")) == sweep
                    and str(e.get("method")) == "v2xregpp_occhint"
                ):
                    c += 1
            occhint_counts["%s/%s" % (mod, sweep)] = c

    return {
        "run_dir": str(opv2v_run_dir.relative_to(ROOT)),
        "total_entries": len(entries),
        "missing_core_scope": missing,
        "missing_core_count": len(missing),
        "occhint_counts": occhint_counts,
        "note": "Core unified scope excludes v2xregpp_occhint because it is camera-only append (lidar not available).",
    }


def _infer_init_mode(row_name, best_source):
    source = best_source.lower()
    if row_name.startswith("ICP") or row_name.startswith("PICP"):
        return "needs_init"
    if row_name.startswith("VIPS") or row_name.startswith("CBM"):
        if "initgt" in source:
            return "has_init_gt"
        if "initunadj" in source:
            return "has_init_unadjusted"
        if "initfree" in source:
            return "no_init"
        return "mixed_or_unknown"
    if row_name in ("FGR", "Quatro", "Teaser++"):
        return "no_init_global"
    if row_name.startswith("V2X-Reg"):
        return "no_init_object_matching"
    return "unknown"


def build_table3_best_rows(table3_md):
    rows = []
    for line in table3_md.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| "):
            continue
        if line.startswith("| Row") or line.startswith("|---"):
            continue
        parts = [x.strip() for x in line.strip("|").split("|")]
        if len(parts) < 8:
            continue
        row_name = parts[0]
        succ_cell = parts[1]
        rte_cell = parts[2]
        rre_cell = parts[3]
        time_cell = parts[4]
        best_source = parts[6].strip("`")

        m_s = re.search(r"best: ([0-9.]+)/([0-9.]+)/([0-9.]+)", succ_cell)
        m_t = re.search(r"best: ([0-9.]+)/([0-9.]+)/([0-9.]+)", rte_cell)
        m_r = re.search(r"best: ([0-9.]+)/([0-9.]+)/([0-9.]+)", rre_cell)
        m_tm = re.search(r"best: ([0-9.]+)", time_cell)

        if not m_s:
            continue
        rows.append(
            {
                "dataset": "DAIR-V2X-paper3737",
                "suite": "table3_te_re",
                "method_row": row_name,
                "best_success_at_1m_pct": float(m_s.group(1)),
                "best_success_at_2m_pct": float(m_s.group(2)),
                "best_success_at_3m_pct": float(m_s.group(3)),
                "best_mRTE_at_1m": float(m_t.group(1)) if m_t else None,
                "best_mRTE_at_2m": float(m_t.group(2)) if m_t else None,
                "best_mRTE_at_3m": float(m_t.group(3)) if m_t else None,
                "best_mRRE_at_1m": float(m_r.group(1)) if m_r else None,
                "best_mRRE_at_2m": float(m_r.group(2)) if m_r else None,
                "best_mRRE_at_3m": float(m_r.group(3)) if m_r else None,
                "best_time_sec": float(m_tm.group(1)) if m_tm else None,
                "init_mode": _infer_init_mode(row_name, best_source),
                "best_source": best_source,
                "source_table_doc": str(table3_md.relative_to(ROOT)),
            }
        )
    return rows


def parse_args():
    p = argparse.ArgumentParser(description="Build unified benchmark report tables.")
    p.add_argument("--dair-sweep", type=Path, default=DEFAULT_DAIR_SWEEP)
    p.add_argument("--opv2v-run-dir", type=Path, default=DEFAULT_OPV2V_RUN_DIR)
    p.add_argument("--table3-md", type=Path, default=DEFAULT_TABLE3_MD)
    p.add_argument("--out-dir", type=Path, default=ROOT / "outputs" / "benchmark_unified_20260220")
    return p.parse_args()


def main():
    args = parse_args()

    dair_rows = build_dair_table(args.dair_sweep)
    opv2v_rows = build_opv2v_table(args.opv2v_run_dir)
    table3_rows = build_table3_best_rows(args.table3_md)
    coverage = build_opv2v_coverage(args.opv2v_run_dir)

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    dair_csv = out_dir / "dair_noise10_ap_reg.csv"
    opv2v_csv = out_dir / "opv2v_dual_suite_ap_reg.csv"
    table3_csv = out_dir / "dair_table3_best_te_re.csv"
    coverage_json = out_dir / "coverage_checks.json"

    _write_csv(
        dair_csv,
        dair_rows,
        header=[
            "dataset",
            "suite",
            "noise_axis",
            "modality",
            "method",
            "strategy",
            "method_family",
            "method_init_class",
            "mean_ap30",
            "mean_ap50",
            "mean_ap70",
            "success_at_1m",
            "success_at_2m",
            "success_at_3m",
            "success_at_5m",
            "mean_rel_trans_m",
            "mean_rel_yaw_deg",
            "mean_pose_time_sec",
            "mean_infer_fps",
            "source_yaml",
            "source_jsonl",
        ],
    )

    _write_csv(
        opv2v_csv,
        opv2v_rows,
        header=[
            "dataset",
            "suite",
            "noise_axis",
            "modality",
            "method",
            "strategy",
            "method_family",
            "method_init_class",
            "mean_ap30",
            "mean_ap50",
            "mean_ap70",
            "success_at_2m",
            "mean_rel_trans_m",
            "mean_rel_yaw_deg",
            "mean_infer_fps",
            "num_points",
            "run_id",
            "source_results_json",
            "source_yaml_count",
            "source_yaml_first",
        ],
    )

    _write_csv(
        table3_csv,
        table3_rows,
        header=[
            "dataset",
            "suite",
            "method_row",
            "best_success_at_1m_pct",
            "best_success_at_2m_pct",
            "best_success_at_3m_pct",
            "best_mRTE_at_1m",
            "best_mRTE_at_2m",
            "best_mRTE_at_3m",
            "best_mRRE_at_1m",
            "best_mRRE_at_2m",
            "best_mRRE_at_3m",
            "best_time_sec",
            "init_mode",
            "best_source",
            "source_table_doc",
        ],
    )

    coverage_json.write_text(json.dumps(coverage, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = {
        "out_dir": str(out_dir.relative_to(ROOT)),
        "dair_rows": len(dair_rows),
        "opv2v_rows": len(opv2v_rows),
        "table3_rows": len(table3_rows),
        "opv2v_missing_core_count": coverage.get("missing_core_count", -1),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
