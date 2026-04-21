#!/usr/bin/env python3

import argparse
import json
import os
import shlex
import subprocess
import time
from collections import deque
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import yaml


ROOT = Path(__file__).resolve().parents[1]
PY39 = ROOT / ".micromamba" / "envs" / "py39" / "bin" / "python"
INFER = ROOT / "HEAL" / "opencood" / "tools" / "inference_w_noise.py"
OUTPUTS = ROOT / "outputs"

DATASETS = {
    "dair": {
        "dataset_name": "DAIR-V2X",
        "model_dir": ROOT / "HEAL" / "opencood" / "logs" / "HeterBaseline_DAIR_camera_v2xvit_2023_09_09_11_27_38",
        "stage1": ROOT / "data" / "DAIR-V2X" / "detected" / "camera_v2xvit_stage1" / "stage1_boxes.json",
        "comm_range": 100,
    },
    "opv2v": {
        "dataset_name": "OPV2V",
        "model_dir": ROOT / "HEAL" / "opencood" / "logs" / "opv2v_camera_v2xvit_full_prope",
        "stage1": ROOT / "data" / "OPV2V" / "detected" / "opv2v_camera_v2xvit_stage1_percav" / "test" / "stage1_boxes.json",
        "comm_range": 70,
    },
}

METHODS = {
    "cbm": "cbm_initfree",
    "freealign": "freealign_paper",
    "v2xregpp": "v2xregpp_initfree",
    "vips": "vips_initfree",
}

FAMILY_CFG = {
    "noinit_nofallback": {
        "noises": [0, 7, 10],
        "pose_selection_policy": "solver_only",
        "pose_source": "noisy_input",
        "pose_no_fallback": True,
        "comm_range_gating": "clean",
        "strategy": "noinit_nofallback",
        "force_pose_confidence": 1.0,
    },
    "init_choosebetter": {
        "noises": list(range(11)),
        "pose_selection_policy": "choose_better_pose_error",
        "pose_source": "noisy_input",
        "pose_no_fallback": False,
        "comm_range_gating": "noisy",
        "strategy": "init",
        "force_pose_confidence": 1.0,
    },
}

RUNS = {
    "noinit_reg": OUTPUTS / "stage1_registration_cache_noinit_nofallback_camera_poseconf_fix_dair_opv2v_20260403",
    "noinit_down": OUTPUTS / "stage1_cached_downstream_noinit_nofallback_camera_poseconf_fix_dair_opv2v_20260403",
    "init_reg_dair": OUTPUTS / "stage1_registration_cache_init_choosebetter_camera_init_choosebetter_full_20260403_p1",
    "init_reg_opv2v": OUTPUTS / "stage1_registration_cache_init_choosebetter_camera_init_choosebetter_opv2v_full_20260403_p2",
    "init_down": OUTPUTS / "stage1_cached_downstream_init_choosebetter_camera_poseconf_fix_dair_opv2v_20260403",
    "plot_dir": OUTPUTS / "camera_poseconf_fix_benchmark_20260403",
}


def _shell_join(args: Iterable[object]) -> str:
    return " ".join(shlex.quote(str(x)) for x in args)


def _noise_label(noise: int) -> str:
    return f"n{int(noise)}"


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: object) -> None:
    _ensure_parent(path)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def _require_complete_results(results_path: Path, *, expected_jobs: int, label: str) -> None:
    obj = _load_json(results_path, {"jobs": []})
    jobs = obj.get("jobs") or []
    ok = [j for j in jobs if j.get("status") == "ok"]
    if len(ok) != int(expected_jobs):
        raise SystemExit(
            "[INCOMPLETE] {} expected {} successful jobs but found {}. See {}".format(
                label, int(expected_jobs), len(ok), results_path
            )
        )


def _job_key(job: dict) -> Tuple[str, str, str]:
    return (str(job.get("dataset")), str(job.get("method")), str(job.get("noise")))


def _launch_env_for_gpu(gpu: int, *, parent_visible: str) -> dict:
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


def _mean(values: Iterable[Optional[float]]) -> Optional[float]:
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None
    return float(sum(vals) / len(vals))


