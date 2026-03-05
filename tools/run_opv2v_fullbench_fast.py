#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import subprocess
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
HEAL = "HEAL"
initfree = "initfree"
stable = "stable"
DEFAULT_PYTHON = ROOT / ".micromamba" / "envs" / "py39" / "bin" / "python"
SCRIPT = ROOT / "HEAL" / "opencood" / "tools" / "inference_w_noise.py"

DEFAULT_CAMERA_MODEL = ROOT / "HEAL" / "opencood" / "logs" / "opv2v_camera_v2xvit_full_prope"
DEFAULT_LIDAR_MODEL = ROOT / "HEAL" / "opencood" / "logs" / "freealign_repro_opv2v_baseline"
DEFAULT_CAMERA_STAGE1 = (
    ROOT
    / "data"
    / "OPV2V"
    / "detected"
    / "opv2v_camera_v2xvit_stage1_percav"
    / "test"
    / "stage1_boxes.json"
)
DEFAULT_LIDAR_STAGE1 = ROOT / "data" / "OPV2V" / "detected" / "opv2v_lidar_v2xvit_stage1" / "test" / "stage1_boxes.json"
DEFAULT_V2XREGPP_CONFIG = ROOT / "configs" / "dair" / "midfusion" / "pipeline_midfusion_detection_occ.yaml"
if not DEFAULT_V2XREGPP_CONFIG.exists():
    # Backward-compat path used by older notes/scripts.
    DEFAULT_V2XREGPP_CONFIG = ROOT / "configs" / "pipeline_midfusion_detection_occ.yaml"
DEFAULT_OPV2V_TEST_SAMPLES = 2170

METHODS = {
    "v2xregpp": {
        "initfree": "v2xregpp_initfree",
        "stable": "v2xregpp_stable",
        "needs_stage1": True,
        "family": "v2xregpp",
        "extra_args": [],
    },
    "v2xregpp_occhint": {
        "initfree": "v2xregpp_initfree",
        "stable": "v2xregpp_stable",
        "needs_stage1": True,
        "family": "v2xregpp",
        "extra_args": ["--v2xregpp-use-occ-hint"],
    },
    "freealign": {
        "initfree": "freealign_paper",
        "stable": "freealign_paper_stable",
        "needs_stage1": True,
        "family": "generic",
        "extra_args": [],
    },
    "vips": {
        "initfree": "vips_initfree",
        "stable": "vips_stable",
        "needs_stage1": True,
        "family": "generic",
        "extra_args": [],
    },
    "vips_noprior": {
        "initfree": "vips_initfree",
        "stable": "vips_stable",
        "needs_stage1": True,
        "family": "generic",
        "extra_args": [],
    },
    "vips_prior": {
        "initfree": "vips_initfree",
        "stable": "vips_stable",
        "needs_stage1": True,
        "family": "generic",
        "extra_args": ["--vips-use-prior"],
    },
    "cbm": {
        "initfree": "cbm_initfree",
        "stable": "cbm_stable",
        "needs_stage1": True,
        "family": "generic",
        "extra_args": [],
    },
    "cbm_noprior": {
        "initfree": "cbm_initfree",
        "stable": "cbm_stable",
        "needs_stage1": True,
        "family": "generic",
        "extra_args": [],
    },
    "cbm_prior": {
        "initfree": "cbm_initfree",
        "stable": "cbm_stable",
        "needs_stage1": True,
        "family": "generic",
        "extra_args": ["--cbm-use-prior"],
    },
    "imagematch_noinit": {
        "initfree": "image_match_initfree",
        "stable": "image_match_stable",
        "needs_stage1": False,
        "family": "generic",
        "extra_args": ["--image-match-init-source none"],
        "supported_modalities": ("camera",),
    },
    "imagematch_current": {
        "initfree": "image_match_initfree",
        "stable": "image_match_stable",
        "needs_stage1": False,
        "family": "generic",
        "extra_args": ["--image-match-init-source current"],
        "supported_modalities": ("camera",),
    },
    "lidarreg_ransac": {
        "initfree": "lidar_reg_initfree",
        "stable": "lidar_reg_stable",
        "needs_stage1": False,
        "family": "generic",
        "extra_args": ["--lidar-reg-global-method ransac"],
        "supported_modalities": ("lidar",),
    },
    "hkust_teaser": {
        "initfree": "lidar_reg_initfree",
        "stable": "lidar_reg_stable",
        "needs_stage1": False,
        "family": "generic",
        "extra_args": ["--lidar-reg-global-method teaser_gnctls"],
        "supported_modalities": ("lidar",),
    },
    "hkust_fgr": {
        "initfree": "lidar_reg_initfree",
        "stable": "lidar_reg_stable",
        "needs_stage1": False,
        "family": "generic",
        "extra_args": ["--lidar-reg-global-method teaser_fgr"],
        "supported_modalities": ("lidar",),
    },
    "hkust_quatro": {
        "initfree": "lidar_reg_initfree",
        "stable": "lidar_reg_stable",
        "needs_stage1": False,
        "family": "generic",
        "extra_args": ["--lidar-reg-global-method teaser_quatro"],
        "supported_modalities": ("lidar",),
    },
}


@dataclass
class Task:
    key: Tuple[str, str, str, str, str]
    cmd: str
    log_path: Path


