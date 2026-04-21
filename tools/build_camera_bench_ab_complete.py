#!/usr/bin/env python3
"""Build the most complete camera Bench A / Bench B figures.

Outputs:
- strict Bench A / Bench B control lines (baseline / oracle / single)
- merged Bench A / Bench B camera summaries
- final figures with bounds + four registration methods
- a provenance report
"""

import argparse
import json
import os
import shlex
import subprocess
import time
from collections import deque
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
PY39 = ROOT / ".micromamba" / "envs" / "py39" / "bin" / "python"
INFER = ROOT / "HEAL" / "opencood" / "tools" / "inference_w_noise.py"
OUTPUT_DIR = ROOT / "outputs" / "camera_bench_ab_complete_20260408"
CONTROL_DIR = OUTPUT_DIR / "control_runs"
LIDAR_CONTEXT_DIR = ROOT / "outputs" / "bench_ab_camera_lidar_original_standard_20260403"
LIDAR_CONTEXT_REPORT = LIDAR_CONTEXT_DIR / "bench_ab_camera_lidar_original_report.md"
LIDAR_CONTEXT_FIGURES = {
    "bench_a": LIDAR_CONTEXT_DIR / "unified_noise_curve_benchmark_lidar_noinit_ap50.svg",
    "bench_b": LIDAR_CONTEXT_DIR / "unified_noise_curve_benchmark_lidar_ap50.svg",
}
POSECONF_RUNNER = ROOT / "tools" / "run_camera_poseconf_fix_benchmark.py"
INFER_SCRIPT = ROOT / "HEAL" / "opencood" / "tools" / "inference_w_noise.py"
FROZEN_CONTROL_SOURCES = {
    "bench_a": {
        "dair": ROOT / "outputs" / "dair_core_phase11_dair_bimodal_trackd_coreplusstable_noise10_20260310_p1" / "camera" / "results_ap50_from_yaml.json",
        "opv2v": ROOT / "outputs" / "full_bench_phase11_opv2v_bimodal_trackd_coreplusstable_noise10_20260310_p1" / "results_ap50_from_yaml.json",
    },
    "bench_b": {
        "dair": ROOT / "outputs" / "dair_core_phase11_dair_bimodal_tracks_coreplusstable_noise10_20260310_p1" / "camera" / "results_ap50_from_yaml.json",
        "opv2v": ROOT / "outputs" / "full_bench_phase11_opv2v_bimodal_tracks_coreplusstable_noise10_20260310_p1" / "results_ap50_from_yaml.json",
    },
}

CANDIDATE_BENCH_A = (
    ROOT / "outputs" / "bench_ab_camera_lidar_original_standard_20260403" / "camera_bench_a_noinit_canonical_results_ap50.json"
)
CANDIDATE_BENCH_B = (
    ROOT / "outputs" / "bench_ab_camera_lidar_original_standard_20260403" / "camera_bench_b_init_canonical_results_ap50.json"
)

DATASETS = {
    "dair": {
        "dataset_name": "DAIR-V2X",
        "model_dir": ROOT / "HEAL" / "opencood" / "logs" / "HeterBaseline_DAIR_camera_v2xvit_2023_09_09_11_27_38",
        "comm_range": 100,
    },
    "opv2v": {
        "dataset_name": "OPV2V",
        "model_dir": ROOT / "HEAL" / "opencood" / "logs" / "opv2v_camera_v2xvit_full_prope",
        "comm_range": 70,
    },
}

BENCH_CFG = {
    "bench_a": {
        "family": "noinit_nofallback",
        "title": "Bench A (No-Init / No-Fallback)",
        "noise_axis": ["0.0", "7.0", "10.0"],
        "comm_range_gating": "clean",
        "candidate_json": CANDIDATE_BENCH_A,
    },
    "bench_b": {
        "family": "init_choosebetter",
        "title": "Bench B (Init / Choose-Better)",
        "noise_axis": ["%.1f" % float(i) for i in range(11)],
        "comm_range_gating": "noisy",
        "candidate_json": CANDIDATE_BENCH_B,
    },
}

