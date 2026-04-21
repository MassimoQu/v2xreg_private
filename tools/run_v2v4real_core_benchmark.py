#!/usr/bin/env python3
"""
Run V2V4Real "core" benchmark curves (default: comm=70, noise 0..10).

Key constraints (match user's ask):
- Fair comparison: identical checkpoint/model_dir, stage1_result, noise schedule, online semantics.
- Fast + robust: tolerate failures and keep launching other tasks; resume-friendly.
- High utilization: optionally oversubscribe each GPU with multiple independent jobs.

Why utilization can look low:
- AP evaluation uses Shapely polygon IoU on CPU, which is single-threaded per process.
  One process per GPU often underutilizes both CPU and GPU. The most reliable speedup is
  to run multiple independent jobs per GPU (max-per-gpu) and/or split the noise sweep.
"""

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


DEFAULT_MODEL_DIR = (
    "opencood/logs/v2v4real_pastat_noise1_multiego_worldlabels_initfcooper_ddp_g0123_2026_01_17_10_06_25"
)
# Canonical V2V4Real stage1 must be per-CAV local-frame boxes. The older "80boxes" export
# is in a common frame and will fail the semantic preflight gate.
DEFAULT_STAGE1 = "opencood/logs/v2v4real_stage1_pointpillar_from_pastat_bestval17_percav/test/stage1_boxes.json"


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _parse_list(s: str) -> list[str]:
    return [x.strip() for x in str(s).split(",") if x.strip()]


def _resolve_heal_path(path_str: str) -> Path:
    p = Path(path_str)
    if p.is_absolute():
        return p
    return (HEAL / p).resolve()


def _preflight_model_config(
    *,
    model_dir: Path,
    comm_range: int,
    allow_comm_range_mismatch: bool,
    allow_pose_override: bool,
    log_path: Path,
) -> None:
    """
    Guardrails to prevent silent "wrong setting" runs.

    We avoid parsing YAML (some configs contain python tags); instead we use a
    simple text scan for the fields we care about.
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


def _run_preflight(*, python_bin: Path, stage1_path: Path, semantic_samples: int, log_path: Path) -> None:
    """
    Fail-fast gate for V2V4Real:
      - stage1 structural sanity (on head200 if present)
      - stage1 semantic frame convention (per-CAV expected)
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
            "paired sweep requires pos-std-list and rot-std-list to have equal length (or one of them length=1). "
            f"Got pos={pos_std_list!r} rot={rot_std_list!r}"
        )
    return list(zip(pos, rot))