def _parse_yaml_metrics(yaml_path: Path) -> dict:
    if not yaml_path.exists():
        return {}
    obj = yaml.safe_load(yaml_path.read_text(encoding="utf-8", errors="ignore")) or {}
    ap30 = obj.get("ap30") or []
    ap50 = obj.get("ap50") or []
    ap70 = obj.get("ap70") or []

    timing_stats = obj.get("timing_stats") or []
    infer_fps = []
    infer_sec = []
    pose_fps = []
    pose_sec = []
    pose_provider_total_sec = []
    pose_provider_applied = []
    pose_match_sec = []
    for ts in timing_stats:
        if not isinstance(ts, dict):
            continue
        if ts.get("infer_fps") is not None:
            infer_fps.append(float(ts["infer_fps"]))
        if ts.get("infer_sec") is not None:
            infer_sec.append(float(ts["infer_sec"]))
        if ts.get("pose_solver_fps") is not None:
            pose_fps.append(float(ts["pose_solver_fps"]))
        if ts.get("pose_solver_sec") is not None:
            pose_sec.append(float(ts["pose_solver_sec"]))
        pt = ts.get("pose_timing")
        if isinstance(pt, dict):
            if pt.get("pose_provider_total_sec") is not None:
                pose_provider_total_sec.append(float(pt["pose_provider_total_sec"]))
            if pt.get("pose_provider_applied_count") is not None:
                pose_provider_applied.append(float(pt["pose_provider_applied_count"]))
            if pt.get("match_sec") is not None:
                pose_match_sec.append(float(pt["match_sec"]))

    rel = obj.get("rel_error_stats") or []
    rel_t = []
    rel_y = []
    succ = {1: [], 2: [], 3: [], 5: [], 10: []}
    samples = []
    for rs in rel:
        if not isinstance(rs, dict):
            continue
        t = (rs.get("rel_trans_m") or {}).get("mean")
        y = (rs.get("rel_yaw_deg") or {}).get("mean")
        if t is not None:
            rel_t.append(float(t))
        if y is not None:
            rel_y.append(float(y))
        succ_map = rs.get("rel_success_at_m") or {}
        for k in succ:
            if str(k) in succ_map and succ_map[str(k)] is not None:
                succ[k].append(float(succ_map[str(k)]))
        if rs.get("samples") is not None:
            samples.append(float(rs["samples"]))

    return {
        "ap30": _mean(ap30),
        "ap50": _mean(ap50),
        "ap70": _mean(ap70),
        "infer_fps": _mean(infer_fps),
        "infer_sec": _mean(infer_sec),
        "pose_fps": _mean(pose_fps),
        "pose_sec": _mean(pose_sec),
        "mean_rel_trans_m": _mean(rel_t),
        "mean_rel_yaw_deg": _mean(rel_y),
        "success_at_1m": _mean(succ[1]),
        "success_at_2m": _mean(succ[2]),
        "success_at_3m": _mean(succ[3]),
        "success_at_5m": _mean(succ[5]),
        "success_at_10m": _mean(succ[10]),
        "samples": _mean(samples),
        "mean_pose_provider_total_sec": _mean(pose_provider_total_sec),
        "mean_pose_provider_applied_count": _mean(pose_provider_applied),
        "mean_pose_match_sec": _mean(pose_match_sec),
    }