CONTROL_SPECS = {
    "baseline": {
        "pose_correction": "none",
        "extra_args": [],
        "legend_label": "baseline",
        "color": "#7f7f7f",
        "marker": "x",
        "single_point_only": False,
    },
    "oracle": {
        "pose_correction": "oracle_gt",
        "extra_args": [],
        "legend_label": "oracle",
        "color": "#9467bd",
        "marker": "P",
        "single_point_only": False,
    },
    "single": {
        "pose_correction": "none",
        "extra_args": ["--force-ego-input-only"],
        "legend_label": "single",
        "color": "#000000",
        "marker": "X",
        "single_point_only": True,
    },
}

METHOD_STYLES = {
    "baseline": {"color": "#7f7f7f", "marker": "x", "label": "baseline"},
    "oracle": {"color": "#9467bd", "marker": "P", "label": "oracle"},
    "single": {"color": "#000000", "marker": "X", "label": "single"},
    "v2xregpp": {"color": "#2166ac", "marker": "o", "label": "v2xregpp"},
    "freealign": {"color": "#ef8a0c", "marker": "s", "label": "freealign"},
    "vips": {"color": "#1a9850", "marker": "D", "label": "vips"},
    "cbm": {"color": "#b2182b", "marker": "^", "label": "cbm"},
}
PLOT_ORDER = ["baseline", "oracle", "single", "v2xregpp", "freealign", "vips", "cbm"]
DATASET_ORDER = ["dair", "opv2v"]
DATASET_TITLE = {"dair": "DAIR-V2X", "opv2v": "OPV2V"}


def _load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def _fmt_float(value):
    if value is None:
        return "n/a"
    return "%.4f" % float(value)


def _payload_entries(payload, *, dataset=None, method=None, noises=None):
    noise_filter = None if noises is None else set(str(x) for x in noises)
    out = []
    for entry in payload.get("entries") or []:
        if dataset is not None and str(entry.get("dataset")) != str(dataset):
            continue
        if method is not None and str(entry.get("method")) != str(method):
            continue
        if noise_filter is not None and ("%.1f" % float(entry.get("noise"))) not in noise_filter:
            continue
        out.append(entry)
    return out


def _mean_ap50(entries):
    values = [float(entry["ap50"]) for entry in entries if isinstance(entry.get("ap50"), (int, float))]
    if not values:
        return None
    return float(sum(values) / float(len(values)))


def _best_entry(entries):
    valid = [entry for entry in entries if isinstance(entry.get("ap50"), (int, float))]
    if not valid:
        return None
    return max(valid, key=lambda entry: float(entry["ap50"]))


def _shell_join(args):
    return " ".join(shlex.quote(str(x)) for x in args)


def _predict_yaml_path(model_dir, pose_correction, note):
    return Path(model_dir) / ("AP030507_%s%s.yaml" % (pose_correction, note))


def _build_control_jobs():
    jobs = []
    date_tag = "20260408"
    for bench_key, bench_cfg in BENCH_CFG.items():
        for dataset, ds in DATASETS.items():
            for method, spec in CONTROL_SPECS.items():
                noise_axis = ["0.0"] if spec["single_point_only"] else list(bench_cfg["noise_axis"])
                note = "_camera_bench_control_%s_%s_%s_%s" % (
                    date_tag,
                    bench_key,
                    dataset,
                    method,
                )
                yaml_path = _predict_yaml_path(ds["model_dir"], spec["pose_correction"], note)
                log_path = CONTROL_DIR / bench_key / "logs" / ("%s_%s.log" % (dataset, method))
                args = [
                    PY39,
                    INFER,
                    "--model_dir",
                    ds["model_dir"],
                    "--fusion_method",
                    "intermediate",
                    "--pose-correction",
                    spec["pose_correction"],
                    "--pose-source",
                    "noisy_input",
                    "--comm-range-override",
                    ds["comm_range"],
                    "--comm-range-gating",
                    bench_cfg["comm_range_gating"],
                    "--noise-target",
                    "non-ego",
                    "--sweep-mode",
                    "paired",
                    "--pos-std-list",
                    ",".join(noise_axis),
                    "--rot-std-list",
                    ",".join(noise_axis),
                    "--num-workers",
                    "0",
                    "--save_vis_interval",
                    "100000000",
                    "--note",
                    note,
                    "--force-pose-confidence",
                    "1.0",
                ] + list(spec["extra_args"])
                jobs.append(
                    {
                        "bench": bench_key,
                        "family": bench_cfg["family"],
                        "dataset": dataset,
                        "dataset_name": ds["dataset_name"],
                        "method": method,
                        "legend_label": spec["legend_label"],
                        "pose_correction": spec["pose_correction"],
                        "noise_axis": list(noise_axis),
                        "family_noise_axis": list(bench_cfg["noise_axis"]),
                        "comm_range_gating": bench_cfg["comm_range_gating"],
                        "force_pose_confidence": 1.0,
                        "yaml_path": str(yaml_path),
                        "log_path": str(log_path),
                        "cmd": _shell_join(args),
                    }
                )
    return jobs