def parse_list(value: str) -> List[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def normalize_noise(val: str) -> str:
    return f"{float(val):.1f}"


def build_task_key(modality: str, sweep: str, method: str, strategy: str, noise: str) -> Tuple[str, str, str, str, str]:
    return (modality, sweep, method, strategy, noise)


def task_log_name(modality: str, sweep: str, method: str, strategy: str, noise: str) -> str:
    return f"{modality}_{sweep}_{method}_{strategy}_n{noise}.log"


def build_common_args(
    model_dir: Path,
    pos: str,
    rot: str,
    num_workers: int,
    dropout: Optional[float],
    comm_range_override: int,
    *,
    solver_backend: str,
    runtime_mode: str,
    pose_source: str,
    comm_range_gating: str,
    max_eval_samples: Optional[int],
    deterministic_strict: bool,
    online_gpu_stage1_solver: bool,
    online_skip_pairwise_rebuild: bool,
) -> List[str]:
    args = [
        f"--model_dir {model_dir}",
        "--fusion_method intermediate",
        f"--comm-range-override {int(comm_range_override)}",
        f"--pos-std-list {pos}",
        f"--rot-std-list {rot}",
        "--sweep-mode paired",
        "--noise-target non-ego",
        f"--num-workers {num_workers}",
        # Avoid generating massive vis_*/bev_*.png outputs during benchmark sweeps.
        "--save_vis_interval 100000000",
        "--log-interval 200",
        "--pose-timing",
        "--pose-device cuda",
        f"--solver-backend {solver_backend}",
        f"--pose-source {pose_source}",
    ]
    # Freeze comm-range semantics across all methods to avoid confounds where
    # pose-correction implicitly toggles clean-vs-noisy gating in inference_w_noise.py.
    if comm_range_gating and str(comm_range_gating).strip().lower() != "auto":
        args.append(f"--comm-range-gating {comm_range_gating}")
    if deterministic_strict:
        args.append("--deterministic-strict")
    if online_gpu_stage1_solver:
        args.append("--online-gpu-stage1-solver")
    if online_skip_pairwise_rebuild:
        args.append("--online-skip-pairwise-rebuild")
    if runtime_mode:
        args.append(f"--runtime-mode {runtime_mode}")
    if dropout is not None and dropout > 0:
        args.append(f"--pose-dropout-prob {dropout}")
    if max_eval_samples is not None and int(max_eval_samples) > 0:
        args.append(f"--max-eval-samples {int(max_eval_samples)}")
    return args


def build_tasks(
    *,
    run_id: str,
    noise_list: Sequence[str],
    rot_list: Sequence[str],
    dropout_prob: float,
    camera_model: Path,
    lidar_model: Path,
    camera_stage1: Path,
    lidar_stage1: Path,
    num_workers: int,
    include_dropout: bool,
    python_bin: Path,
    v2xregpp_config: Path,
    log_dir: Path,
    solver_backend: str,
    runtime_mode: str,
    pose_source: str,
    comm_range_gating: str,
    comm_range_override: int,
    pose_compare_distance_threshold: float,
    pose_current_precision_threshold: float,
    pose_min_precision_improvement: float,
    pose_min_matched_improvement: int,
    max_eval_samples: Optional[int],
    deterministic_strict: bool,
    online_gpu_stage1_solver: bool,
    online_skip_pairwise_rebuild: bool,
    lidar_reg_cache_dir: Optional[Path],
    require_lidar_reg_cache: bool,
    methods: Sequence[str],
    include_baseline: bool,
    include_oracle: bool,
    include_single: bool,
    modalities: Sequence[str] = ("camera", "lidar"),
    sweeps: Sequence[str] = ("noise10", "drop20"),
) -> List[Task]:
    tasks: List[Task] = []
    # Memoize cache meta reads (avoid re-parsing JSON per noise/method/strategy).
    cache_meta_by_path: Dict[Path, dict] = {}

    if len(noise_list) != len(rot_list):
        raise ValueError("noise_list and rot_list must have same length")
    for m in methods:
        if m not in METHODS:
            raise ValueError(f"Unknown method: {m} (expected one of {sorted(METHODS)})")

    def add_task(modality: str, sweep: str, method: str, strategy: str, noise: str, cmd: str):
        key = build_task_key(modality, sweep, method, strategy, noise)
        log_path = log_dir / task_log_name(modality, sweep, method, strategy, noise)
        tasks.append(Task(key=key, cmd=cmd, log_path=log_path))

    def _lidar_reg_global_method(meta: dict) -> str:
        extra = meta.get("extra_args") or []
        for item in extra:
            if not isinstance(item, str):
                continue
            if item.strip().startswith("--lidar-reg-global-method"):
                toks = item.strip().split()
                if len(toks) >= 2:
                    return str(toks[1]).strip()
        # Matches inference_w_noise default (when global_method==auto and use_fgr=False).
        return "ransac"

    def _load_cache_meta(path: Path) -> dict:
        if path in cache_meta_by_path:
            return cache_meta_by_path[path]
        try:
            obj = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
            meta = obj.get("meta") if isinstance(obj, dict) else None
            meta = meta if isinstance(meta, dict) else {}
        except Exception:
            meta = {}
        cache_meta_by_path[path] = meta
        return meta

    def _require_full_cache(path: Path, *, global_method: str) -> None:
        """
        If we are evaluating the full OPV2V test split (i.e., max_eval_samples is None),
        refuse caches that were explicitly generated with --max-samples > 0.

        Otherwise the benchmark may silently fall back to on-the-fly registration for missing keys
        (slow + unintended), or mix cached vs uncached pairs (hard to reason about).
        """
        full_eval = max_eval_samples is None
        if not full_eval:
            return
        meta = _load_cache_meta(path)
        if "max_samples" not in meta:
            raise SystemExit(
                f"[PRECHECK] lidar-reg cache missing meta.max_samples: {path} (global_method={global_method}). "
                "Refuse for full eval; regenerate cache with tools/precompute_opv2v_lidar_reg_cache.py"
            )
        try:
            max_samples = int(meta.get("max_samples") or 0)
        except Exception:
            max_samples = -1
        if max_samples != 0:
            raise SystemExit(
                f"[PRECHECK] lidar-reg cache appears partial (meta.max_samples={max_samples}): {path} (global_method={global_method}). "
                "Refuse for full eval; regenerate with --max-samples 0."
            )

    modality_specs = {
        "camera": (camera_model, camera_stage1),
        "lidar": (lidar_model, lidar_stage1),
    }
    for modality in modalities:
        if modality not in modality_specs:
            raise ValueError(f"Unknown modality: {modality} (expected one of {sorted(modality_specs)})")
        model_dir, stage1 = modality_specs[modality]
        for sweep in sweeps:
            if sweep not in ("noise10", "drop20"):
                raise ValueError(f"Unknown sweep: {sweep} (expected noise10,drop20)")
            use_dropout = dropout_prob if (sweep == "drop20" and include_dropout) else None
            # baseline + oracle per noise
            for noise, rot in zip(noise_list, rot_list):
                common = build_common_args(
                    model_dir,
                    noise,
                    rot,
                    num_workers,
                    use_dropout,
                    comm_range_override,
                    solver_backend=solver_backend,
                    runtime_mode=runtime_mode,
                    pose_source=pose_source,
                    comm_range_gating=comm_range_gating,
                    max_eval_samples=max_eval_samples,
                    deterministic_strict=deterministic_strict,
                    online_gpu_stage1_solver=online_gpu_stage1_solver,
                    online_skip_pairwise_rebuild=online_skip_pairwise_rebuild,
                )
                if include_baseline:
                    note = f"_{run_id}_{modality}_{sweep}_baseline_n{noise}"
                    cmd = build_cmd(python_bin, common + [f"--pose-correction none --note {note}"])
                    add_task(modality, sweep, "baseline", "bounds", noise, cmd)

                if include_oracle:
                    note = f"_{run_id}_{modality}_{sweep}_oracle_n{noise}"
                    cmd = build_cmd(python_bin, common + [f"--pose-correction oracle_gt --note {note}"])
                    add_task(modality, sweep, "oracle", "bounds", noise, cmd)

                for method_name in methods:
                    meta = METHODS[method_name]
                    supported_modalities = tuple(meta.get("supported_modalities") or ())
                    if supported_modalities and modality not in supported_modalities:
                        continue
                    # best-of
                    note = f"_{run_id}_{modality}_{sweep}_{method_name}_best_n{noise}"
                    args = [f"--pose-correction {meta[initfree]}", "--pose-compare-current", f"--note {note}"]
                    args.extend(
                        [
                            f"--pose-compare-distance-threshold {float(pose_compare_distance_threshold)}",
                            f"--pose-current-precision-threshold {float(pose_current_precision_threshold)}",
                            f"--pose-min-precision-improvement {float(pose_min_precision_improvement)}",
                            f"--pose-min-matched-improvement {int(pose_min_matched_improvement)}",
                        ]
                    )
                    if meta.get("needs_stage1"):
                        args.append(f"--stage1-result {stage1}")
                    if meta.get("family") == "v2xregpp":
                        args.append(f"--v2xregpp-config {v2xregpp_config}")
                    args.extend(meta.get("extra_args", []))
                    if lidar_reg_cache_dir and str(meta.get("initfree", "")).startswith("lidar_reg"):
                        gm = _lidar_reg_global_method(meta)
                        cache_path = (Path(lidar_reg_cache_dir) / f"opv2v_test_{gm}.json").resolve()
                        if require_lidar_reg_cache and not cache_path.exists():
                            raise SystemExit(f"[PRECHECK] Missing lidar-reg cache: {cache_path}")
                        if require_lidar_reg_cache and cache_path.exists():
                            _require_full_cache(cache_path, global_method=gm)
                        if cache_path.exists():
                            args.append(f"--lidar-reg-cache {cache_path}")
                    cmd = build_cmd(python_bin, common + [" ".join(args)])
                    add_task(modality, sweep, method_name, "best", noise, cmd)

                    # stable
                    note = f"_{run_id}_{modality}_{sweep}_{method_name}_stable_n{noise}"
                    args = [f"--pose-correction {meta[stable]}", f"--note {note}"]
                    if meta.get("needs_stage1"):
                        args.append(f"--stage1-result {stage1}")
                    if meta.get("family") == "v2xregpp":
                        args.append(f"--v2xregpp-config {v2xregpp_config}")
                    args.extend(meta.get("extra_args", []))
                    if lidar_reg_cache_dir and str(meta.get("initfree", "")).startswith("lidar_reg"):
                        gm = _lidar_reg_global_method(meta)
                        cache_path = (Path(lidar_reg_cache_dir) / f"opv2v_test_{gm}.json").resolve()
                        if require_lidar_reg_cache and not cache_path.exists():
                            raise SystemExit(f"[PRECHECK] Missing lidar-reg cache: {cache_path}")
                        if require_lidar_reg_cache and cache_path.exists():
                            _require_full_cache(cache_path, global_method=gm)
                        if cache_path.exists():
                            args.append(f"--lidar-reg-cache {cache_path}")
                    cmd = build_cmd(python_bin, common + [" ".join(args)])
                    add_task(modality, sweep, method_name, "stable", noise, cmd)

            # single baseline (noise 0 only)
            common = [
                f"--model_dir {model_dir}",
                "--fusion_method intermediate",
                f"--comm-range-override {int(comm_range_override)}",
                "--pos-std-list 0",
                "--rot-std-list 0",
                "--sweep-mode paired",
                "--noise-target non-ego",
                f"--num-workers {num_workers}",
                "--save_vis_interval 100000000",
                "--log-interval 200",
                "--pose-timing",
                "--pose-device cuda",
                f"--solver-backend {solver_backend}",
                f"--pose-source {pose_source}",
                # Fair single-agent baseline: keep the same comm_range/labels as cooperative runs,
                # but force the forward pass to use only ego inputs (no comm). This avoids the
                # "comm_range=0 makes the task easier" confound where single can look better than oracle.
                "--force-ego-input-only",
            ]
            if comm_range_gating and str(comm_range_gating).strip().lower() != "auto":
                common.append(f"--comm-range-gating {comm_range_gating}")
            if deterministic_strict:
                common.append("--deterministic-strict")
            if online_gpu_stage1_solver:
                common.append("--online-gpu-stage1-solver")
            if online_skip_pairwise_rebuild:
                common.append("--online-skip-pairwise-rebuild")
            if runtime_mode:
                common.append(f"--runtime-mode {runtime_mode}")
            if use_dropout is not None and use_dropout > 0:
                common.append(f"--pose-dropout-prob {use_dropout}")
            if max_eval_samples is not None and int(max_eval_samples) > 0:
                common.append(f"--max-eval-samples {int(max_eval_samples)}")
            if include_single:
                note = f"_{run_id}_{modality}_{sweep}_single_ego_only"
                cmd = build_cmd(python_bin, common + [f"--pose-correction none --note {note}"])
                add_task(modality, sweep, "single", "bounds", normalize_noise("0"), cmd)

    return tasks


def build_cmd(python_bin: Path, args: List[str]) -> str:
    heal_path = ROOT / "HEAL"
    base = [f"PYTHONPATH={heal_path}", str(python_bin), str(SCRIPT)]
    cmd = " ".join(base + args)
    return cmd


def parse_completed_from_log(path: Path, modality: str, sweep: str, method: str, strategy: str) -> Dict[str, Dict[str, float]]:
    """Return noise->AP dict from a log file that may contain multiple noises."""
    results: Dict[str, Dict[str, float]] = {}
    current_noise: Optional[str] = None
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("Noise Added:"):
            m = re.search(r"Noise Added: ([0-9.]+)", line)
            if m:
                current_noise = m.group(1)
                results.setdefault(current_noise, {})
            continue
        if "The Average Precision at IOU" in line and current_noise:
            m = re.search(r"IOU ([0-9.]+) is ([0-9.]+)", line)
            if m:
                iou = m.group(1)
                ap = float(m.group(2))
                results[current_noise][iou] = ap
    return results


def collect_done_keys(log_dir: Path) -> Dict[Tuple[str, str, str, str, str], Dict[str, float]]:
    done: Dict[Tuple[str, str, str, str, str], Dict[str, float]] = {}
    for path in log_dir.glob("*.log"):
        name = path.name
        # new-style
        m = re.match(r"(camera|lidar)_(noise10|drop20)_([a-z0-9_]+)_(best|stable|bounds)_n([0-9.]+)\.log", name)
        if m:
            modality, sweep, method, strategy, noise = m.groups()
            parsed = parse_completed_from_log(path, modality, sweep, method, strategy)
            if parsed:
                # single-noise logs should only have one entry
                key = build_task_key(modality, sweep, method, strategy, noise)
                ap = parsed.get(noise)
                if ap:
                    done[key] = ap
            continue
        # legacy names for baseline/oracle/single
        m = re.match(r"(camera|lidar)_(noise10|drop20)_(baseline|oracle|single)\.log", name)
        if m:
            modality, sweep, method = m.groups()
            strategy = "bounds"
            parsed = parse_completed_from_log(path, modality, sweep, method, strategy)
            for noise, ap in parsed.items():
                key = build_task_key(modality, sweep, method, strategy, noise)
                done[key] = ap
            continue
        # legacy names for best/stable methods
        m = re.match(r"(camera|lidar)_(noise10|drop20)_([a-z0-9_]+)_(best|stable)\.log", name)
        if not m:
            continue
        modality, sweep, method, strategy = m.groups()
        parsed = parse_completed_from_log(path, modality, sweep, method, strategy)
        for noise, ap in parsed.items():
            key = build_task_key(modality, sweep, method, strategy, noise)
            done[key] = ap
    return done


def write_config_snapshot(out_dir: Path, args: argparse.Namespace, noise_list: Sequence[str], rot_list: Sequence[str]):
    cfg = {
        "run_id": args.run_id,
        "gpus": args.gpus,
        "max_per_gpu": args.max_per_gpu,
        "num_workers": args.num_workers,
        "fusion_method": "intermediate",
        "comm_range_override": int(getattr(args, "comm_range_override", 0)),
        "sweep_mode": "paired",
        "noise_target": "non-ego",
        "save_vis_interval": 100000000,
        "modalities": args.modalities,
        "sweeps": args.sweeps,
        "noise_list": list(noise_list),
        "rot_list": list(rot_list),
        "dropout": args.dropout,
        "include_dropout": not args.no_dropout,
        "max_eval_samples": int(getattr(args, "max_eval_samples", 0)),
        "allow_pose_override": bool(getattr(args, "allow_pose_override", False)),
        "skip_preflight": bool(getattr(args, "skip_preflight", False)),
        "stage1_expected_samples": int(getattr(args, "stage1_expected_samples", DEFAULT_OPV2V_TEST_SAMPLES)),
        "log_mode": getattr(args, "log_mode", "append"),
        "camera_model": str(args.camera_model),
        "lidar_model": str(args.lidar_model),
        "camera_stage1": str(args.camera_stage1),
        "lidar_stage1": str(args.lidar_stage1),
        "python_bin": str(args.python_bin),
        "v2xregpp_config": str(args.v2xregpp_config),
        "solver_backend": str(getattr(args, "solver_backend", "offline_map")),
        "runtime_mode": str(getattr(args, "runtime_mode", "")),
        "pose_source": str(getattr(args, "pose_source", "noisy_input")),
        "pose_compare_distance_threshold": float(getattr(args, "pose_compare_distance_threshold", 3.0)),
        "pose_current_precision_threshold": float(getattr(args, "pose_current_precision_threshold", 1.8)),
        "pose_min_precision_improvement": float(getattr(args, "pose_min_precision_improvement", 0.0)),
        "pose_min_matched_improvement": int(getattr(args, "pose_min_matched_improvement", 0)),
        "comm_range_gating": str(getattr(args, "comm_range_gating", "auto")),
        "deterministic_strict": bool(getattr(args, "deterministic_strict", False)),
        "online_gpu_stage1_solver": bool(getattr(args, "online_gpu_stage1_solver", False)),
        "online_skip_pairwise_rebuild": bool(getattr(args, "online_skip_pairwise_rebuild", False)),
        "lidar_reg_cache_dir": str(getattr(args, "lidar_reg_cache_dir", "") or ""),
        "require_lidar_reg_cache": bool(getattr(args, "require_lidar_reg_cache", False)),
        "methods": parse_list(getattr(args, "methods", "")),
        "skip_baseline": bool(getattr(args, "skip_baseline", False)),
        "skip_oracle": bool(getattr(args, "skip_oracle", False)),
        "skip_single": bool(getattr(args, "skip_single", False)),
    }
    # Record GPU allocation context for traceability (e.g. Slurm remapping).
    try:
        cfg["parent_cuda_visible_devices"] = str(os.environ.get("CUDA_VISIBLE_DEVICES", "") or "")
    except Exception:
        pass
    # Include git provenance for evidence-grade comparisons.
    try:
        cfg["git_commit"] = (
            subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
        )
        cfg["git_branch"] = (
            subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "--abbrev-ref", "HEAD"], text=True).strip()
        )
        cfg["git_dirty"] = bool(
            subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain=v1"], text=True).strip()
        )
    except Exception:
        pass
    try:
        heal_root = ROOT / HEAL
        if (heal_root / ".git").exists():
            cfg["heal_commit"] = (
                subprocess.check_output(["git", "-C", str(heal_root), "rev-parse", "HEAD"], text=True).strip()
            )
            cfg["heal_branch"] = (
                subprocess.check_output(["git", "-C", str(heal_root), "rev-parse", "--abbrev-ref", "HEAD"], text=True).strip()
            )
            cfg["heal_dirty"] = bool(
                subprocess.check_output(["git", "-C", str(heal_root), "status", "--porcelain=v1"], text=True).strip()
            )
    except Exception:
        pass
    try:
        cfg["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    (out_dir / "config_snapshot.json").write_text(json.dumps(cfg, indent=2))


def _resolve_stage1_path(path: Path) -> Path:
    path = Path(path)
    if path.is_dir():
        return path / "stage1_boxes.json"
    return path


def _validate_stage1_cache(path: Path, *, expected_samples: int, label: str) -> dict:
    path = _resolve_stage1_path(path)
    if not path.exists():
        raise SystemExit(f"[PRECHECK] Missing {label} stage1 cache: {path}")
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise SystemExit(f"[PRECHECK] Failed to parse {label} stage1 cache JSON: {path} ({e})")
    if not isinstance(obj, dict):
        raise SystemExit(f"[PRECHECK] {label} stage1 cache must be a dict: {path} (got {type(obj)})")
    if int(expected_samples) > 0 and len(obj) != int(expected_samples):
        raise SystemExit(
            f"[PRECHECK] {label} stage1 cache sample count mismatch: expected={expected_samples} actual={len(obj)} path={path}"
        )
    mismatch = 0
    missing_fields = Counter()
    for rec in obj.values():
        if not isinstance(rec, dict):
            continue
        for f in ("pred_corner3d_np_list", "cav_id_list", "lidar_pose_clean_np"):
            if f not in rec:
                missing_fields[f] += 1
        cav = rec.get("cav_id_list")
        pred = rec.get("pred_corner3d_np_list")
        if cav is None or pred is None:
            continue
        try:
            if len(cav) != len(pred):
                mismatch += 1
        except Exception:
            mismatch += 1
    if missing_fields:
        raise SystemExit(f"[PRECHECK] {label} stage1 cache missing fields: {dict(missing_fields)} path={path}")
    if mismatch:
        raise SystemExit(
            f"[PRECHECK] {label} stage1 cache has len(cav_id_list)!=len(pred_corner3d_np_list) for {mismatch}/{len(obj)} samples: {path}"
        )
    return obj


def _head_keys(obj: dict, n: int) -> List[str]:
    keys = []
    for k in obj.keys():
        ks = str(k)
        try:
            keys.append((int(ks), ks))
        except Exception:
            # Keep non-int keys after int keys.
            keys.append((10**18, ks))
    keys.sort(key=lambda x: (x[0], x[1]))
    return [ks for _, ks in keys[: max(1, int(n))]]


def _validate_stage1_semantics(obj: dict, *, label: str, samples: int, min_valid_samples: int) -> None:
    try:
        # NOTE: This script is sometimes launched with an explicit path
        # (e.g. `python /abs/path/to/tools/run_opv2v_fullbench_fast.py`) and a
        # working directory that is *not* the repo root. In that case, the repo
        # root may be missing from `sys.path`, so `tools.*` imports fail.
        # Fall back to importing from the script directory (which *is* on
        # `sys.path` as `sys.path[0]`).
        try:
            from tools.validate_stage1_semantics import check_stage1_semantics_dict
        except Exception:
            from validate_stage1_semantics import check_stage1_semantics_dict
    except Exception as e:
        raise SystemExit(f"[PRECHECK] Failed to import semantic stage1 validator: {e}")
    keys = _head_keys(obj, int(samples))
    summary = check_stage1_semantics_dict(obj, keys=keys, min_valid_samples=int(min_valid_samples))
    if not summary.ok:
        raise SystemExit(
            "[PRECHECK] {} stage1 semantic check failed: {} (valid_samples={} inverted_rate={:.3f} ratio_rel_over_id={:.3f})".format(
                label,
                summary.note,
                summary.valid_samples,
                summary.inverted_rate,
                summary.match_ratio_rel_over_id,
            )
        )


def _pose_override_is_zero(model_dir: Path) -> bool:
    cfg_path = Path(model_dir) / "config.yaml"
    if not cfg_path.exists():
        return False
    text = cfg_path.read_text(encoding="utf-8", errors="ignore")
    if "pose_override" not in text:
        return False
    try:
        import yaml  # type: ignore

        obj = yaml.safe_load(text)
        pose_override = (obj or {}).get("pose_override") or {}
        if isinstance(pose_override, dict):
            enabled = bool(pose_override.get("enabled", False))
            mode = str(pose_override.get("mode") or "").strip().lower()
            return enabled and mode == "zero"
    except Exception:
        pass

    # Fallback: scan the pose_override block by indentation.
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not re.match(r"^\s*pose_override\s*:\s*$", line):
            continue
        base_indent = len(line) - len(line.lstrip(" "))
        enabled = None
        mode = None
        for j in range(i + 1, len(lines)):
            raw = lines[j]
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            if indent <= base_indent:
                break
            m = re.match(r"^\s*enabled\s*:\s*([A-Za-z0-9_]+)\s*$", raw)
            if m:
                enabled = m.group(1).strip().lower() in {"true", "1", "yes"}
            m = re.match(r"^\s*mode\s*:\s*([A-Za-z0-9_]+)\s*$", raw)
            if m:
                mode = m.group(1).strip().lower()
        return bool(enabled) and str(mode or "").lower() == "zero"
    return False


def _git_is_dirty(repo: Path) -> Optional[bool]:
    """
    Returns:
      - True/False if git status can be queried
      - None if repo is not a git worktree or git is unavailable
    """
    try:
        out = subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain=v1"], text=True)
        return bool(out.strip())
    except Exception:
        return None


def collect_done_from_state(state_path: Path) -> set:
    """
    Treat any task with an `end` event and exit code 0 as done.

    This makes the launcher resumable without relying on log parsing, which is brittle
    if logs were overwritten or truncated.
    """
    done = set()
    if not state_path.exists():
        return done
    for line in state_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("event") != "end":
            continue
        if obj.get("code") != 0:
            continue
        key = obj.get("task")
        if not isinstance(key, list):
            continue
        done.add(tuple(key))
    return done


def load_in_progress(state_path: Path) -> set:
    if not state_path.exists():
        return set()
    # Track unmatched starts with PIDs so we can ignore stale "in progress" tasks
    # after a launcher crash / manual kill.
    open_starts: Dict[Tuple[str, str, str, str, str], List[int]] = {}
    for line in state_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        key = obj.get("task")
        if not isinstance(key, list):
            continue
        key_t = tuple(key)
        if obj.get("event") == "start":
            pid = obj.get("pid")
            if isinstance(pid, int):
                open_starts.setdefault(key_t, []).append(pid)
            else:
                open_starts.setdefault(key_t, [])
        elif obj.get("event") == "end":
            if key_t in open_starts and open_starts[key_t]:
                # Match one start; usually there is at most one in flight per key.
                open_starts[key_t].pop(0)
    in_progress = set()
    for key, pids in open_starts.items():
        if not pids:
            continue
        # If the latest PID no longer exists, treat this as stale (not in-progress)
        # so a restart can re-run the task.
        pid = pids[-1]
        try:
            # Signal 0 only checks existence/permission.
            os.kill(int(pid), 0)
        except Exception:
            continue
        in_progress.add(key)
    return in_progress


def schedule_tasks(tasks: List[Task], gpus: List[int], max_per_gpu: int, out_dir: Path, *, log_mode: str):
    # simple scheduler: keep up to max_per_gpu processes per GPU
    gpu_slots: Dict[int, List[subprocess.Popen]] = {g: [] for g in gpus}
    queue = deque(tasks)
    state_path = out_dir / "run_state.jsonl"
    # Map "GPU slot indices" (args.gpus) to actual CUDA_VISIBLE_DEVICES entries
    # provided by the parent environment (e.g. Slurm). This prevents accidentally
    # running on GPUs outside the allocation when Slurm remaps visible devices.
    parent_visible = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    parent_visible_list = [v.strip() for v in str(parent_visible).split(",") if v.strip()]
    cuda_visible_map: Dict[int, str] = {}
    if parent_visible_list:
        for idx in gpus:
            if 0 <= int(idx) < len(parent_visible_list):
                cuda_visible_map[int(idx)] = parent_visible_list[int(idx)]

    def launch(task: Task, gpu: int):
        env = os.environ.copy()
        # NOTE: `gpu` is a slot index. Resolve it to a real visible device string
        # (can be numeric or UUID) when the parent exports CUDA_VISIBLE_DEVICES.
        env["CUDA_VISIBLE_DEVICES"] = cuda_visible_map.get(int(gpu), str(gpu))
        env["PYTHONPATH"] = str(ROOT / "HEAL")
        env["OPENCOOD_VOXEL_GPU"] = "1"
        env.setdefault("OMP_NUM_THREADS", "1")
        env.setdefault("MKL_NUM_THREADS", "1")
        env.setdefault("OPENBLAS_NUM_THREADS", "1")
        env.setdefault("NUMEXPR_NUM_THREADS", "1")
        task.log_path.parent.mkdir(parents=True, exist_ok=True)
        # Never silently truncate historical logs unless explicitly requested.
        mode = "a" if log_mode == "append" else "w"
        log_f = open(task.log_path, mode, encoding="utf-8")
        log_f.write(
            "\n"
            + "=" * 80
            + "\n"
            + f"[LAUNCH] time={time.strftime('%Y-%m-%d %H:%M:%S')} gpu={gpu} cmd={task.cmd}\n"
            + "=" * 80
            + "\n"
        )
        log_f.flush()
        proc = subprocess.Popen(task.cmd, shell=True, env=env, stdout=log_f, stderr=subprocess.STDOUT)
        gpu_slots[gpu].append((proc, log_f, task))
        with state_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"event": "start", "task": task.key, "gpu": gpu, "pid": proc.pid, "time": time.time()}) + "\n")

    def reap():
        for gpu in gpus:
            alive = []
            for proc, log_f, task in gpu_slots[gpu]:
                ret = proc.poll()
                if ret is None:
                    alive.append((proc, log_f, task))
                    continue
                log_f.close()
                with state_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"event": "end", "task": task.key, "gpu": gpu, "pid": proc.pid, "code": ret, "time": time.time()}) + "\n")
            gpu_slots[gpu] = alive

    while queue or any(gpu_slots[g] for g in gpus):
        # fill available slots
        for gpu in gpus:
            while queue and len(gpu_slots[gpu]) < max_per_gpu:
                task = queue.popleft()
                launch(task, gpu)
        time.sleep(2)
        reap()