def _build_registration_manifest(
    *,
    family: str,
    run_root: Path,
    datasets: Iterable[str],
) -> dict:
    cfg = FAMILY_CFG[family]
    jobs = []
    for dataset in datasets:
        ds = DATASETS[dataset]
        for method, pose_correction in METHODS.items():
            for noise in cfg["noises"]:
                noise_str = f"{float(noise):.1f}"
                note = (
                    f"_{family}_camera_poseconf_fix_dair_opv2v_20260403_camera_"
                    f"{dataset}_{method}_{_noise_label(noise)}"
                )
                export_path = run_root / "overrides" / "camera" / dataset / method / f"{method}_{_noise_label(noise)}.json"
                solver_yaml = ds["model_dir"] / f"POSE_SOLVER_ONLY_{pose_correction}{note}.yaml"
                log_path = run_root / "logs" / "camera" / dataset / f"{dataset}_{method}_{_noise_label(noise)}.log"
                args = [
                    PY39,
                    INFER,
                    "--model_dir",
                    ds["model_dir"],
                    "--fusion_method",
                    "intermediate",
                    "--pose-correction",
                    pose_correction,
                    "--solver-backend",
                    "offline_map",
                    "--pose-solver-only",
                    "--pose-selection-policy",
                    cfg["pose_selection_policy"],
                    "--pose-source",
                    cfg["pose_source"],
                    "--comm-range-override",
                    ds["comm_range"],
                    "--noise-target",
                    "non-ego",
                    "--sweep-mode",
                    "paired",
                    "--pos-std-list",
                    noise_str,
                    "--rot-std-list",
                    noise_str,
                    "--num-workers",
                    "0",
                    "--save_vis_interval",
                    "100000000",
                    "--pose-device",
                    "cuda",
                    "--stage1-result",
                    ds["stage1"],
                    "--pose-override-export-path",
                    export_path,
                    "--note",
                    note,
                ]
                if cfg["pose_no_fallback"]:
                    args.append("--pose-no-fallback")
                jobs.append(
                    {
                        "family": family,
                        "modality": "camera",
                        "dataset": dataset,
                        "dataset_name": ds["dataset_name"],
                        "method": method,
                        "pose_correction": pose_correction,
                        "noise": noise_str,
                        "export_path": str(export_path),
                        "solver_yaml_path": str(solver_yaml),
                        "log_path": str(log_path),
                        "note": note,
                        "cmd": _shell_join(args),
                    }
                )
    return {
        "family": family,
        "modality": "camera",
        "run_tag": run_root.name.replace("stage1_registration_cache_", ""),
        "run_root": str(run_root),
        "manifest_generated_at_epoch": time.time(),
        "jobs": jobs,
    }


def _cache_root_for_init(dataset: str) -> Path:
    if dataset == "dair":
        return RUNS["init_reg_dair"]
    if dataset == "opv2v":
        return RUNS["init_reg_opv2v"]
    raise KeyError(dataset)


def _build_downstream_manifest(
    *,
    family: str,
    run_root: Path,
    cache_roots: Dict[str, Path],
) -> dict:
    cfg = FAMILY_CFG[family]
    jobs = []
    for dataset, cache_root in cache_roots.items():
        ds = DATASETS[dataset]
        for method in METHODS:
            for noise in cfg["noises"]:
                noise_str = f"{float(noise):.1f}"
                note = (
                    f"_cacheddown_{family}_camera_poseconf_fix_dair_opv2v_20260403_camera_"
                    f"{dataset}_{method}_{_noise_label(noise)}"
                )
                override_path = cache_root / "overrides" / "camera" / dataset / method / f"{method}_{_noise_label(noise)}.json"
                yaml_path = ds["model_dir"] / f"AP030507_none{note}.yaml"
                log_path = run_root / "logs" / "camera" / dataset / f"{dataset}_{method}_{_noise_label(noise)}.log"
                args = [
                    PY39,
                    INFER,
                    "--model_dir",
                    ds["model_dir"],
                    "--fusion_method",
                    "intermediate",
                    "--pose-correction",
                    "none",
                    "--pose-override-path",
                    override_path,
                    "--comm-range-override",
                    ds["comm_range"],
                    "--comm-range-gating",
                    cfg["comm_range_gating"],
                    "--noise-target",
                    "non-ego",
                    "--sweep-mode",
                    "paired",
                    "--pos-std-list",
                    noise_str,
                    "--rot-std-list",
                    noise_str,
                    "--num-workers",
                    "0",
                    "--save_vis_interval",
                    "100000000",
                    "--note",
                    note,
                    "--force-pose-confidence",
                    f"{float(cfg['force_pose_confidence']):.1f}",
                ]
                jobs.append(
                    {
                        "family": family,
                        "modality": "camera",
                        "dataset": dataset,
                        "dataset_name": ds["dataset_name"],
                        "method": method,
                        "noise": noise_str,
                        "strategy": cfg["strategy"],
                        "override_path": str(override_path),
                        "yaml_path": str(yaml_path),
                        "log_path": str(log_path),
                        "force_pose_confidence": float(cfg["force_pose_confidence"]),
                        "cmd": _shell_join(args),
                    }
                )
    return {
        "family": family,
        "modality": "camera",
        "run_tag": run_root.name.replace("stage1_cached_downstream_", ""),
        "cache_roots": {k: str(v) for k, v in cache_roots.items()},
        "manifest_generated_at_epoch": time.time(),
        "force_pose_confidence": float(cfg["force_pose_confidence"]),
        "jobs": jobs,
    }


def _registration_expected_ok(job: dict) -> bool:
    return Path(job["export_path"]).exists()


def _downstream_expected_ok(job: dict) -> bool:
    return Path(job["yaml_path"]).exists()