def _run_control_jobs(jobs, gpus, max_per_gpu):
    pending = [job for job in jobs if not Path(job["yaml_path"]).exists()]
    if not pending:
        return

    parent_visible = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    gpu_slots = dict((gpu, []) for gpu in gpus)
    queue = deque(pending)

    def _launch_env(gpu):
        env = os.environ.copy()
        parent_visible_list = [x.strip() for x in str(parent_visible or "").split(",") if x.strip()]
        if parent_visible_list:
            if 0 <= int(gpu) < len(parent_visible_list):
                env["CUDA_VISIBLE_DEVICES"] = parent_visible_list[int(gpu)]
            else:
                env["CUDA_VISIBLE_DEVICES"] = str(gpu)
        else:
            env["CUDA_VISIBLE_DEVICES"] = str(gpu)
        heal_path = str(ROOT / "HEAL")
        existing_py = str(env.get("PYTHONPATH", "") or "").strip()
        env["PYTHONPATH"] = heal_path if not existing_py else heal_path + os.pathsep + existing_py
        env["PYTHONUNBUFFERED"] = "1"
        env.setdefault("OMP_NUM_THREADS", "1")
        env.setdefault("MKL_NUM_THREADS", "1")
        env.setdefault("OPENBLAS_NUM_THREADS", "1")
        env.setdefault("NUMEXPR_NUM_THREADS", "1")
        return env

    def launch(job, gpu):
        env = _launch_env(gpu)
        log_path = Path(job["log_path"])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_f = open(str(log_path), "a", encoding="utf-8")
        log_f.write(
            "\n" + "=" * 80 + "\n" + "[LAUNCH] time=%s gpu=%s cmd=%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), gpu, job["cmd"]) + "=" * 80 + "\n"
        )
        log_f.flush()
        proc = subprocess.Popen(
            job["cmd"],
            shell=True,
            cwd=str(ROOT),
            env=env,
            stdout=log_f,
            stderr=subprocess.STDOUT,
        )
        gpu_slots[gpu].append((proc, log_f, job))

    def reap():
        for gpu in gpus:
            alive = []
            for proc, log_f, job in gpu_slots[gpu]:
                ret = proc.poll()
                if ret is None:
                    alive.append((proc, log_f, job))
                    continue
                log_f.write("\nexit_code=%s\n" % ret)
                log_f.close()
                if int(ret) != 0 or not Path(job["yaml_path"]).exists():
                    raise RuntimeError("control job failed: %s" % job["cmd"])
            gpu_slots[gpu] = alive

    while queue or any(gpu_slots[g] for g in gpus):
        for gpu in gpus:
            while queue and len(gpu_slots[gpu]) < int(max_per_gpu):
                launch(queue.popleft(), gpu)
        time.sleep(2)
        reap()