def collect_final_codes(state_path: Path) -> Dict[Tuple[str, str, str, str, str], int]:
    """
    Return the final exit code per task key using the last `end` event for that task.

    `run_state.jsonl` is append-only and chronological, so "last seen" is the final status.
    """
    final: Dict[Tuple[str, str, str, str, str], int] = {}
    if not state_path.exists():
        return final
    for line in state_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("event") != "end":
            continue
        key = obj.get("task")
        if not isinstance(key, list) or len(key) != 5:
            continue
        code = obj.get("code")
        try:
            code_i = int(code)
        except Exception:
            code_i = 999
        final[tuple(str(x) for x in key)] = code_i
    return final


def main():
    parser = argparse.ArgumentParser(description="Run OPV2V full benchmark with noise-split scheduling.")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--gpus", default="0,1,2,3,4,5,6,7,8,9")
    parser.add_argument("--max-per-gpu", type=int, default=2)
    parser.add_argument("--num-workers", type=int, default=4)
    parser.add_argument("--modalities", default="camera,lidar", help="Comma-separated: camera,lidar (default: both).")
    parser.add_argument("--sweeps", default="noise10,drop20", help="Comma-separated: noise10,drop20 (default: both).")
    parser.add_argument("--noise-list", default="0,1,2,3,4,5,6,7,8,9,10")
    parser.add_argument("--rot-list", default="0,1,2,3,4,5,6,7,8,9,10")
    parser.add_argument("--dropout", type=float, default=0.2)
    parser.add_argument("--no-dropout", action="store_true")
    parser.add_argument(
        "--methods",
        type=str,
        default="v2xregpp,freealign,vips,cbm",
        help=f"Comma-separated pose-correction methods to run (choices: {','.join(sorted(METHODS))}).",
    )
    parser.add_argument("--skip-baseline", action="store_true", help="Skip baseline (pose-correction=none) tasks.")
    parser.add_argument("--skip-oracle", action="store_true", help="Skip oracle (pose-correction=oracle_gt) tasks.")
    parser.add_argument(
        "--skip-single",
        action="store_true",
        help="Skip canonical single-agent bounds (single_ego_only via --force-ego-input-only, noise=0).",
    )
    parser.add_argument(
        "--max-eval-samples",
        type=int,
        default=0,
        help="Per-noise sample cap forwarded to inference_w_noise.py (0=full split; use >0 for smoke).",
    )
    parser.add_argument("--camera-model", type=Path, default=DEFAULT_CAMERA_MODEL)
    parser.add_argument("--lidar-model", type=Path, default=DEFAULT_LIDAR_MODEL)
    parser.add_argument("--camera-stage1", type=Path, default=DEFAULT_CAMERA_STAGE1)
    parser.add_argument("--lidar-stage1", type=Path, default=DEFAULT_LIDAR_STAGE1)
    parser.add_argument("--python-bin", type=Path, default=DEFAULT_PYTHON)
    parser.add_argument("--v2xregpp-config", type=Path, default=DEFAULT_V2XREGPP_CONFIG)
    parser.add_argument("--reuse-log-dir", type=Path, default=None)
    parser.add_argument("--log-mode", choices=["append", "overwrite"], default="append")
    parser.add_argument("--force-rerun", action="store_true", help="Ignore previous successful end events in run_state.jsonl.")
    parser.add_argument(
        "--solver-backend",
        type=str,
        default="offline_map",
        choices=["offline_map", "online_box", "online_box_feat_refine"],
        help="Pose solver backend forwarded to inference_w_noise.py (default: offline_map).",
    )
    parser.add_argument(
        "--runtime-mode",
        type=str,
        default="",
        choices=["", "single_only", "fusion_only", "register_only", "register_and_fuse"],
        help="Optional runtime mode forwarded to inference_w_noise.py.",
    )
    parser.add_argument(
        "--pose-source",
        type=str,
        default="noisy_input",
        choices=["noisy_input", "gt", "identity"],
        help="Pose source for runtime fusion-only mode.",
    )
    parser.add_argument(
        "--comm-range-gating",
        type=str,
        default="auto",
        choices=["auto", "clean", "noisy"],
        help="Freeze comm-range pruning semantics in inference_w_noise.py (recommended to avoid cross-method confounds).",
    )
    parser.add_argument(
        "--comm-range-override",
        type=int,
        default=70,
        help="Override comm_range passed to inference_w_noise.py (OPV2V canonical: 70).",
    )
    parser.add_argument("--pose-compare-distance-threshold", type=float, default=3.0)
    parser.add_argument("--pose-current-precision-threshold", type=float, default=1.8)
    parser.add_argument("--pose-min-precision-improvement", type=float, default=0.0)
    parser.add_argument("--pose-min-matched-improvement", type=int, default=0)
    parser.add_argument(
        "--deterministic-strict",
        action="store_true",
        help="Forward --deterministic-strict to inference_w_noise.py for stricter parity runs.",
    )
    parser.add_argument(
        "--online-gpu-stage1-solver",
        action="store_true",
        help="Forward --online-gpu-stage1-solver to inference_w_noise.py.",
    )
    parser.add_argument(
        "--online-skip-pairwise-rebuild",
        action="store_true",
        help="Forward --online-skip-pairwise-rebuild to inference_w_noise.py (useful for oracle parity checks).",
    )
    parser.add_argument(
        "--lidar-reg-cache-dir",
        type=Path,
        default=None,
        help="Optional directory containing precomputed OPV2V test caches for lidar_reg/hkust methods (files: opv2v_test_<global_method>.json).",
    )
    parser.add_argument(
        "--require-lidar-reg-cache",
        action="store_true",
        help="Fail preflight if a lidar_reg/hkust method is requested but its cache file is missing.",
    )
    parser.add_argument(
        "--allow-pose-override",
        action="store_true",
        help="Allow pose_override.enabled=true,mode=zero in model config (use for explicit no-extrinsics suites).",
    )
    parser.add_argument(
        "--stage1-expected-samples",
        type=int,
        default=DEFAULT_OPV2V_TEST_SAMPLES,
        help="Expected OPV2V test sample count in stage1 cache (default: 2170).",
    )
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip stage1/model config preflight checks (NOT recommended; can waste GPU days).",
    )
    parser.add_argument(
        "--skip-stage1-semantic-check",
        action="store_true",
        help="Skip stage1 semantic (frame convention) check. NOT recommended for new/unknown stage1 caches.",
    )
    parser.add_argument(
        "--stage1-semantic-samples",
        type=int,
        default=50,
        help="Number of samples (head) to use for stage1 semantic check.",
    )
    parser.add_argument(
        "--stage1-semantic-min-valid",
        type=int,
        default=10,
        help="Minimum valid samples required by stage1 semantic check.",
    )
    parser.add_argument(
        "--require-clean-git",
        action="store_true",
        help="Fail preflight if the main repo or HEAL submodule is git-dirty (recommended for canonical numbers).",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.run_id:
        args.run_id = "opv2v_fullbench_fast_" + time.strftime("%Y%m%d_%H%M%S")

    out_dir = ROOT / "outputs" / f"full_bench_{args.run_id}"
    LOG_DIR = out_dir / "logs"
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    noise_list = [normalize_noise(v) for v in parse_list(args.noise_list)]
    rot_list = [normalize_noise(v) for v in parse_list(args.rot_list)]
    gpus = [int(x) for x in parse_list(args.gpus)]
    modalities = parse_list(args.modalities)
    sweeps = parse_list(args.sweeps)
    methods = parse_list(args.methods)
    include_baseline = not bool(args.skip_baseline)
    include_oracle = not bool(args.skip_oracle)
    include_single = not bool(args.skip_single)

    # Hard preflight gates: stage1 integrity + pose_override mismatch.
    if not args.skip_preflight:
        # Semantics freeze: auto gating can silently change comm-range pruning semantics across methods
        # under online runtimes. Require an explicit setting for evidence-grade benchmarks.
        if str(args.solver_backend).strip().lower() != "offline_map" and str(args.comm_range_gating).strip().lower() == "auto":
            raise SystemExit(
                "[PRECHECK] comm-range-gating=auto with an online solver backend can introduce cross-method confounds. "
                "Pass --comm-range-gating noisy (recommended) or clean to freeze semantics."
            )

        expected_samples = int(args.stage1_expected_samples)
        needs_camera_stage1 = any(METHODS[m].get("needs_stage1") for m in methods)
        needs_lidar_stage1 = any(METHODS[m].get("needs_stage1") for m in methods)
        cam_obj = None
        lidar_obj = None
        if "camera" in modalities and needs_camera_stage1:
            cam_obj = _validate_stage1_cache(args.camera_stage1, expected_samples=expected_samples, label="camera")
        if "lidar" in modalities and needs_lidar_stage1:
            lidar_obj = _validate_stage1_cache(args.lidar_stage1, expected_samples=expected_samples, label="lidar")
        if not bool(args.skip_stage1_semantic_check):
            if cam_obj is not None:
                _validate_stage1_semantics(
                    cam_obj,
                    label="camera",
                    samples=int(args.stage1_semantic_samples),
                    min_valid_samples=int(args.stage1_semantic_min_valid),
                )
            if lidar_obj is not None:
                _validate_stage1_semantics(
                    lidar_obj,
                    label="lidar",
                    samples=int(args.stage1_semantic_samples),
                    min_valid_samples=int(args.stage1_semantic_min_valid),
                )

        # For pose-noise robustness, pose_override=zero cancels the noise sweep. Require an explicit override.
        if "lidar" in modalities and _pose_override_is_zero(args.lidar_model) and not args.allow_pose_override:
            raise SystemExit(
                "[PRECHECK] lidar model has pose_override.enabled=true,mode=zero; "
                "this cancels pose-noise sweeps and makes baseline curves flat. "
                "Use a non-noextr model dir OR pass --allow-pose-override for an explicit no-extr suite."
            )

        if bool(getattr(args, "require_clean_git", False)):
            main_dirty = _git_is_dirty(ROOT)
            heal_dirty = _git_is_dirty(ROOT / HEAL)
            if main_dirty is True or heal_dirty is True:
                raise SystemExit(
                    "[PRECHECK] git worktree is dirty (main or HEAL). Commit/stash changes before running canonical benchmarks, "
                    "or remove --require-clean-git."
                )

    write_config_snapshot(out_dir, args, noise_list, rot_list)

    done_from_state = set()
    if not args.force_rerun:
        done_from_state = collect_done_from_state(out_dir / "run_state.jsonl")

    # reuse logs if provided
    done = {}
    if args.reuse_log_dir and args.reuse_log_dir.exists():
        # copy legacy logs into new log dir for traceability
        for path in args.reuse_log_dir.glob("*.log"):
            dest = LOG_DIR / path.name
            if not dest.exists():
                shutil.copy2(path, dest)
        done = collect_done_keys(LOG_DIR)

    in_progress = load_in_progress(out_dir / "run_state.jsonl")
    # If the task has already succeeded at least once, treat it as done even if
    # later runs were interrupted and left a dangling start without a matching end.
    in_progress = set(in_progress) - set(done_from_state)

    tasks = build_tasks(
        run_id=args.run_id,
        noise_list=noise_list,
        rot_list=rot_list,
        dropout_prob=args.dropout,
        camera_model=args.camera_model,
        lidar_model=args.lidar_model,
        camera_stage1=args.camera_stage1,
        lidar_stage1=args.lidar_stage1,
        num_workers=args.num_workers,
        include_dropout=not args.no_dropout,
        python_bin=args.python_bin,
        v2xregpp_config=args.v2xregpp_config,
        log_dir=LOG_DIR,
        solver_backend=args.solver_backend,
        runtime_mode=args.runtime_mode,
        pose_source=args.pose_source,
        comm_range_gating=args.comm_range_gating,
        comm_range_override=int(args.comm_range_override),
        pose_compare_distance_threshold=float(args.pose_compare_distance_threshold),
        pose_current_precision_threshold=float(args.pose_current_precision_threshold),
        pose_min_precision_improvement=float(args.pose_min_precision_improvement),
        pose_min_matched_improvement=int(args.pose_min_matched_improvement),
        max_eval_samples=args.max_eval_samples if int(args.max_eval_samples) > 0 else None,
        deterministic_strict=bool(getattr(args, "deterministic_strict", False)),
        online_gpu_stage1_solver=bool(getattr(args, "online_gpu_stage1_solver", False)),
        online_skip_pairwise_rebuild=bool(getattr(args, "online_skip_pairwise_rebuild", False)),
        lidar_reg_cache_dir=args.lidar_reg_cache_dir,
        require_lidar_reg_cache=bool(args.require_lidar_reg_cache),
        methods=methods,
        include_baseline=include_baseline,
        include_oracle=include_oracle,
        include_single=include_single,
        modalities=modalities,
        sweeps=sweeps,
    )

    done_keys = set(done.keys()) | set(done_from_state)
    pending = [t for t in tasks if t.key not in done_keys and t.key not in in_progress]
    scope_keys = {t.key for t in tasks}

    summary = {
        "total_tasks": len(tasks),
        "done_from_reuse": len(done),
        "done_from_state_total": len(done_from_state),
        "done_from_state_in_scope": len(set(done_from_state) & scope_keys),
        "done_total_in_scope": len(done_keys & scope_keys),
        "in_progress": len(in_progress),
        "pending": len(pending),
        "scope_tasks": len(scope_keys),
    }
    (out_dir / "task_summary.json").write_text(json.dumps(summary, indent=2))

    if args.dry_run:
        for t in pending:
            print(t.key, "->", t.log_path)
        print(json.dumps(summary, indent=2))
        return

    schedule_tasks(pending, gpus=gpus, max_per_gpu=args.max_per_gpu, out_dir=out_dir, log_mode=args.log_mode)

    # Exit non-zero if any in-scope task is missing or has a non-zero final code.
    # This makes Slurm dependency chains reliable (afterok should not trigger on partial/failed runs).
    final_codes = collect_final_codes(out_dir / "run_state.jsonl")
    missing = sorted(scope_keys - set(final_codes.keys()))
    failed = sorted([k for k, c in final_codes.items() if k in scope_keys and int(c) != 0])
    final_summary = dict(summary)
    final_summary.update(
        {
            "final_done_tasks": len([k for k, c in final_codes.items() if k in scope_keys and int(c) == 0]),
            "final_failed_tasks": len(failed),
            "final_missing_tasks": len(missing),
        }
    )
    (out_dir / "task_summary_final.json").write_text(json.dumps(final_summary, indent=2))
    if missing or failed:
        raise SystemExit(
            f"[FAIL] Run incomplete: missing={len(missing)} failed={len(failed)}. "
            f"See {out_dir/'run_state.jsonl'} and {out_dir/'task_summary_final.json'}."
        )


if __name__ == "__main__":
    main()