def _build_registration_result(job: dict, exit_code: int, *, synthesized: bool = False) -> dict:
    export_exists = Path(job["export_path"]).exists()
    solver_yaml_exists = Path(job["solver_yaml_path"]).exists()
    return {
        "family": job["family"],
        "dataset": job["dataset"],
        "dataset_name": job["dataset_name"],
        "method": job["method"],
        "pose_correction": job["pose_correction"],
        "noise": job["noise"],
        "export_path": job["export_path"],
        "solver_yaml_path": job["solver_yaml_path"],
        "log_path": job["log_path"],
        "cmd": job["cmd"],
        "exit_code": int(exit_code),
        "export_exists": bool(export_exists),
        "solver_yaml_exists": bool(solver_yaml_exists),
        "status": "ok" if int(exit_code) == 0 and export_exists else "fail",
        "synthesized_from_existing": bool(synthesized),
    }


def _build_downstream_result(job: dict, exit_code: int, *, synthesized: bool = False) -> dict:
    yaml_path = Path(job["yaml_path"])
    yaml_exists = yaml_path.exists()
    log_exists = Path(job["log_path"]).exists()
    metrics = _parse_yaml_metrics(yaml_path) if yaml_exists else {}
    rec = {
        "family": job["family"],
        "dataset": job["dataset"],
        "dataset_name": job["dataset_name"],
        "method": job["method"],
        "noise": job["noise"],
        "strategy": job["strategy"],
        "override_path": job["override_path"],
        "yaml_path": job["yaml_path"],
        "log_path": job["log_path"],
        "cmd": job["cmd"],
        "yaml_exists": bool(yaml_exists),
        "log_exists": bool(log_exists),
        "exit_code": int(exit_code),
        "force_pose_confidence": float(job["force_pose_confidence"]),
        "status": "ok" if int(exit_code) == 0 and yaml_exists else "fail",
        "synthesized_from_existing": bool(synthesized),
    }
    rec.update(metrics)
    return rec


def _collect_existing_results(results_path: Path) -> Dict[Tuple[str, str, str], dict]:
    obj = _load_json(results_path, {"jobs": []})
    jobs = obj.get("jobs") or []
    out: Dict[Tuple[str, str, str], dict] = {}
    for rec in jobs:
        out[_job_key(rec)] = rec
    return out


def _write_results(results_path: Path, manifest: dict, result_map: Dict[Tuple[str, str, str], dict]) -> None:
    ordered = []
    for job in manifest["jobs"]:
        rec = result_map.get(_job_key(job))
        if rec is not None:
            ordered.append(rec)
    payload = {"jobs": ordered}
    _write_json(results_path, payload)