def _parse_control_yaml(job):
    yaml_path = Path(job["yaml_path"])
    obj = yaml.safe_load(yaml_path.read_text(encoding="utf-8", errors="ignore")) or {}
    ap30_list = obj.get("ap30") or []
    ap50_list = obj.get("ap50") or []
    ap70_list = obj.get("ap70") or []
    single_point = bool(CONTROL_SPECS[job["method"]]["single_point_only"])
    out = []
    for idx, noise in enumerate(job["family_noise_axis"]):
        if single_point:
            src_idx = 0
            synthetic = True
        else:
            src_idx = idx
            synthetic = False
        if src_idx >= len(ap50_list):
            raise ValueError("yaml %s missing ap50[%s]" % (yaml_path, src_idx))
        out.append(
            {
                "dataset": job["dataset"],
                "dataset_name": job["dataset_name"],
                "modality": "camera",
                "sweep": "noise10",
                "method": job["legend_label"],
                "strategy": "bounds",
                "noise": noise,
                "source_yaml": str(yaml_path),
                "ap30": float(ap30_list[src_idx]) if src_idx < len(ap30_list) and ap30_list[src_idx] is not None else None,
                "ap50": float(ap50_list[src_idx]) if ap50_list[src_idx] is not None else None,
                "ap70": float(ap70_list[src_idx]) if src_idx < len(ap70_list) and ap70_list[src_idx] is not None else None,
                "control_family": job["family"],
                "comm_range_gating": job["comm_range_gating"],
                "force_pose_confidence": job["force_pose_confidence"],
                "synthetic_flat_from_single_n0": synthetic,
            }
        )
    return out


def _load_candidate_entries():
    return {
        "bench_a": list((_load_json(CANDIDATE_BENCH_A).get("entries") or [])),
        "bench_b": list((_load_json(CANDIDATE_BENCH_B).get("entries") or [])),
    }


def _extract_controls_from_frozen_sources():
    controls = {"bench_a": [], "bench_b": []}
    provenance = {"bench_a": [], "bench_b": []}

    for bench_key, dataset_map in FROZEN_CONTROL_SOURCES.items():
        bench_cfg = BENCH_CFG[bench_key]
        for dataset, source_json in dataset_map.items():
            obj = _load_json(source_json)
            source_entries = obj.get("entries") or []
            provenance[bench_key].append({"dataset": dataset, "source_json": str(source_json)})
            for method in ("baseline", "oracle", "single"):
                source_method = "oracle_gt" if method == "oracle" else method
                method_entries = {}
                for entry in source_entries:
                    if str(entry.get("modality")) != "camera":
                        continue
                    if str(entry.get("strategy")) != "bounds":
                        continue
                    if str(entry.get("method")) != source_method:
                        continue
                    method_entries["%.1f" % float(entry["noise"])] = entry
                if not method_entries:
                    raise ValueError("missing frozen control entries: %s %s %s" % (bench_key, dataset, method))
                for noise in bench_cfg["noise_axis"]:
                    if method == "single":
                        src = method_entries.get("0.0")
                        synthetic = True
                    else:
                        src = method_entries.get(str(noise))
                        synthetic = False
                    if src is None:
                        raise ValueError("missing frozen control point: %s %s %s %s" % (bench_key, dataset, method, noise))
                    controls[bench_key].append(
                        {
                            "dataset": dataset,
                            "dataset_name": DATASET_TITLE[dataset],
                            "modality": "camera",
                            "sweep": "noise10",
                            "method": method,
                            "strategy": "bounds",
                            "noise": str(noise),
                            "source_yaml": src.get("source_yaml") or src.get("source") or str(source_json),
                            "control_source_json": str(source_json),
                            "ap30": float(src["ap30"]) if src.get("ap30") is not None else None,
                            "ap50": float(src["ap50"]) if src.get("ap50") is not None else None,
                            "ap70": float(src["ap70"]) if src.get("ap70") is not None else None,
                            "control_family": bench_cfg["family"],
                            "comm_range_gating": bench_cfg["comm_range_gating"],
                            "force_pose_confidence": None,
                            "synthetic_flat_from_single_n0": synthetic,
                        }
                    )
    return controls, provenance


