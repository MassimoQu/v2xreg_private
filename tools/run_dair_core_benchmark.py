#!/usr/bin/env python3
"""
Run DAIR-V2X "core" benchmark curves (noise 0..10) in a unified, fair setting.

This is the DAIR counterpart of tools/run_v2v4real_core_benchmark.py and follows the
same contract:
  - Same checkpoint/model_dir, stage1_result, noise schedule, online semantics.
  - Fast + robust: tolerate partial failures, resume-friendly, high utilization via
    --max-per-gpu and --split-noise.
  - Produce evidence artifacts: per-modality manifest/results/summary + plots.

Notes / gotchas (why this exists):
  - Historical DAIR sweeps used inference_w_noise.py defaults (offline_map) and did
    not freeze comm-range gating semantics, which can confound baseline vs pose-correction.
  - This runner pins solver_backend=online_box and freezes comm-range gating semantics
    (default: noisy; override via --comm-range-gating), matching OPV2V/V2V4Real core runs.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import subprocess
import threading
import time
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
HEAL = ROOT / "HEAL"
INFER = HEAL / "opencood" / "tools" / "inference_w_noise.py"

DEFAULT_CAMERA_MODEL_DIR = "opencood/logs/HeterBaseline_DAIR_camera_v2xvit_2023_09_09_11_27_38"
DEFAULT_LIDAR_MODEL_DIR = "opencood/logs/HeterBaseline_DAIR_lidar_v2xvit_2023_09_09_11_19_26"

DEFAULT_CAMERA_STAGE1 = "data/DAIR-V2X/detected/camera_v2xvit_stage1/stage1_boxes.json"
# This cache may not exist in all checkouts; export it from the lidar V2XViT checkpoint if missing.
DEFAULT_LIDAR_STAGE1 = "data/DAIR-V2X/detected/lidar_v2xvit_stage1_percav/test/stage1_boxes.json"

DEFAULT_V2XREGPP_CONFIG = "configs/dair/midfusion/pipeline_midfusion_detection_occ.yaml"


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _parse_list(s: str) -> list[str]:
    return [x.strip() for x in str(s).split(",") if x.strip()]


def _parse_floats(s: str) -> list[float]:
    out = []
    for tok in _parse_list(s):
        try:
            out.append(float(tok))
        except Exception:
            raise SystemExit(f"Invalid float token in list: {tok!r} from {s!r}")
    return out


def _paired_noise_pairs(pos_std_list: str, rot_std_list: str) -> list[tuple[float, float]]:
    pos = _parse_floats(pos_std_list)
    rot = _parse_floats(rot_std_list)
    if not pos:
        pos = [0.0]
    if not rot:
        rot = [0.0]
    if len(pos) == 1 and len(rot) > 1:
        pos = pos * len(rot)
    if len(rot) == 1 and len(pos) > 1:
        rot = rot * len(pos)
    if len(pos) != len(rot):
        raise SystemExit(
            "pos_std_list and rot_std_list length mismatch (paired sweep required): "
            f"len(pos)={len(pos)} len(rot)={len(rot)}"
        )
    return [(float(p), float(r)) for p, r in zip(pos, rot)]


def _resolve_heal_path(path_str: str) -> Path:
    p = Path(path_str)
    if p.is_absolute():
        return p
    return (ROOT / p).resolve()


def _preflight_model_config(
    *,
    model_dir: Path,
    comm_range: int,
    allow_comm_range_mismatch: bool,
    allow_pose_override: bool,
    log_path: Path,
) -> None:
    """
    Same guardrails as V2V4Real runner:
      - comm_range override mismatch vs checkpoint config.yaml
      - pose_override.enabled=true in checkpoint config
    """
    cfg = model_dir / "config.yaml"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write("\n" + "=" * 80 + "\n")
        f.write("time: {}\n".format(_now()))
        f.write("model_dir: {}\n".format(model_dir))
        f.write("config: {}\n".format(cfg))
        if not cfg.exists():
            f.write("[WARN] missing config.yaml (skip model preflight)\n")
            return

        text = cfg.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"(?m)^comm_range:\\s*([0-9]+)\\s*$", text)
        if m:
            train_cr = int(m.group(1))
            f.write("train_comm_range: {}\n".format(train_cr))
            f.write("override_comm_range: {}\n".format(int(comm_range)))
            if int(train_cr) != int(comm_range) and not bool(allow_comm_range_mismatch):
                raise SystemExit(
                    "[PRECHECK] comm_range mismatch for this checkpoint: "
                    f"train={train_cr} override={comm_range}. "
                    "Pass --allow-comm-range-mismatch to acknowledge and proceed."
                )
        else:
            f.write("[WARN] could not parse comm_range from config.yaml (no gate enforced)\n")

        pose_override_enabled = False
        if re.search(r"(?m)^pose_override\\s*:\\s*\\{.*enabled\\s*:\\s*true", text):
            pose_override_enabled = True
        if re.search(r"(?m)^pose_override\\s*:\\s*$", text) and re.search(
            r"(?m)^\\s+enabled\\s*:\\s*true\\s*$", text
        ):
            pose_override_enabled = True
        if pose_override_enabled:
            f.write("[WARN] pose_override.enabled=true detected in config.yaml\n")
            if not bool(allow_pose_override):
                raise SystemExit(
                    "[PRECHECK] pose_override.enabled=true cancels the noise/extrinsics sweep axis for core benchmarks. "
                    "Disable it in the checkpoint config or pass --allow-pose-override for an explicit no-extr suite."
                )


def _yaml_complete(path: Path, expected_len: int) -> bool:
    if not path.exists():
        return False
    try:
        obj = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore")) or {}
    except Exception:
        return False
    for key in ("ap30", "ap50", "ap70"):
        arr = obj.get(key) or []
        if not isinstance(arr, list) or len(arr) != int(expected_len):
            return False
    return True


def _mean(vals):
    buf = [float(v) for v in vals if v is not None]
    return float(sum(buf) / len(buf)) if buf else None


def _summarize_yaml(path: Path) -> dict:
    obj = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore")) or {}
    ap30 = obj.get("ap30") or []
    ap50 = obj.get("ap50") or []
    ap70 = obj.get("ap70") or []

    timing_stats = obj.get("timing_stats") or []
    infer_fps = []
    infer_sec = []
    pose_provider_applied = []
    pose_provider_total_sec = []
    pose_match_sec = []
    for ts in timing_stats:
        if not isinstance(ts, dict):
            continue
        if ts.get("infer_fps") is not None:
            infer_fps.append(float(ts["infer_fps"]))
        if ts.get("infer_sec") is not None:
            infer_sec.append(float(ts["infer_sec"]))
        pt = ts.get("pose_timing")
        if isinstance(pt, dict):
            if pt.get("pose_provider_applied_count") is not None:
                pose_provider_applied.append(float(pt["pose_provider_applied_count"]))
            if pt.get("pose_provider_total_sec") is not None:
                pose_provider_total_sec.append(float(pt["pose_provider_total_sec"]))
            if pt.get("match_sec") is not None:
                pose_match_sec.append(float(pt["match_sec"]))

    rel_stats = obj.get("rel_error_stats") or []
    rel_trans_mean = []
    rel_yaw_mean = []
    success_at_2m = []
    for rs in rel_stats:
        if not isinstance(rs, dict):
            continue
        t = (rs.get("rel_trans_m") or {}).get("mean")
        y = (rs.get("rel_yaw_deg") or {}).get("mean")
        if t is not None:
            rel_trans_mean.append(float(t))
        if y is not None:
            rel_yaw_mean.append(float(y))
        s2 = (rs.get("rel_success_at_m") or {}).get("2")
        if s2 is not None:
            success_at_2m.append(float(s2))

    return {
        "yaml": str(path),
        "mean_ap30": _mean(ap30),
        "mean_ap50": _mean(ap50),
        "mean_ap70": _mean(ap70),
        "mean_rel_trans_m": _mean(rel_trans_mean),
        "mean_rel_yaw_deg": _mean(rel_yaw_mean),
        "success_at_2m": _mean(success_at_2m),
        "mean_infer_fps": _mean(infer_fps),
        "mean_infer_sec": _mean(infer_sec),
        "mean_pose_provider_applied_count": _mean(pose_provider_applied),
        "mean_pose_provider_total_sec": _mean(pose_provider_total_sec),
        "mean_pose_match_sec": _mean(pose_match_sec),
    }


def _run_preflight(*, python_bin: Path, stage1_path: Path, semantic_samples: int, log_path: Path) -> None:
    """
    Fail-fast gate:
      - stage1 structural sanity
      - stage1 semantic frame convention (per-CAV local frame expected)
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    head200 = stage1_path.with_name("stage1_boxes_head200.json")
    stage1_for_struct = head200 if (stage1_path.name == "stage1_boxes.json" and head200.exists()) else stage1_path

    cmds = [
        [
            str(python_bin),
            str(ROOT / "tools" / "validate_stage1_cache.py"),
            "--stage1",
            str(stage1_for_struct),
        ],
        [
            str(python_bin),
            str(ROOT / "tools" / "validate_stage1_semantics.py"),
            "--stage1",
            str(stage1_path),
            "--prefer-head200",
            "--num-samples",
            str(int(semantic_samples)),
        ],
    ]

    with log_path.open("a", encoding="utf-8") as f:
        f.write("\n" + "=" * 80 + "\n")
        f.write("time: {}\n".format(_now()))
        f.write("stage1: {}\n".format(stage1_path))
        f.write("head200: {}\n".format(head200 if head200.exists() else "NA"))
        for cmd in cmds:
            f.write("- cmd: {}\n".format(" ".join(cmd)))
        f.write("=" * 80 + "\n\n")
        f.flush()
        for cmd in cmds:
            proc = subprocess.run(cmd, cwd=str(ROOT), stdout=f, stderr=subprocess.STDOUT)
            f.write("\nexit_code={}\n\n".format(proc.returncode))
            f.flush()
            if proc.returncode != 0:
                raise SystemExit(
                    "[PRECHECK] stage1 preflight failed (rc={}). See: {}".format(proc.returncode, log_path)
                )