def _run_manifest(
    *,
    manifest_path: Path,
    results_path: Path,
    is_downstream: bool,
    gpus: List[int],
    max_per_gpu: int,
    dry_run: bool,
) -> None:
    manifest = _load_json(manifest_path, None)
    if manifest is None:
        raise SystemExit(f"Missing manifest: {manifest_path}")
    existing = _collect_existing_results(results_path)
    result_map = dict(existing)

    jobs = manifest.get("jobs") or []
    pending = []
    for job in jobs:
        key = _job_key(job)
        if is_downstream:
            expected_ok = _downstream_expected_ok(job)
            builder = _build_downstream_result
        else:
            expected_ok = _registration_expected_ok(job)
            builder = _build_registration_result
        rec = existing.get(key)
        if rec and rec.get("status") == "ok" and expected_ok:
            continue
        if expected_ok:
            result_map[key] = builder(job, 0, synthesized=True)
            continue
        pending.append(job)

    _write_results(results_path, manifest, result_map)
    if dry_run or not pending:
        return

    parent_visible = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    gpu_slots: Dict[int, List[Tuple[subprocess.Popen, object, dict]]] = {gpu: [] for gpu in gpus}
    queue: deque[dict] = deque(pending)

    def launch(job: dict, gpu: int) -> None:
        env = _launch_env_for_gpu(gpu, parent_visible=parent_visible)
        log_path = Path(job["log_path"])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_f = open(log_path, "a", encoding="utf-8")
        log_f.write(
            "\n"
            + "=" * 80
            + "\n"
            + f"[LAUNCH] time={time.strftime('%Y-%m-%d %H:%M:%S')} gpu={gpu} cmd={job['cmd']}\n"
            + "=" * 80
            + "\n"
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

    def reap() -> None:
        for gpu in gpus:
            alive = []
            for proc, log_f, job in gpu_slots[gpu]:
                ret = proc.poll()
                if ret is None:
                    alive.append((proc, log_f, job))
                    continue
                log_f.write(f"\nexit_code={ret}\n")
                log_f.close()
                if is_downstream:
                    rec = _build_downstream_result(job, ret)
                else:
                    rec = _build_registration_result(job, ret)
                result_map[_job_key(job)] = rec
                _write_results(results_path, manifest, result_map)
            gpu_slots[gpu] = alive

    while queue or any(gpu_slots[g] for g in gpus):
        for gpu in gpus:
            while queue and len(gpu_slots[gpu]) < max_per_gpu:
                launch(queue.popleft(), gpu)
        time.sleep(2)
        reap()


def _summarize_downstream(run_root: Path, manifest_path: Path, results_path: Path, out_json: Path) -> None:
    manifest = _load_json(manifest_path, None)
    if manifest is None:
        raise SystemExit(f"Missing manifest: {manifest_path}")
    results = _load_json(results_path, {"jobs": []})
    entries = []
    for rec in results.get("jobs") or []:
        if rec.get("status") != "ok":
            continue
        if not rec.get("yaml_exists"):
            continue
        entries.append(
            {
                "dataset": rec["dataset"],
                "dataset_name": rec["dataset_name"],
                "modality": "camera",
                "sweep": "noise10",
                "method": rec["method"],
                "strategy": rec["strategy"],
                "noise": rec["noise"],
                "source_yaml": rec["yaml_path"],
                "override_path": rec["override_path"],
                "ap30": rec.get("ap30"),
                "ap50": rec.get("ap50"),
                "ap70": rec.get("ap70"),
                "infer_fps": rec.get("infer_fps"),
                "infer_sec": rec.get("infer_sec"),
                "pose_fps": rec.get("pose_fps"),
                "pose_sec": rec.get("pose_sec"),
                "mean_rel_trans_m": rec.get("mean_rel_trans_m"),
                "mean_rel_yaw_deg": rec.get("mean_rel_yaw_deg"),
                "success_at_1m": rec.get("success_at_1m"),
                "success_at_2m": rec.get("success_at_2m"),
                "success_at_3m": rec.get("success_at_3m"),
                "success_at_5m": rec.get("success_at_5m"),
                "success_at_10m": rec.get("success_at_10m"),
                "samples": rec.get("samples"),
                "force_pose_confidence": rec.get("force_pose_confidence"),
                "mean_pose_provider_total_sec": rec.get("mean_pose_provider_total_sec"),
                "mean_pose_provider_applied_count": rec.get("mean_pose_provider_applied_count"),
                "mean_pose_match_sec": rec.get("mean_pose_match_sec"),
            }
        )
    payload = {
        "run_id": run_root.name.replace("stage1_cached_downstream_", ""),
        "family": manifest["family"],
        "cache_roots": manifest.get("cache_roots") or {"shared": str(manifest.get("cache_root", ""))},
        "entries": entries,
    }
    _write_json(out_json, payload)


def _plot_benchmark(results_json: Path, out_svg: Path, *, title: str, subtitle: str) -> None:
    import matplotlib.pyplot as plt

    obj = _load_json(results_json, None)
    if obj is None:
        raise SystemExit(f"Missing results summary: {results_json}")
    entries = obj.get("entries") or []
    datasets = ["dair", "opv2v"]
    dataset_title = {"dair": "DAIR-V2X", "opv2v": "OPV2V"}
    methods = ["v2xregpp", "freealign", "vips", "cbm"]
    colors = {
        "v2xregpp": "#2166ac",
        "freealign": "#ef8a0c",
        "vips": "#1a9850",
        "cbm": "#b2182b",
    }
    markers = {
        "v2xregpp": "o",
        "freealign": "s",
        "vips": "D",
        "cbm": "^",
    }
    plt.rcParams.update(
        {
            "font.size": 10.5,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titleweight": "bold",
            "svg.fonttype": "none",
        }
    )
    fig, axes = plt.subplots(1, 2, figsize=(11.4, 4.8), sharey=True)
    fig.patch.set_facecolor("#fbfaf7")
    grouped: Dict[Tuple[str, str], Dict[float, float]] = {}
    for e in entries:
        v = e.get("ap50")
        if not isinstance(v, (int, float)):
            continue
        grouped.setdefault((str(e["dataset"]), str(e["method"])), {})[float(e["noise"])] = float(v)

    y_min = None
    y_max = None
    for ds in datasets:
        for method in methods:
            vals = list(grouped.get((ds, method), {}).values())
            if not vals:
                continue
            lo = min(vals)
            hi = max(vals)
            y_min = lo if y_min is None else min(y_min, lo)
            y_max = hi if y_max is None else max(y_max, hi)

    if y_min is None or y_max is None:
        y_min, y_max = 0.0, 1.0
    pad = max(0.02, (y_max - y_min) * 0.18)
    y_lo = max(0.0, y_min - pad)
    y_hi = min(1.0, y_max + pad)

    for ax, ds in zip(axes, datasets):
        ax.set_facecolor("#f5f1e8")
        for method in methods:
            series = grouped.get((ds, method), {})
            if not series:
                continue
            xs = sorted(series)
            ys = [series[x] for x in xs]
            ax.plot(
                xs,
                ys,
                color=colors[method],
                marker=markers[method],
                linewidth=2.2,
                markersize=6.5,
                markeredgecolor="white",
                markeredgewidth=0.9,
                label=method,
                zorder=3,
            )
        ax.set_title(dataset_title[ds])
        ax.set_xlabel("Pose Noise Sigma (m / deg)")
        ax.set_ylim(y_lo, y_hi)
        ax.grid(True, linestyle="--", linewidth=0.8, alpha=0.32, color="#7c6f64")
    axes[0].set_ylabel("AP50")

    handles, labels = axes[0].get_legend_handles_labels()
    if handles:
        fig.legend(
            handles,
            labels,
            loc="upper center",
            ncol=4,
            frameon=False,
            bbox_to_anchor=(0.5, 1.04),
            columnspacing=1.2,
            handletextpad=0.6,
        )
    fig.suptitle(title, y=1.10, fontsize=13, fontweight="bold")
    fig.text(0.5, 0.01, subtitle, ha="center", va="bottom", fontsize=9.5, color="#5f574f")
    out_svg.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=[0, 0.05, 1, 0.95])
    fig.savefig(out_svg, dpi=200, bbox_inches="tight")
    plt.close(fig)