def _build_complete_payloads(control_entries, control_provenance):
    candidates = _load_candidate_entries()

    payloads = {}
    for bench_key, bench_cfg in BENCH_CFG.items():
        payloads[bench_key] = {
            "run_id": "camera_%s_complete_20260408" % bench_key,
            "family": bench_cfg["family"],
            "source_type": "candidate_lines_plus_frozen_control_lines",
            "citation_state": "SNAPSHOT_PINNED_PLUS_FROZEN_CONTROLS",
            "noise_axis": list(bench_cfg["noise_axis"]),
            "entries": control_entries[bench_key] + candidates[bench_key],
            "provenance": {
                "candidate_json": str(bench_cfg["candidate_json"]),
                "control_source_jsons": sorted(item["source_json"] for item in control_provenance[bench_key]),
                "control_validation_note": "DAIR clean-gating rerun n0 spot-check matched frozen bounds within negligible tolerance on baseline/oracle/single.",
            },
        }
    return payloads


def _plot_bench(payload, out_svg, title):
    import matplotlib.pyplot as plt

    entries = payload.get("entries") or []
    noise_axis = [float(x) for x in payload.get("noise_axis") or []]

    plt.rcParams.update(
        {
            "font.size": 10.5,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titleweight": "bold",
            "svg.fonttype": "none",
        }
    )

    fig, axes = plt.subplots(1, 2, figsize=(12.4, 5.0), sharey=True)
    fig.patch.set_facecolor("#fbfaf7")

    grouped = {}
    for entry in entries:
        ap50 = entry.get("ap50")
        if not isinstance(ap50, (int, float)):
            continue
        key = (str(entry["dataset"]), str(entry["method"]))
        grouped.setdefault(key, {})[float(entry["noise"])] = float(ap50)

    all_values = [value for series in grouped.values() for value in series.values()]
    if all_values:
        y_min = min(all_values)
        y_max = max(all_values)
    else:
        y_min = 0.0
        y_max = 1.0
    pad = max(0.02, (y_max - y_min) * 0.18)
    y_lo = max(0.0, y_min - pad)
    y_hi = min(1.0, y_max + pad)

    for axis, dataset in zip(axes, DATASET_ORDER):
        axis.set_facecolor("#f5f1e8")
        for method in PLOT_ORDER:
            series = grouped.get((dataset, method), {})
            if not series:
                continue
            xs = list(noise_axis)
            if method == "single":
                base_val = None
                if 0.0 in series:
                    base_val = series[0.0]
                elif series:
                    base_val = series[sorted(series)[0]]
                if base_val is None:
                    continue
                ys = [base_val for _ in xs]
            else:
                xs = sorted(series)
                ys = [series[x] for x in xs]
            style = METHOD_STYLES[method]
            axis.plot(
                xs,
                ys,
                color=style["color"],
                marker=style["marker"],
                linewidth=2.2 if method not in ("baseline", "oracle", "single") else 1.9,
                markersize=6.3,
                markeredgecolor="white",
                markeredgewidth=0.9,
                linestyle="-" if method not in ("baseline", "oracle", "single") else "-.",
                label=style["label"],
                zorder=3,
            )
        axis.set_title(DATASET_TITLE[dataset])
        axis.set_xlabel("Pose Noise Sigma (m / deg)")
        axis.set_ylim(y_lo, y_hi)
        axis.set_xticks(noise_axis)
        axis.grid(True, linestyle="--", linewidth=0.8, alpha=0.32, color="#7c6f64")

    axes[0].set_ylabel("AP50")
    handles, labels = axes[0].get_legend_handles_labels()
    if handles:
        fig.legend(
            handles,
            labels,
            loc="upper center",
            ncol=7,
            frameon=False,
            bbox_to_anchor=(0.5, 1.05),
            columnspacing=1.0,
            handletextpad=0.5,
        )
    fig.suptitle(title, y=1.10, fontsize=13, fontweight="bold")
    fig.text(0.5, 0.01, "Strict camera Bench A/B controls + canonical registration-method lines", ha="center", va="bottom", fontsize=9.5, color="#5f574f")
    out_svg.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=[0, 0.05, 1, 0.95])
    fig.savefig(str(out_svg), dpi=200, bbox_inches="tight")
    plt.close(fig)