def _run_job(*, python_bin: Path, job: dict, gpu: int, log_path: Path) -> Path:
    expected_len = int(job.get("expected_len") or len(_parse_list(job["pos_std_list"])))
    yaml_path = Path(job["yaml_path"])
    if _yaml_complete(yaml_path, expected_len):
        return yaml_path

    # Slurm (and some launchers) remap CUDA_VISIBLE_DEVICES to a slot/UUID list.
    # Our runners accept `--gpus` as *slot indices* by default (0..N-1). Map them
    # to the parent-visible device string to avoid escaping the allocation.
    parent_visible = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    parent_list = [v.strip() for v in str(parent_visible).split(",") if v.strip()]
    if parent_list and 0 <= int(gpu) < len(parent_list):
        cuda_visible = parent_list[int(gpu)]
    elif parent_list and str(gpu) in parent_list:
        # Allow passing physical IDs explicitly when they match the parent allocation.
        cuda_visible = str(gpu)
    else:
        cuda_visible = str(gpu)

    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = cuda_visible
    env["PYTHONUNBUFFERED"] = "1"
    env["OPENCOOD_VOXEL_GPU"] = "1"
    env.setdefault("OMP_NUM_THREADS", "1")
    env.setdefault("MKL_NUM_THREADS", "1")
    env.setdefault("OPENBLAS_NUM_THREADS", "1")
    env.setdefault("NUMEXPR_NUM_THREADS", "1")
    env["PYTHONPATH"] = str(HEAL)

    # inference_w_noise.py expects `--model_dir` to exist as a filesystem path.
    # Many of our default model_dir strings are HEAL-relative (opencood/logs/..).
    model_dir_raw = str(job["model_dir"])
    model_dir_p = Path(model_dir_raw)
    if model_dir_p.is_absolute():
        model_dir_arg = str(model_dir_p)
    else:
        heal_candidate = (HEAL / model_dir_p).resolve()
        root_candidate = (ROOT / model_dir_p).resolve()
        if heal_candidate.exists():
            model_dir_arg = str(heal_candidate)
        elif root_candidate.exists():
            model_dir_arg = str(root_candidate)
        else:
            model_dir_arg = model_dir_raw

    cmd = [
        str(python_bin),
        str(INFER),
        "--model_dir",
        model_dir_arg,
        "--fusion_method",
        "intermediate",
        "--comm-range-override",
        str(int(job["comm_range"])),
        "--pos-std-list",
        job["pos_std_list"],
        "--rot-std-list",
        job["rot_std_list"],
        "--sweep-mode",
        "paired",
        "--noise-target",
        job["noise_target"],
        "--num-workers",
        "0",
        "--save_vis_interval",
        "100000000",
        "--log-interval",
        "400",
        "--note",
        job["note"],
        "--pose-correction",
        job["pose_correction"],
        "--pose-device",
        "cuda",
        "--pose-timing",
        "--comm-range-gating",
        job["comm_range_gating"],
        "--solver-backend",
        "online_box",
        "--runtime-mode",
        "register_and_fuse",
        "--pose-source",
        "noisy_input",
    ]
    if job.get("max_eval_samples", 0) and int(job["max_eval_samples"]) > 0:
        cmd.extend(["--max-eval-samples", str(int(job["max_eval_samples"]))])
    if job.get("needs_stage1"):
        cmd.extend(["--stage1-result", job["stage1_result"]])

    cmd.extend(job.get("extra_args") or [])

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as f:
        f.write("time: {}\n".format(_now()))
        f.write("gpu: {}\n".format(gpu))
        f.write("cmd: {}\n\n".format(" ".join(cmd)))
        f.flush()
        proc = subprocess.run(cmd, cwd=str(HEAL), env=env, stdout=f, stderr=subprocess.STDOUT)
        f.write("\nexit_code={}\n".format(proc.returncode))
    if proc.returncode != 0:
        raise RuntimeError("job failed rc={} log={}".format(proc.returncode, log_path))
    if not yaml_path.exists():
        raise RuntimeError("missing yaml: {}".format(yaml_path))
    return yaml_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Run DAIR-V2X core benchmark curves in parallel across GPUs.")
    ap.add_argument("--tag", type=str, default=time.strftime("%Y%m%d_%H%M%S"))
    ap.add_argument("--gpus", type=str, default="0,1,2,3,4,5,6,7,8,9")
    ap.add_argument("--modalities", type=str, default="camera,lidar")
    ap.add_argument(
        "--max-per-gpu",
        type=int,
        default=2,
        help="Max concurrent subprocesses per GPU. Increase to raise CPU/GPU utilization.",
    )
    ap.add_argument(
        "--split-noise",
        action="store_true",
        help="Run each (pos_std, rot_std) pair as an independent job and merge YAMLs per method.",
    )
    ap.add_argument(
        "--suite",
        type=str,
        default="core",
        choices=["core", "core_plus_stable"],
        help="core: initfree only; core_plus_stable: also run *_stable variants.",
    )
    ap.add_argument("--python-bin", type=Path, default=ROOT / ".micromamba" / "envs" / "py39" / "bin" / "python")
    ap.add_argument("--camera-model-dir", type=str, default=DEFAULT_CAMERA_MODEL_DIR)
    ap.add_argument("--lidar-model-dir", type=str, default=DEFAULT_LIDAR_MODEL_DIR)
    ap.add_argument("--camera-stage1", type=str, default=DEFAULT_CAMERA_STAGE1)
    ap.add_argument("--lidar-stage1", type=str, default=DEFAULT_LIDAR_STAGE1)
    ap.add_argument("--v2xregpp-config", type=str, default=DEFAULT_V2XREGPP_CONFIG)
    ap.add_argument("--skip-preflight", action="store_true")
    ap.add_argument("--preflight-semantic-samples", type=int, default=20)
    ap.add_argument(
        "--allow-comm-range-mismatch",
        action="store_true",
        help="Allow comm_range override to differ from the checkpoint's config.yaml (use only for explicit ablations).",
    )
    ap.add_argument(
        "--allow-pose-override",
        action="store_true",
        help="Allow pose_override.enabled=true in model config (use only for explicit no-extr suites).",
    )
    ap.add_argument("--comm-range", type=int, default=100)
    ap.add_argument(
        "--comm-range-gating",
        type=str,
        default="noisy",
        choices=["clean", "noisy"],
        help="Freeze comm-range pruning semantics (clean=agent set fixed; noisy=system effect).",
    )
    ap.add_argument("--noise-target", type=str, default="non-ego")
    ap.add_argument("--pos-std-list", type=str, default="0,1,2,3,4,5,6,7,8,9,10")
    ap.add_argument("--rot-std-list", type=str, default="0,1,2,3,4,5,6,7,8,9,10")
    ap.add_argument("--max-eval-samples", type=int, default=0, help="0=full; >0 for smoke.")
    ap.add_argument("--skip-single", action="store_true")
    # Compare-current (best-state) gate pins. These MUST be explicit to make the
    # run reproducible and to avoid noise=0 bad-apply.
    ap.add_argument("--pose-compare-distance-threshold", type=float, default=3.0)
    ap.add_argument("--pose-current-precision-threshold", type=float, default=1.8)
    ap.add_argument("--pose-min-precision-improvement", type=float, default=0.0)
    ap.add_argument("--pose-min-matched-improvement", type=int, default=0)
    args = ap.parse_args()

    gpus = [int(x) for x in _parse_list(args.gpus)]
    if not gpus:
        raise SystemExit("--gpus must be non-empty")
    if int(args.max_per_gpu) <= 0:
        raise SystemExit("--max-per-gpu must be >= 1")

    modalities = [m.strip().lower() for m in _parse_list(args.modalities)]
    if not modalities:
        raise SystemExit("--modalities must be non-empty")
    for m in modalities:
        if m not in {"camera", "lidar"}:
            raise SystemExit(f"Unsupported modality: {m!r} (expected camera,lidar)")

    noise_pairs = _paired_noise_pairs(args.pos_std_list, args.rot_std_list)

    out_dir = ROOT / "outputs" / ("dair_core_" + args.tag)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Per-modality runs (each has its own manifest + plots dir).
    mod_cfg = {
        "camera": {"model_dir": args.camera_model_dir, "stage1": args.camera_stage1},
        "lidar": {"model_dir": args.lidar_model_dir, "stage1": args.lidar_stage1},
    }

    for m in modalities:
        stage1_abs = _resolve_heal_path(mod_cfg[m]["stage1"])
        if not stage1_abs.exists():
            raise SystemExit(
                f"stage1_result not found for {m}: {stage1_abs}\n"
                f"Tip: export per-CAV stage1 via HEAL/opencood/tools/export_stage1_boxes_per_cav.py"
            )

    # Preflight (model config + stage1 semantics).
    if not bool(args.skip_preflight):
        for m in modalities:
            run_dir = out_dir / m
            preflight_log = run_dir / "preflight.log"
            model_abs = (HEAL / str(mod_cfg[m]["model_dir"])).resolve()
            if not model_abs.exists():
                raise SystemExit(f"model_dir not found for {m}: {model_abs}")
            _preflight_model_config(
                model_dir=model_abs,
                comm_range=int(args.comm_range),
                allow_comm_range_mismatch=bool(args.allow_comm_range_mismatch),
                allow_pose_override=bool(args.allow_pose_override),
                log_path=preflight_log,
            )

            stage1_abs = _resolve_heal_path(mod_cfg[m]["stage1"])
            _run_preflight(
                python_bin=args.python_bin,
                stage1_path=stage1_abs,
                semantic_samples=int(args.preflight_semantic_samples),
                log_path=preflight_log,
            )

    compare_pins = [
        "--pose-compare-current",
        "--pose-compare-distance-threshold",
        str(float(args.pose_compare_distance_threshold)),
        "--pose-current-precision-threshold",
        str(float(args.pose_current_precision_threshold)),
        "--pose-min-precision-improvement",
        str(float(args.pose_min_precision_improvement)),
        "--pose-min-matched-improvement",
        str(int(args.pose_min_matched_improvement)),
    ]

    # Build tasks.
    core_jobs = [
        ("none", "none", False, []),  # baseline
        ("none", "single", False, ["--force-ego-input-only"]),
        ("oracle_gt", "oracle", False, []),
        ("v2xregpp_initfree", "v2xregpp_initfree", True, compare_pins),
        ("freealign_paper", "freealign_paper", True, compare_pins),
        ("vips_initfree", "vips_initfree", True, compare_pins),
        ("cbm_initfree", "cbm_initfree", True, compare_pins),
    ]
    if bool(args.skip_single):
        core_jobs = [j for j in core_jobs if j[1] != "single"]
    if str(args.suite) == "core_plus_stable":
        core_jobs.extend(
            [
                ("v2xregpp_stable", "v2xregpp_stable", True, []),
                ("freealign_paper_stable", "freealign_paper_stable", True, []),
                ("vips_stable", "vips_stable", True, []),
                ("cbm_stable", "cbm_stable", True, []),
            ]
        )

    all_jobs = []
    manifests = {}
    for m in modalities:
        run_dir = out_dir / m
        log_dir = run_dir / "logs"
        run_dir.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)

        model_dir = str(mod_cfg[m]["model_dir"])
        stage1 = str(mod_cfg[m]["stage1"])

        method_specs = []
        jobs = []
        for pose_correction, name, needs_stage1, extra_args in core_jobs:
            comm_range = int(args.comm_range)
            pos_std_list = str(args.pos_std_list)
            rot_std_list = str(args.rot_std_list)
            expected_len = len(noise_pairs)
            if str(name) == "single":
                pos_std_list = "0"
                rot_std_list = "0"
                expected_len = 1

            base_note = "_dair_core_{}_comm{}_{}_{}".format(args.tag, int(comm_range), m, name)
            if str(name) == "single":
                base_note = base_note + "_ego_only"

            final_yaml_path = HEAL / model_dir / ("AP030507_{}{}.yaml".format(pose_correction, base_note))
            # v2xregpp needs a config path.
            extra_args_full = list(extra_args or [])
            if pose_correction.startswith("v2xregpp"):
                extra_args_full.extend(["--v2xregpp-config", str(args.v2xregpp_config)])

            spec = {
                "name": name,
                "pose_correction": pose_correction,
                "needs_stage1": bool(needs_stage1) and pose_correction != "none",
                "extra_args": list(extra_args_full),
                "base_note": base_note,
                "final_yaml_path": str(final_yaml_path),
                "comm_range": int(comm_range),
                "comm_range_gating": str(args.comm_range_gating),
                "pos_std_list": pos_std_list,
                "rot_std_list": rot_std_list,
                "expected_len": int(expected_len),
            }
            method_specs.append(spec)
            if _yaml_complete(final_yaml_path, expected_len=int(expected_len)):
                continue

            if (not bool(args.split_noise)) or int(expected_len) == 1:
                jobs.append(
                    {
                        "task_name": f"{m}_{name}",
                        "pose_correction": pose_correction,
                        "model_dir": model_dir,
                        "stage1_result": stage1,
                        "needs_stage1": bool(needs_stage1) and pose_correction != "none",
                        "comm_range": int(comm_range),
                        "comm_range_gating": str(args.comm_range_gating),
                        "noise_target": str(args.noise_target),
                        "pos_std_list": pos_std_list,
                        "rot_std_list": rot_std_list,
                        "max_eval_samples": int(args.max_eval_samples),
                        "note": base_note,
                        "yaml_path": str(final_yaml_path),
                        "expected_len": int(expected_len),
                        "extra_args": list(extra_args_full),
                        "log_dir": str(log_dir),
                    }
                )
            else:
                for idx, (pos_std, rot_std) in enumerate(noise_pairs):
                    note = "{}_noise{}".format(base_note, idx)
                    partial_yaml_path = HEAL / model_dir / ("AP030507_{}{}.yaml".format(pose_correction, note))
                    if _yaml_complete(partial_yaml_path, expected_len=1):
                        continue
                    jobs.append(
                        {
                            "task_name": f"{m}_{name}_noise{idx}",
                            "pose_correction": pose_correction,
                            "model_dir": model_dir,
                            "stage1_result": stage1,
                            "needs_stage1": bool(needs_stage1) and pose_correction != "none",
                            "comm_range": int(comm_range),
                            "comm_range_gating": str(args.comm_range_gating),
                            "noise_target": str(args.noise_target),
                            "pos_std_list": str(float(pos_std)),
                            "rot_std_list": str(float(rot_std)),
                            "max_eval_samples": int(args.max_eval_samples),
                            "note": note,
                            "yaml_path": str(partial_yaml_path),
                            "expected_len": 1,
                            "extra_args": list(extra_args_full),
                            "merge_into": str(final_yaml_path),
                            "noise_idx": int(idx),
                            "log_dir": str(log_dir),
                        }
                    )

        (run_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "tag": args.tag,
                    "dataset": "DAIR-V2X",
                    "modality": m,
                    "suite": str(args.suite),
                    "split_noise": bool(args.split_noise),
                    "max_per_gpu": int(args.max_per_gpu),
                    "fusion_method": "intermediate",
                    "solver_backend": "online_box",
                    "runtime_mode": "register_and_fuse",
                    "pose_source": "noisy_input",
                    "compare_current_pins": {
                        "pose_compare_distance_threshold": float(args.pose_compare_distance_threshold),
                        "pose_current_precision_threshold": float(args.pose_current_precision_threshold),
                        "pose_min_precision_improvement": float(args.pose_min_precision_improvement),
                        "pose_min_matched_improvement": int(args.pose_min_matched_improvement),
                    },
                    "model_dir": model_dir,
                    "stage1_result": stage1,
                    "comm_range": int(args.comm_range),
                    "comm_range_gating": str(args.comm_range_gating),
                    "noise_target": str(args.noise_target),
                    "pos_std_list": str(args.pos_std_list),
                    "rot_std_list": str(args.rot_std_list),
                    "max_eval_samples": int(args.max_eval_samples),
                    "noise_pairs": noise_pairs,
                    "method_specs": method_specs,
                    "jobs": jobs,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        manifests[m] = {"run_dir": run_dir, "method_specs": method_specs, "jobs": jobs, "noise_pairs": noise_pairs}
        all_jobs.extend(jobs)

    # Schedule all jobs across GPUs.
    q = queue.Queue()
    for j in all_jobs:
        q.put(j)

    errors = []
    lock = threading.Lock()

    def worker(gpu: int):
        while True:
            try:
                job = q.get_nowait()
            except queue.Empty:
                return
            task_name = job.get("task_name") or "job"
            log_dir = Path(job.get("log_dir") or (out_dir / "logs"))
            log_path = log_dir / (str(task_name) + ".log")
            try:
                _run_job(python_bin=args.python_bin, job=job, gpu=gpu, log_path=log_path)
            except Exception as e:
                with lock:
                    errors.append({"job": task_name, "error": str(e)})
            finally:
                q.task_done()

    threads = []
    for gpu in gpus:
        for _slot in range(int(args.max_per_gpu)):
            threads.append(threading.Thread(target=worker, args=(gpu,), daemon=True))
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Merge partial YAMLs.
    merge_errors = []
    if bool(args.split_noise):
        for m in modalities:
            spec_list = manifests[m]["method_specs"]
            for spec in spec_list:
                final_yaml_path = Path(spec["final_yaml_path"])
                expected_len = int(spec.get("expected_len") or len(noise_pairs))
                if expected_len <= 1:
                    continue
                # Resume safety: if the final YAML is already complete, do not
                # overwrite it by re-merging partial shards.
                if _yaml_complete(final_yaml_path, expected_len=expected_len):
                    continue
                pose_correction = str(spec["pose_correction"])
                base_note = str(spec["base_note"])
                partial_paths = []
                for idx in range(expected_len):
                    note = "{}_noise{}".format(base_note, idx)
                    partial_yaml_path = (
                        HEAL
                        / str(mod_cfg[m]["model_dir"])
                        / ("AP030507_{}{}.yaml".format(pose_correction, note))
                    )
                    partial_paths.append(partial_yaml_path)
                if not all(_yaml_complete(p, expected_len=1) for p in partial_paths):
                    merge_errors.append(
                        {
                            "modality": m,
                            "method": spec["name"],
                            "error": "missing_or_incomplete_partial_yaml(s) -> cannot merge",
                            "final_yaml": str(final_yaml_path),
                        }
                    )
                    continue

                merged = {
                    "pos_std_list": [float(p) for p, _ in noise_pairs[:expected_len]],
                    "rot_std_list": [float(r) for _, r in noise_pairs[:expected_len]],
                    "noise_target": str(args.noise_target),
                    "pose_correction": str(pose_correction),
                    "ap30": [],
                    "ap50": [],
                    "ap70": [],
                    "timing_stats": [],
                    "rel_error_stats": [],
                }
                for p in partial_paths:
                    obj = yaml.safe_load(p.read_text(encoding="utf-8", errors="ignore")) or {}
                    for key in ("ap30", "ap50", "ap70"):
                        merged[key].extend(list(obj.get(key) or []))
                    merged["timing_stats"].extend(list(obj.get("timing_stats") or []))
                    merged["rel_error_stats"].extend(list(obj.get("rel_error_stats") or []))

                try:
                    final_yaml_path.write_text(yaml.safe_dump(merged, sort_keys=False), encoding="utf-8")
                except Exception as e:
                    merge_errors.append(
                        {
                            "modality": m,
                            "method": spec["name"],
                            "error": "write_final_yaml_failed: {}".format(str(e)),
                            "final_yaml": str(final_yaml_path),
                        }
                    )

    # Summarize + plot per modality.
    for m in modalities:
        run_dir = manifests[m]["run_dir"]
        method_specs = manifests[m]["method_specs"]

        results = []
        for spec in method_specs:
            final_yaml_path = Path(spec["final_yaml_path"])
            if final_yaml_path.exists():
                try:
                    summary = _summarize_yaml(final_yaml_path)
                except Exception:
                    summary = {"yaml": str(final_yaml_path)}
            else:
                summary = {"yaml": str(final_yaml_path)}
            results.append({**spec, **summary})

        results_path = run_dir / "results.jsonl"
        with results_path.open("w", encoding="utf-8") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

        summary_md = run_dir / "summary.md"
        lines = []
        lines.append("# DAIR-V2X Core Benchmark Summary")
        lines.append("")
        lines.append("- tag: `{}`".format(args.tag))
        lines.append("- modality: `{}`".format(m))
        lines.append("- run_dir: `{}`".format(run_dir))
        lines.append("- model_dir: `{}` (relative to HEAL)".format(mod_cfg[m]["model_dir"]))
        lines.append("- stage1_result: `{}`".format(mod_cfg[m]["stage1"]))
        lines.append("- comm_range: `{}`".format(args.comm_range))
        lines.append("- comm_range_gating: `{}`".format(args.comm_range_gating))
        lines.append("- solver_backend: `online_box`")
        lines.append("- runtime_mode: `register_and_fuse`")
        lines.append("- pose_source: `noisy_input`")
        lines.append("- noise_target: `{}`".format(args.noise_target))
        lines.append("- pos_std_list: `{}`".format(args.pos_std_list))
        lines.append("- rot_std_list: `{}`".format(args.rot_std_list))
        lines.append("- suite: `{}`".format(args.suite))
        lines.append("- split_noise: `{}`".format(bool(args.split_noise)))
        lines.append("- max_per_gpu: `{}`".format(int(args.max_per_gpu)))
        lines.append("- max_eval_samples: `{}`".format(int(args.max_eval_samples)))
        lines.append("")
        lines.append("## Results (mean AP50)")
        lines.append("")

        def _display_name(spec_name: str, pose_correction: str) -> str:
            n = str(spec_name).strip().lower()
            pc = str(pose_correction).strip()
            if n == "none":
                return "baseline"
            if n == "single":
                return "single_ego_only"
            if n == "oracle":
                return pc or "oracle_gt"
            return spec_name

        rows = sorted(
            [
                (
                    _display_name(str(r.get("name") or ""), str(r.get("pose_correction") or "")),
                    r.get("mean_ap50"),
                    r.get("mean_rel_trans_m"),
                    r.get("mean_rel_yaw_deg"),
                    r.get("mean_pose_provider_applied_count"),
                )
                for r in results
            ],
            key=lambda x: (x[0] or ""),
        )
        lines.append("| method | mean_ap50 | mean_rel_trans_m | mean_rel_yaw_deg | mean_pose_provider_applied_count |")
        lines.append("|---|---:|---:|---:|---:|")
        for name, ap50, t, y, applied in rows:
            lines.append(
                "| {} | {} | {} | {} | {} |".format(
                    name,
                    "NA" if ap50 is None else "{:.6f}".format(float(ap50)),
                    "NA" if t is None else "{:.3f}".format(float(t)),
                    "NA" if y is None else "{:.3f}".format(float(y)),
                    "NA" if applied is None else "{:.1f}".format(float(applied)),
                )
            )
        if merge_errors:
            lines.append("")
            lines.append("## Merge Failures")
            lines.append("")
            for e in merge_errors:
                if e.get("modality") == m:
                    lines.append("- {}: {} ({})".format(e.get("method"), e.get("error"), e.get("final_yaml")))
        summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # Plots + long-format JSON (same style as OPV2V/V2V4Real).
        try:
            subprocess.run(
                [
                    str(args.python_bin),
                    "-u",
                    str(ROOT / "tools" / "summarize_v2v4real_core_from_yaml.py"),
                    "--run-dir",
                    str(run_dir),
                    "--dataset",
                    "DAIR-V2X",
                    "--modality",
                    m,
                    "--clean-plot-dir",
                ],
                cwd=str(ROOT),
                check=True,
            )
        except Exception as e:
            errors.append({"job": f"{m}_summarize", "error": str(e)})

    final_errors = []
    if merge_errors:
        final_errors.append("merge_failures={}".format(len(merge_errors)))
    if errors:
        final_errors.append("job_failures={}".format(len(errors)))
    if final_errors:
        raise SystemExit("DAIR core benchmark finished with failures: " + "; ".join(final_errors))


if __name__ == "__main__":
    main()