def _check_path_exists(path: Path, *, label: str) -> None:
    if not path.exists():
        raise SystemExit(f"Missing {label}: {path}")


def _write_manifest(path: Path, manifest: dict) -> None:
    _write_json(path, manifest)


def main() -> None:
    ap = argparse.ArgumentParser(description="Run camera poseconf-fix cached benchmarks for noinit/init camera stage1 boxes.")
    ap.add_argument("--gpus", type=str, default="1,5,9", help="GPU slots/indices to use, comma-separated.")
    ap.add_argument("--max-per-gpu", type=int, default=2)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-init-registration", action="store_true")
    ap.add_argument("--skip-noinit-registration", action="store_true")
    ap.add_argument("--skip-init-downstream", action="store_true")
    ap.add_argument("--skip-noinit-downstream", action="store_true")
    ap.add_argument("--skip-plot", action="store_true")
    args = ap.parse_args()

    gpus = [int(x.strip()) for x in str(args.gpus).split(",") if x.strip()]
    if not gpus:
        raise SystemExit("No GPUs selected.")
    if int(args.max_per_gpu) <= 0:
        raise SystemExit("--max-per-gpu must be > 0")

    for dataset, ds in DATASETS.items():
        _check_path_exists(ds["model_dir"], label=f"{dataset} model_dir")
        _check_path_exists(ds["stage1"], label=f"{dataset} camera stage1")

    RUNS["plot_dir"].mkdir(parents=True, exist_ok=True)

    # 1) Build / run corrected noinit registration.
    noinit_reg_manifest = _build_registration_manifest(
        family="noinit_nofallback",
        run_root=RUNS["noinit_reg"],
        datasets=("dair", "opv2v"),
    )
    noinit_reg_manifest_path = RUNS["noinit_reg"] / "manifest.json"
    noinit_reg_results_path = RUNS["noinit_reg"] / "results.json"
    _write_manifest(noinit_reg_manifest_path, noinit_reg_manifest)
    if not args.skip_noinit_registration:
        _run_manifest(
            manifest_path=noinit_reg_manifest_path,
            results_path=noinit_reg_results_path,
            is_downstream=False,
            gpus=gpus,
            max_per_gpu=int(args.max_per_gpu),
            dry_run=bool(args.dry_run),
        )

    # 2) Ensure choosebetter opv2v registration is complete enough for downstream.
    init_reg_p2_manifest_path = RUNS["init_reg_opv2v"] / "manifest.json"
    init_reg_p2_results_path = RUNS["init_reg_opv2v"] / "results.json"
    if not args.skip_init_registration:
        _run_manifest(
            manifest_path=init_reg_p2_manifest_path,
            results_path=init_reg_p2_results_path,
            is_downstream=False,
            gpus=gpus,
            max_per_gpu=int(args.max_per_gpu),
            dry_run=bool(args.dry_run),
        )

    # 3) Build / run corrected noinit downstream.
    noinit_down_manifest = _build_downstream_manifest(
        family="noinit_nofallback",
        run_root=RUNS["noinit_down"],
        cache_roots={
            "dair": RUNS["noinit_reg"],
            "opv2v": RUNS["noinit_reg"],
        },
    )
    noinit_down_manifest_path = RUNS["noinit_down"] / "manifest.json"
    noinit_down_results_path = RUNS["noinit_down"] / "results.json"
    _write_manifest(noinit_down_manifest_path, noinit_down_manifest)
    if not args.skip_noinit_downstream:
        _run_manifest(
            manifest_path=noinit_down_manifest_path,
            results_path=noinit_down_results_path,
            is_downstream=True,
            gpus=gpus,
            max_per_gpu=int(args.max_per_gpu),
            dry_run=bool(args.dry_run),
        )

    # 4) Build / run choosebetter downstream using existing dair registration + completed opv2v registration root.
    init_down_manifest = _build_downstream_manifest(
        family="init_choosebetter",
        run_root=RUNS["init_down"],
        cache_roots={
            "dair": RUNS["init_reg_dair"],
            "opv2v": RUNS["init_reg_opv2v"],
        },
    )
    init_down_manifest_path = RUNS["init_down"] / "manifest.json"
    init_down_results_path = RUNS["init_down"] / "results.json"
    _write_manifest(init_down_manifest_path, init_down_manifest)
    if not args.skip_init_downstream:
        _run_manifest(
            manifest_path=init_down_manifest_path,
            results_path=init_down_results_path,
            is_downstream=True,
            gpus=gpus,
            max_per_gpu=int(args.max_per_gpu),
            dry_run=bool(args.dry_run),
        )

    if not args.dry_run:
        if not args.skip_noinit_registration:
            _require_complete_results(noinit_reg_results_path, expected_jobs=24, label="noinit registration")
        if not args.skip_init_registration:
            _require_complete_results(init_reg_p2_results_path, expected_jobs=44, label="init choosebetter opv2v registration")
        if not args.skip_noinit_downstream:
            _require_complete_results(noinit_down_results_path, expected_jobs=24, label="noinit downstream")
        if not args.skip_init_downstream:
            _require_complete_results(init_down_results_path, expected_jobs=88, label="init choosebetter downstream")

    # 5) Summaries.
    noinit_summary = RUNS["noinit_down"] / "results_ap50_from_yaml.json"
    init_summary = RUNS["init_down"] / "results_ap50_from_yaml.json"
    _summarize_downstream(RUNS["noinit_down"], noinit_down_manifest_path, noinit_down_results_path, noinit_summary)
    _summarize_downstream(RUNS["init_down"], init_down_manifest_path, init_down_results_path, init_summary)

    # 6) Final plots.
    if not args.skip_plot:
        _plot_benchmark(
            noinit_summary,
            RUNS["plot_dir"] / "unified_noise_curve_benchmark_noinit_nofallback_ap50.svg",
            title="Camera Detection Boxes | No-Init, No-Fallback",
            subtitle="Canonical contract: DAIR-V2X + OPV2V, paired non-ego noise, force_pose_confidence=1.0",
        )
        _plot_benchmark(
            init_summary,
            RUNS["plot_dir"] / "unified_noise_curve_benchmark_init_choosebetter_ap50.svg",
            title="Camera Detection Boxes | Init, Choose-Better",
            subtitle="Canonical contract: DAIR-V2X + OPV2V, paired non-ego noise, force_pose_confidence=1.0",
        )


if __name__ == "__main__":
    main()