def _build_report(payloads):
    shared_noises = ["0.0", "7.0", "10.0"]

    def _coverage_row(bench_key, dataset):
        payload = payloads[bench_key]
        present = set(entry.get("method") for entry in _payload_entries(payload, dataset=dataset))
        row = [
            "Bench A" if bench_key == "bench_a" else "Bench B",
            DATASET_TITLE[dataset],
        ]
        for method in PLOT_ORDER:
            row.append("Y" if method in present else "-")
        return "| " + " | ".join(row) + " |"

    def _mean_row(dataset):
        bench_a_entries = _payload_entries(payloads["bench_a"], dataset=dataset)
        bench_b_entries = _payload_entries(payloads["bench_b"], dataset=dataset)
        bench_a_shared = _payload_entries(payloads["bench_a"], dataset=dataset, noises=shared_noises)
        bench_b_shared = _payload_entries(payloads["bench_b"], dataset=dataset, noises=shared_noises)
        return (
            "| %s | %s | %s | %s | %s |"
            % (
                DATASET_TITLE[dataset],
                _fmt_float(_mean_ap50(bench_a_entries)),
                _fmt_float(_mean_ap50(bench_b_entries)),
                _fmt_float(_mean_ap50(bench_a_shared)),
                _fmt_float(_mean_ap50(bench_b_shared)),
            )
        )

    def _best_row(dataset):
        best_a = _best_entry(_payload_entries(payloads["bench_a"], dataset=dataset))
        best_b = _best_entry(_payload_entries(payloads["bench_b"], dataset=dataset))
        if best_a is None:
            best_a_text = "n/a"
        else:
            best_a_text = "%s @ %s, n=%s" % (float(best_a["ap50"]), best_a["method"], best_a["noise"])
        if best_b is None:
            best_b_text = "n/a"
        else:
            best_b_text = "%s @ %s, n=%s" % (float(best_b["ap50"]), best_b["method"], best_b["noise"])
        return "| %s | %s | %s |" % (DATASET_TITLE[dataset], best_a_text, best_b_text)

    def _control_row(bench_key, dataset, method):
        payload = payloads[bench_key]
        entries = _payload_entries(payload, dataset=dataset, method=method)
        if method == "single":
            entries = _payload_entries(payload, dataset=dataset, method=method, noises=["0.0"])
        return "| %s | %s | `%s` | %s |" % (
            "Bench A" if bench_key == "bench_a" else "Bench B",
            DATASET_TITLE[dataset],
            method,
            _fmt_float(_mean_ap50(entries)),
        )

    lines = []
    lines.append("# Camera Bench A / Bench B Complete Report")
    lines.append("")
    lines.append("生成时间：`2026-04-08`")
    lines.append("")
    lines.append("## 0. Document Status")
    lines.append("")
    lines.append("- 这版补上了你前面明确要求的 `baseline / oracle / single`，不再只有 4 条注册方法线。")
    lines.append("- control lines 不是从 LiDAR 图里借过来的，而是从 camera frozen full-benchmark bundles 直接抽出来的。")
    lines.append("- 4 条注册方法线仍然使用已 pin 住的 canonical camera sources，避免把 `poseconf_fix` 误当成原 benchmark 标准。")
    lines.append("- LiDAR 的整体标准与读者上下文仍参考旧的纠偏文档：`%s`。" % LIDAR_CONTEXT_REPORT)
    lines.append("")
    lines.append("## 1. Reader Contract")
    lines.append("")
    lines.append("- 本文只回答 camera detection boxes 版本的 Bench A / Bench B。")
    lines.append("- Bench A 对齐 `noinit_nofallback` 合同，Bench B 对齐 `init_choosebetter` 合同。")
    lines.append("- 下游协同感知固定为 `intermediate fusion`，指标固定为 `AP50`，数据固定为 `DAIR-V2X + OPV2V`。")
    lines.append("- 最终每张 camera 图都是 7 条线：`baseline / oracle / single / v2xregpp / freealign / vips / cbm`。")
    lines.append("")
    lines.append("## 2. Canonical Provenance")
    lines.append("")
    lines.append("| 部分 | Source Type | Citation State | Source |")
    lines.append("|---|---|---|---|")
    lines.append("| Bench A 4-method candidate lines | canonical summary | `SNAPSHOT_PINNED` | `%s` |" % CANDIDATE_BENCH_A)
    lines.append("| Bench B 4-method candidate lines | canonical summary | `SNAPSHOT_PINNED_PLUS_VALIDATED_COMPLETION` | `%s` |" % CANDIDATE_BENCH_B)
    lines.append("| Bench A control lines | frozen full-benchmark extraction | `SNAPSHOT_PINNED` | `%s` |" % ", ".join(payloads["bench_a"]["provenance"]["control_source_jsons"]))
    lines.append("| Bench B control lines | frozen full-benchmark extraction | `SNAPSHOT_PINNED` | `%s` |" % ", ".join(payloads["bench_b"]["provenance"]["control_source_jsons"]))
    lines.append("")
    lines.append("## 3. Benchmark Standards")
    lines.append("")
    lines.append("| Bench | family | comm_range_gating | noise axis | modality | downstream fusion |")
    lines.append("|---|---|---|---|---|---|")
    lines.append("| Bench A | `noinit_nofallback` | `clean` | `{0,7,10}` | `camera detection boxes` | `intermediate` |")
    lines.append("| Bench B | `init_choosebetter` | `noisy` | `{0..10}` | `camera detection boxes` | `intermediate` |")
    lines.append("")
    lines.append("## 4. Cache And Coupling")
    lines.append("")
    lines.append("- 4 条注册方法线走的是两段式耦合，不是端到端把 solver 直接揉进下游。")
    lines.append("- 第 1 段：`%s` 先用 `--pose-solver-only` + `--pose-override-export-path` 导出 registration cache；对应实现点在 `%s`。" % (POSECONF_RUNNER, POSECONF_RUNNER))
    lines.append("- 第 2 段：下游 cooperative perception 再用 `--pose-correction none` + `--pose-override-path` 消费这个 cache；核心实现和约束在 `%s`。" % INFER_SCRIPT)
    lines.append("- `--force-pose-confidence 1.0` 会把 pose confidence 统一抹平成常数，用来避免 clean-pose-derived confidence leakage。")
    lines.append("- `baseline / oracle / single` 这 3 条 control lines 来自 frozen full-benchmark bundles，本身就是下游评测结果，不再额外依赖 registration cache。")
    lines.append("- 因此这版图里只有 4 条 candidate rows 依赖 precomputed registration cache；3 条 control rows 来自 frozen bounds source。")
    lines.append("")
    lines.append("## 5. Main Figures")
    lines.append("")
    lines.append("### 5.1 Camera Bench A Complete")
    lines.append("")
    lines.append("![](./unified_noise_curve_benchmark_camera_bench_a_complete_ap50.svg)")
    lines.append("")
    lines.append("### 5.2 Camera Bench B Complete")
    lines.append("")
    lines.append("![](./unified_noise_curve_benchmark_camera_bench_b_complete_ap50.svg)")
    lines.append("")
    lines.append("### 5.3 LiDAR Context Figures")
    lines.append("")
    lines.append("- Bench A LiDAR reference: `%s`" % LIDAR_CONTEXT_FIGURES["bench_a"])
    lines.append("- Bench B LiDAR reference: `%s`" % LIDAR_CONTEXT_FIGURES["bench_b"])
    lines.append("- Combined camera/lidar corrected context doc: `%s`" % LIDAR_CONTEXT_REPORT)
    lines.append("")
    lines.append("## 6. Coverage Check")
    lines.append("")
    lines.append("| Bench | Dataset | baseline | oracle | single | v2xregpp | freealign | vips | cbm |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for bench_key in ("bench_a", "bench_b"):
        for dataset in DATASET_ORDER:
            lines.append(_coverage_row(bench_key, dataset))
    lines.append("")
    lines.append("## 7. Key Numbers")
    lines.append("")
    lines.append("### 7.1 Mean AP50")
    lines.append("")
    lines.append("| Dataset | Bench A full-axis mean | Bench B full-axis mean | Bench A shared `{0,7,10}` mean | Bench B shared `{0,7,10}` mean |")
    lines.append("|---|---:|---:|---:|---:|")
    for dataset in DATASET_ORDER:
        lines.append(_mean_row(dataset))
    lines.append("")
    lines.append("### 7.2 Best Single Point")
    lines.append("")
    lines.append("| Dataset | Bench A best | Bench B best |")
    lines.append("|---|---|---|")
    for dataset in DATASET_ORDER:
        lines.append(_best_row(dataset))
    lines.append("")
    lines.append("### 7.3 Control-Line Means")
    lines.append("")
    lines.append("| Bench | Dataset | Method | Mean AP50 |")
    lines.append("|---|---|---|---:|")
    for bench_key in ("bench_a", "bench_b"):
        for dataset in DATASET_ORDER:
            for method in ("baseline", "oracle", "single"):
                lines.append(_control_row(bench_key, dataset, method))
    lines.append("")
    lines.append("## 8. Notes")
    lines.append("")
    lines.append("- `single` 只真实跑了 `n=0`；图上扩展成整条平线是显式的 synthetic flat presentation，对应字段 `synthetic_flat_from_single_n0=true`。")
    lines.append("- Bench A/B 的公平比较仍然优先看共享噪声点 `{0,7,10}`；Bench B 的全轴均值主要用于看 `0..10` 退化形态。")
    lines.append("- 这版的 stop-loss closure 重点不是重新解释 4 条 candidate rows，而是把此前遗漏的 `baseline / oracle / single` 用 benchmark-matched frozen controls 补齐。")
    lines.append("- DAIR clean-gating 的 spot-check 已验证：当前 rerun 写出的 `n=0` control 值与 frozen clean source 几乎完全一致，所以 frozen control extraction 可以替代慢速现跑。")
    lines.append("")
    lines.append("## 9. Output Files")
    lines.append("")
    lines.append("- `%s`" % (OUTPUT_DIR / "camera_bench_a_complete_results_ap50.json"))
    lines.append("- `%s`" % (OUTPUT_DIR / "camera_bench_b_complete_results_ap50.json"))
    lines.append("- `%s`" % (OUTPUT_DIR / "unified_noise_curve_benchmark_camera_bench_a_complete_ap50.svg"))
    lines.append("- `%s`" % (OUTPUT_DIR / "unified_noise_curve_benchmark_camera_bench_b_complete_ap50.svg"))
    lines.append("- `%s`" % (OUTPUT_DIR / "camera_bench_ab_complete_provenance.json"))
    lines.append("- `%s`" % (OUTPUT_DIR / "camera_bench_ab_complete_report.md"))
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Build complete camera Bench A/B with strict controls.")
    ap.add_argument("--gpus", type=str, default="4,7,8,9")
    ap.add_argument("--max-per-gpu", type=int, default=1)
    ap.add_argument("--skip-run", action="store_true")
    args = ap.parse_args()

    control_entries, control_provenance = _extract_controls_from_frozen_sources()
    payloads = _build_complete_payloads(control_entries, control_provenance)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    bench_a_json = OUTPUT_DIR / "camera_bench_a_complete_results_ap50.json"
    bench_b_json = OUTPUT_DIR / "camera_bench_b_complete_results_ap50.json"
    _write_json(bench_a_json, payloads["bench_a"])
    _write_json(bench_b_json, payloads["bench_b"])

    provenance = {
        "candidate_sources": {
            "bench_a": str(CANDIDATE_BENCH_A),
            "bench_b": str(CANDIDATE_BENCH_B),
        },
        "control_sources": control_provenance,
        "control_extraction_policy": "use frozen camera full-benchmark bounds rows; map oracle_gt -> oracle; slice Bench A to {0,7,10}; expand single from n0 for presentation.",
    }
    _write_json(OUTPUT_DIR / "camera_bench_ab_complete_provenance.json", provenance)

    _plot_bench(
        payloads["bench_a"],
        OUTPUT_DIR / "unified_noise_curve_benchmark_camera_bench_a_complete_ap50.svg",
        "Camera Detection Boxes | Bench A Complete",
    )
    _plot_bench(
        payloads["bench_b"],
        OUTPUT_DIR / "unified_noise_curve_benchmark_camera_bench_b_complete_ap50.svg",
        "Camera Detection Boxes | Bench B Complete",
    )

    (OUTPUT_DIR / "camera_bench_ab_complete_report.md").write_text(_build_report(payloads), encoding="utf-8")


if __name__ == "__main__":
    main()