def _yaml_complete(path: Path, expected_len: int) -> bool:
    if not path.exists():
        return False
    try:
        obj = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return False
    if not isinstance(obj, dict):
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
    # V2V4Real defaults are HEAL-relative (opencood/logs/..).
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
    if job.get("force_pose_confidence") is not None:
        cmd.extend(["--force-pose-confidence", str(float(job["force_pose_confidence"]))])
    if job.get("max_eval_samples", 0) and int(job["max_eval_samples"]) > 0:
        cmd.extend(["--max-eval-samples", str(int(job["max_eval_samples"]))])
    if job.get("eval_sample_start", 0) and int(job["eval_sample_start"]) > 0:
        cmd.extend(["--eval-sample-start", str(int(job["eval_sample_start"]))])

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
    ap = argparse.ArgumentParser(description="Run V2V4Real core benchmark curves in parallel across GPUs.")
    ap.add_argument("--tag", type=str, default=time.strftime("%Y%m%d_%H%M%S"))
    ap.add_argument("--gpus", type=str, default="0,1,2,3,4,5,6,7,8,9")
    ap.add_argument(
        "--max-per-gpu",
        type=int,
        default=1,
        help="Max concurrent subprocesses per GPU. Increase to raise CPU/GPU utilization.",
    )
    ap.add_argument(
        "--split-noise",
        action="store_true",
        help=(
            "Run each (pos_std, rot_std) pair as an independent job and merge YAMLs per method. "
            "Recommended together with --max-per-gpu>1 for speed."
        ),
    )
    ap.add_argument(
        "--suite",
        type=str,
        default="core",
        choices=["core", "core_plus_stable"],
        help=(
            "core: initfree only (none/oracle/v2xregpp/freealign/vips/cbm). "
            "core_plus_stable: also run *_stable variants."
        ),
    )
    ap.add_argument("--python-bin", type=Path, default=ROOT / ".micromamba" / "envs" / "py39" / "bin" / "python")
    ap.add_argument("--model-dir", type=str, default=DEFAULT_MODEL_DIR, help="Path relative to HEAL/ (recommended).")
    ap.add_argument("--stage1-result", type=str, default=DEFAULT_STAGE1, help="Path relative to HEAL/ (recommended).")
    ap.add_argument("--skip-preflight", action="store_true", help="Skip stage1 semantic checks (NOT recommended).")
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
    ap.add_argument("--comm-range", type=int, default=70)
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
    ap.add_argument(
        "--eval-sample-start",
        type=int,
        default=0,
        help=(
            "Skip the first N dataset samples before counting --max-eval-samples (debug only). "
            "Useful when the dataset head is degenerate under comm-range pruning."
        ),
    )
    ap.add_argument(
        "--skip-single",
        action="store_true",
        help="Skip single-agent ego-only baseline job (same comm_range/labels as cooperative runs).",
    )
    ap.add_argument(
        "--force-pose-confidence",
        type=float,
        default=None,
        help="Optionally force a constant pose_confidence during eval to disable clean-pose-derived leakage.",
    )
    ap.add_argument(
        "--pose-selection-policy",
        type=str,
        default="compare_current_proxy",
        choices=["solver_only", "compare_current_proxy", "choose_better_pose_error"],
        help="How init/current pose and solver output are reconciled for initfree core methods.",
    )
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

    out_dir = ROOT / "outputs" / ("v2v4real_core_" + args.tag)
    log_dir = out_dir / "logs"
    out_dir.mkdir(parents=True, exist_ok=True)

    model_abs = _resolve_heal_path(args.model_dir)
    if not model_abs.exists():
        raise SystemExit(f"model_dir not found: {model_abs}")
    if not bool(args.skip_preflight):
        _preflight_model_config(
            model_dir=model_abs,
            comm_range=int(args.comm_range),
            allow_comm_range_mismatch=bool(args.allow_comm_range_mismatch),
            allow_pose_override=bool(args.allow_pose_override),
            log_path=out_dir / "preflight.log",
        )

    stage1_abs = _resolve_heal_path(args.stage1_result)
    if not stage1_abs.exists():
        raise SystemExit(f"stage1_result not found: {stage1_abs}")
    if not bool(args.skip_preflight):
        _run_preflight(
            python_bin=args.python_bin,
            stage1_path=stage1_abs,
            semantic_samples=int(args.preflight_semantic_samples),
            log_path=out_dir / "preflight.log",
        )

    # Suite job set.
    # initfree jobs include pose-compare-current to reduce bad-apply risk.
    selection_pins = ["--pose-selection-policy", str(args.pose_selection_policy)]
    if str(args.pose_selection_policy) == "compare_current_proxy":
        selection_pins.extend(
            [
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
        )
    core_jobs = [
        ("none", "none", False, []),
        # Single-agent baseline under the SAME comm_range (same GT difficulty), but
        # force the forward pass to use only ego inputs (no comm).
        ("none", "single", False, ["--force-ego-input-only"]),
        # Oracle upper bound: directly use clean poses (GT) to override noisy inputs.
        ("oracle_gt", "oracle", False, []),
        ("v2xregpp_initfree", "v2xregpp_initfree", True, selection_pins),
        ("freealign_paper", "freealign_paper", True, selection_pins),
        ("vips_initfree", "vips_initfree", True, selection_pins),
        ("cbm_initfree", "cbm_initfree", True, selection_pins),
    ]
    if bool(args.skip_single):
        core_jobs = [job for job in core_jobs if job[1] != "single"]
    if str(args.suite) == "core_plus_stable":
        core_jobs.extend(
            [
                ("v2xregpp_stable", "v2xregpp_stable", True, []),
                ("freealign_paper_stable", "freealign_paper_stable", True, []),
                ("vips_stable", "vips_stable", True, []),
                ("cbm_stable", "cbm_stable", True, []),
            ]
        )

    noise_pairs = _paired_noise_pairs(args.pos_std_list, args.rot_std_list)

    # Build job list (either full sweep per method, or split per noise pair).
    jobs = []
    method_specs = []
    for pose_correction, name, needs_stage1, extra_args in core_jobs:
        comm_range = int(args.comm_range)
        pos_std_list = str(args.pos_std_list)
        rot_std_list = str(args.rot_std_list)
        expected_len = len(noise_pairs)
        if str(name) == "single":
            # Single-agent baseline: keep comm_range so GT difficulty matches cooperative runs,
            # but only evaluate one point (noise doesn't apply when forward uses only ego).
            pos_std_list = "0"
            rot_std_list = "0"
            expected_len = 1

        base_note = "_v2v4real_core_{}_comm{}_{}".format(args.tag, int(comm_range), name)
        if str(name) == "single":
            base_note = base_note + "_ego_only"
        final_yaml_path = HEAL / args.model_dir / ("AP030507_{}{}.yaml".format(pose_correction, base_note))
        method_specs.append(
            {
                "name": name,
                "pose_correction": pose_correction,
                "needs_stage1": bool(needs_stage1) and pose_correction != "none",
                "extra_args": list(extra_args or []),
                "base_note": base_note,
                "final_yaml_path": str(final_yaml_path),
                "comm_range": int(comm_range),
                "comm_range_gating": str(args.comm_range_gating),
                "pos_std_list": pos_std_list,
                "rot_std_list": rot_std_list,
                "expected_len": int(expected_len),
                "force_pose_confidence": None if args.force_pose_confidence is None else float(args.force_pose_confidence),
            }
        )
        if _yaml_complete(final_yaml_path, expected_len=int(expected_len)):
            # Already complete -> skip generating sub-jobs.
            continue
        if (not bool(args.split_noise)) or int(expected_len) == 1:
            jobs.append(
                {
                    "task_name": name,
                    "pose_correction": pose_correction,
                    "model_dir": args.model_dir,
                    "stage1_result": args.stage1_result,
                    "needs_stage1": bool(needs_stage1) and pose_correction != "none",
                    "comm_range": int(comm_range),
                    "comm_range_gating": str(args.comm_range_gating),
                    "noise_target": str(args.noise_target),
                    "pos_std_list": pos_std_list,
                    "rot_std_list": rot_std_list,
                    "max_eval_samples": int(args.max_eval_samples),
                    "eval_sample_start": int(args.eval_sample_start),
                    "force_pose_confidence": None if args.force_pose_confidence is None else float(args.force_pose_confidence),
                    "note": base_note,
                    "yaml_path": str(final_yaml_path),
                    "expected_len": int(expected_len),
                    "extra_args": list(extra_args or []),
                }
            )
        else:
            # One job per noise pair; merge later.
            for idx, (pos_std, rot_std) in enumerate(noise_pairs):
                note = "{}_noise{}".format(base_note, idx)
                partial_yaml_path = HEAL / args.model_dir / ("AP030507_{}{}.yaml".format(pose_correction, note))
                if _yaml_complete(partial_yaml_path, expected_len=1):
                    continue
                jobs.append(
                    {
                        "task_name": "{}_noise{}".format(name, idx),
                        "pose_correction": pose_correction,
                        "model_dir": args.model_dir,
                        "stage1_result": args.stage1_result,
                        "needs_stage1": bool(needs_stage1) and pose_correction != "none",
                        "comm_range": int(comm_range),
                        "comm_range_gating": str(args.comm_range_gating),
                        "noise_target": str(args.noise_target),
                        "pos_std_list": str(float(pos_std)),
                        "rot_std_list": str(float(rot_std)),
                        "max_eval_samples": int(args.max_eval_samples),
                        "eval_sample_start": int(args.eval_sample_start),
                        "force_pose_confidence": None if args.force_pose_confidence is None else float(args.force_pose_confidence),
                        "note": note,
                        "yaml_path": str(partial_yaml_path),
                        "expected_len": 1,
                        "extra_args": list(extra_args or []),
                        "merge_into": str(final_yaml_path),
                        "noise_idx": int(idx),
                    }
                )

    # Save a manifest for traceability.
    (out_dir / "manifest.json").write_text(
        json.dumps(
            {
                "tag": args.tag,
                "dataset": "V2V4Real",
                "suite": str(args.suite),
                "split_noise": bool(args.split_noise),
                "max_per_gpu": int(args.max_per_gpu),
                "fusion_method": "intermediate",
                "solver_backend": "online_box",
                "runtime_mode": "register_and_fuse",
                "pose_source": "noisy_input",
                "pose_selection_policy": str(args.pose_selection_policy),
                "compare_current_pins": (
                    {
                        "pose_compare_distance_threshold": float(args.pose_compare_distance_threshold),
                        "pose_current_precision_threshold": float(args.pose_current_precision_threshold),
                        "pose_min_precision_improvement": float(args.pose_min_precision_improvement),
                        "pose_min_matched_improvement": int(args.pose_min_matched_improvement),
                    }
                    if str(args.pose_selection_policy) == "compare_current_proxy"
                    else None
                ),
                "model_dir": str(args.model_dir),
                "stage1_result": str(args.stage1_result),
                "comm_range": int(args.comm_range),
                "comm_range_gating": str(args.comm_range_gating),
                "force_pose_confidence": None if args.force_pose_confidence is None else float(args.force_pose_confidence),
                "noise_target": str(args.noise_target),
                "pos_std_list": str(args.pos_std_list),
                "rot_std_list": str(args.rot_std_list),
                "max_eval_samples": int(args.max_eval_samples),
                "eval_sample_start": int(args.eval_sample_start),
                "noise_pairs": noise_pairs,
                "method_specs": method_specs,
                "jobs": jobs,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    q = queue.Queue()
    for j in jobs:
        q.put(j)

    errors = []
    lock = threading.Lock()

    def worker(gpu: int):
        while True:
            try:
                job = q.get_nowait()
            except queue.Empty:
                return
            try:
                task_name = job.get("task_name") or job.get("name") or "job"
                log_path = log_dir / (str(task_name) + ".log")
                yaml_path = _run_job(python_bin=args.python_bin, job=job, gpu=gpu, log_path=log_path)
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

    # Merge partial YAMLs into final YAMLs if requested.
    merge_errors = []
    if bool(args.split_noise):
        for spec in method_specs:
            final_yaml_path = Path(spec["final_yaml_path"])
            expected_len = int(spec.get("expected_len") or len(noise_pairs))
            if expected_len == 1:
                # Single-agent baseline (or any 1-point method) does not participate in split-noise merging.
                continue
            if _yaml_complete(final_yaml_path, expected_len=expected_len):
                continue
            pose_correction = spec["pose_correction"]
            base_note = spec["base_note"]

            partial_paths = []
            for idx in range(expected_len):
                note = "{}_noise{}".format(base_note, idx)
                partial_paths.append(
                    HEAL
                    / args.model_dir
                    / ("AP030507_{}{}.yaml".format(pose_correction, note))
                )
            if not all(_yaml_complete(p, expected_len=1) for p in partial_paths):
                merge_errors.append(
                    {
                        "method": spec["name"],
                        "error": "missing_partial_yaml(s) -> cannot merge",
                        "final_yaml": str(final_yaml_path),
                    }
                )
                continue

            merged = {}
            merged["pos_std_list"] = [float(p) for p, _ in noise_pairs[:expected_len]]
            merged["rot_std_list"] = [float(r) for _, r in noise_pairs[:expected_len]]
            merged["noise_target"] = str(args.noise_target)
            merged["pose_correction"] = str(pose_correction)

            for key in ("ap30", "ap50", "ap70", "timing_stats", "rel_error_stats"):
                merged[key] = []

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
                        "method": spec["name"],
                        "error": "write_final_yaml_failed: {}".format(str(e)),
                        "final_yaml": str(final_yaml_path),
                    }
                )

    # Summarize results (even if some jobs failed/merge failed).
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

    # Write results JSONL for programmatic consumption.
    results_path = out_dir / "results.jsonl"
    with results_path.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    summary_md = out_dir / "summary.md"
    lines = []
    lines.append("# V2V4Real Core Benchmark Summary")
    lines.append("")
    lines.append("- tag: `{}`".format(args.tag))
    lines.append("- out_dir: `{}`".format(out_dir))
    lines.append("- model_dir: `{}` (relative to HEAL)".format(args.model_dir))
    lines.append("- stage1_result: `{}` (relative to HEAL)".format(args.stage1_result))
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
    lines.append("- eval_sample_start: `{}`".format(int(args.eval_sample_start)))
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
            lines.append("- {}: {} ({})".format(e.get("method"), e.get("error"), e.get("final_yaml")))
    if errors:
        lines.append("")
        lines.append("## Failures")
        lines.append("")
        for e in errors:
            lines.append("- {}: {}".format(e.get("job"), e.get("error")))
    summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("out_dir:", out_dir)
    print("results:", results_path)
    print("summary:", summary_md)
    if merge_errors or errors:
        raise SystemExit(
            "V2V4Real core benchmark finished with {} failures (merge_failures={}, job_failures={})".format(
                len(merge_errors) + len(errors), len(merge_errors), len(errors)
            )
        )


if __name__ == "__main__":
    main()
