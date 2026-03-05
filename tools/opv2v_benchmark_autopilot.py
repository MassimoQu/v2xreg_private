#!/usr/bin/env python3
"""
Autopilot for OPV2V benchmark plan-execute.

Goals:
- Keep GPUs busy with low-overhead supervision.
- Automatically recover from common blockers (stage1 cache invalid/missing).
- Gate by evidence before promoting smoke -> full benchmark.
- Produce a final evidence report and summary paths.
"""

import argparse
import json
import os
import subprocess
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PY39 = ROOT / ".micromamba" / "envs" / "py39" / "bin" / "python"


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _run(cmd, *, env=None, cwd=None, check=True, capture=False):
    if capture:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd or ROOT),
            env=env,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if check and proc.returncode != 0:
            raise RuntimeError("Command failed ({}): {}\n{}".format(proc.returncode, " ".join(cmd), proc.stdout[-4000:]))
        return proc
    proc = subprocess.run(cmd, cwd=str(cwd or ROOT), env=env, check=False)
    if check and proc.returncode != 0:
        raise RuntimeError("Command failed ({}): {}".format(proc.returncode, " ".join(cmd)))
    return proc


def _append_log(path, msg):
    line = "[{}] {}\n".format(_now(), msg)
    print(line, end="", flush=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line)


def _validate_stage1(pybin, stage1_path, expected_samples):
    cmd = [
        str(pybin),
        str(ROOT / "tools" / "validate_stage1_cache.py"),
        "--stage1",
        str(stage1_path),
        "--expected-samples",
        str(int(expected_samples)),
        "--require-contiguous-keys",
    ]
    return _run(cmd, check=False, capture=True)


def _build_stage1_parallel(args, log_path):
    _append_log(log_path, "Rebuilding camera stage1 per-CAV in parallel shards...")
    out_dir = Path(args.camera_stage1).parent.parent
    split_name = Path(args.camera_stage1).parent.name
    split_dir = out_dir / split_name
    split_dir.mkdir(parents=True, exist_ok=True)

    num_shards = int(args.stage1_shards)
    shard_gpus = [x.strip() for x in str(args.stage1_shard_gpus).split(",") if x.strip()]
    if not shard_gpus:
        shard_gpus = ["0"]
    procs = []
    for shard in range(num_shards):
        gpu = shard_gpus[shard % len(shard_gpus)]
        env = os.environ.copy()
        # Slurm may remap CUDA_VISIBLE_DEVICES; treat `stage1_shard_gpus` as slot indices by default.
        parent_visible = os.environ.get("CUDA_VISIBLE_DEVICES", "")
        parent_list = [v.strip() for v in str(parent_visible).split(",") if v.strip()]
        cuda_visible = str(gpu)
        try:
            gi = int(str(gpu))
        except Exception:
            gi = None
        if parent_list and gi is not None and 0 <= gi < len(parent_list):
            cuda_visible = parent_list[gi]
        elif parent_list and str(gpu) in parent_list:
            cuda_visible = str(gpu)
        env["CUDA_VISIBLE_DEVICES"] = cuda_visible
        env["PYTHONPATH"] = str(ROOT / "HEAL")
        env["PYTHONUNBUFFERED"] = "1"
        cmd = [
            str(args.python_bin),
            "-u",
            str(ROOT / "HEAL" / "opencood" / "tools" / "export_stage1_boxes_per_cav.py"),
            "--hypes_yaml",
            str(Path(args.camera_model) / "config.yaml"),
            "--stage1_checkpoint",
            str(args.camera_ckpt),
            "--output_dir",
            str(out_dir),
            "--split",
            split_name,
            "--shard-index",
            str(shard),
            "--num-shards",
            str(num_shards),
            "--log-interval",
            "20",
        ]
        shard_log = split_dir / "stage1_export_shard{:02d}.log".format(shard)
        lf = shard_log.open("w", encoding="utf-8")
        _append_log(log_path, "Launch shard {}/{} on GPU {} -> {}".format(shard, num_shards, gpu, shard_log))
        proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env, stdout=lf, stderr=subprocess.STDOUT)
        procs.append((proc, lf, shard, shard_log))

    failed = []
    while procs:
        alive = []
        for proc, lf, shard, shard_log in procs:
            rc = proc.poll()
            if rc is None:
                alive.append((proc, lf, shard, shard_log))
                continue
            lf.close()
            if rc != 0:
                failed.append((shard, shard_log, rc))
                _append_log(log_path, "Shard {} failed (rc={}): {}".format(shard, rc, shard_log))
            else:
                _append_log(log_path, "Shard {} done: {}".format(shard, shard_log))
        procs = alive
        if procs:
            time.sleep(15)

    if failed:
        raise RuntimeError("stage1 shard export failed: {}".format(failed[:3]))

    merge_cmd = [
        str(args.python_bin),
        str(ROOT / "tools" / "merge_stage1_shards.py"),
        "--shard-dir",
        str(split_dir),
        "--num-shards",
        str(num_shards),
        "--out",
        str(args.camera_stage1),
        "--expected-samples",
        str(int(args.expected_samples)),
        "--require-contiguous-keys",
    ]
    _run(merge_cmd, check=True)
    _append_log(log_path, "Merged camera stage1 -> {}".format(args.camera_stage1))


def _ensure_stage1(args, log_path):
    cam = _validate_stage1(args.python_bin, args.camera_stage1, args.expected_samples)
    if cam.returncode != 0:
        _append_log(log_path, "Camera stage1 invalid, will rebuild. validator output tail:\n{}".format(cam.stdout[-1200:]))
        _build_stage1_parallel(args, log_path)
        cam = _validate_stage1(args.python_bin, args.camera_stage1, args.expected_samples)
        if cam.returncode != 0:
            raise RuntimeError("Camera stage1 still invalid after rebuild:\n{}".format(cam.stdout[-2000:]))
    else:
        _append_log(log_path, "Camera stage1 OK: {}".format(args.camera_stage1))

    lidar = _validate_stage1(args.python_bin, args.lidar_stage1, args.expected_samples)
    if lidar.returncode != 0:
        raise RuntimeError("LiDAR stage1 invalid:\n{}".format(lidar.stdout[-2000:]))
    _append_log(log_path, "LiDAR stage1 OK: {}".format(args.lidar_stage1))


def _count_inference_procs():
    cmd = [
        "bash",
        "-lc",
        "ps -ef | rg -i 'inference_w_noise.py' | rg -v 'rg -i' | wc -l | tr -d ' '",
    ]
    proc = _run(cmd, check=False, capture=True)
    if proc.returncode != 0:
        return 0
    out = (proc.stdout or "").strip()
    try:
        return int(out)
    except Exception:
        return 0


def _run_state_stats(run_dir):
    state_path = run_dir / "run_state.jsonl"
    starts = 0
    ends = 0
    last_ts = 0.0
    done = set()
    if not state_path.exists():
        return {"starts": 0, "ends": 0, "done": 0, "last_ts": 0.0}
    for line in state_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        t = ev.get("time")
        if isinstance(t, (int, float)) and float(t) > last_ts:
            last_ts = float(t)
        if ev.get("event") == "start":
            starts += 1
        if ev.get("event") == "end":
            ends += 1
            if ev.get("code") == 0 and isinstance(ev.get("task"), list):
                done.add(tuple(ev["task"]))
    return {"starts": starts, "ends": ends, "done": len(done), "last_ts": last_ts}


def _launch_scheduler(args, run_id, *, smoke):
    run_dir = ROOT / "outputs" / ("full_bench_" + run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    scheduler_log = run_dir / "scheduler.log"
    cmd = [
        str(args.python_bin),
        str(ROOT / "tools" / "run_opv2v_fullbench_fast.py"),
        "--run-id",
        run_id,
        "--gpus",
        args.gpus,
        "--max-per-gpu",
        str(int(args.max_per_gpu)),
        "--num-workers",
        str(int(args.num_workers)),
        "--camera-model",
        str(args.camera_model),
        "--lidar-model",
        str(args.lidar_model),
        "--camera-stage1",
        str(args.camera_stage1),
        "--lidar-stage1",
        str(args.lidar_stage1),
        "--solver-backend",
        "online_box",
        "--runtime-mode",
        "register_and_fuse",
        "--pose-source",
        "noisy_input",
        "--comm-range-gating",
        str(getattr(args, "comm_range_gating", "noisy")),
        "--comm-range-override",
        str(int(getattr(args, "comm_range_override", 70))),
        "--pose-compare-distance-threshold",
        str(float(getattr(args, "pose_compare_distance_threshold", 3.0))),
        "--pose-current-precision-threshold",
        str(float(getattr(args, "pose_current_precision_threshold", 1.8))),
        "--pose-min-precision-improvement",
        str(float(getattr(args, "pose_min_precision_improvement", 0.0))),
        "--pose-min-matched-improvement",
        str(int(getattr(args, "pose_min_matched_improvement", 0))),
        "--log-mode",
        "append",
    ]
    if smoke:
        cmd.extend(["--noise-list", args.smoke_noise_list, "--rot-list", args.smoke_noise_list])
        cmd.extend(["--sweeps", "noise10"])
        cmd.extend(["--max-eval-samples", str(int(args.smoke_max_eval_samples))])
    else:
        cmd.extend(["--noise-list", args.full_noise_list, "--rot-list", args.full_noise_list])
        cmd.extend(["--sweeps", "noise10,drop20"])
        if int(args.full_max_eval_samples) > 0:
            cmd.extend(["--max-eval-samples", str(int(args.full_max_eval_samples))])

    lf = scheduler_log.open("a", encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "HEAL")
    proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env, stdout=lf, stderr=subprocess.STDOUT)
    return proc, lf, run_dir, scheduler_log


def _wait_scheduler(args, proc, log_fh, run_dir, log_path):
    last_done = -1
    stall_count = 0
    while True:
        rc = proc.poll()
        stats = _run_state_stats(run_dir)
        if stats["done"] > last_done:
            last_done = stats["done"]
            stall_count = 0
            _append_log(
                log_path,
                "progress run={} done={} starts={} ends={} inf_procs={}".format(
                    run_dir.name, stats["done"], stats["starts"], stats["ends"], _count_inference_procs()
                ),
            )
        else:
            stall_count += 1

        if rc is not None:
            log_fh.close()
            if rc != 0:
                raise RuntimeError("scheduler exited non-zero rc={} run_dir={}".format(rc, run_dir))
            _append_log(log_path, "scheduler completed: {}".format(run_dir))
            return

        # no progress for long time and no worker process -> assume stale scheduler, restart outside.
        if stall_count >= int(args.stall_polls) and _count_inference_procs() == 0:
            proc.terminate()
            time.sleep(3)
            if proc.poll() is None:
                proc.kill()
            log_fh.close()
            raise RuntimeError("scheduler stalled with no inference workers (run={})".format(run_dir))

        time.sleep(int(args.poll_seconds))


def _summarize_and_gate(args, run_id, *, smoke, log_path):
    run_dir = ROOT / "outputs" / ("full_bench_" + run_id)
    cmd = [
        str(args.python_bin),
        str(ROOT / "tools" / "summarize_opv2v_fullbench_from_yaml.py"),
        "--run-dir",
        str(run_dir),
        "--clean-plot-dir",
        "--strict-applied-gate",
    ]
    proc = _run(cmd, check=False, capture=True)
    if proc.returncode != 0:
        tail = (proc.stdout or "")[-3000:]
        raise RuntimeError("summarize failed rc={} run_id={} tail:\n{}".format(proc.returncode, run_id, tail))
    _append_log(log_path, "summary generated: {}".format(run_dir / "results_ap50_from_yaml.json"))
    data = json.loads((run_dir / "results_ap50_from_yaml.json").read_text(encoding="utf-8"))
    entries = data.get("entries") or []
    index = {}
    for e in entries:
        key = (e.get("modality"), e.get("sweep"), e.get("method"), e.get("strategy"), str(e.get("noise")))
        index[key] = e

    # Derive noise endpoints from the config snapshot recorded by the scheduler.
    low_noise = "1.0"
    high_noise = "10.0"
    cfg_path = run_dir / "config_snapshot.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            axis = cfg.get("noise_list") or []
            if isinstance(axis, list) and axis:
                vals = []
                for x in axis:
                    try:
                        vals.append(float(x))
                    except Exception:
                        continue
                if vals:
                    low_noise = "{:.1f}".format(min(vals))
                    high_noise = "{:.1f}".format(max(vals))
        except Exception:
            pass

    # Shape gates: strict enough to avoid "flat garbage", but tolerant to small-sample variance.
    problems = []
    flat_eps = 0.003 if smoke else 0.005
    for modality in ("camera", "lidar"):
        b1 = index.get((modality, "noise10", "baseline", "bounds", low_noise))
        bmax = index.get((modality, "noise10", "baseline", "bounds", high_noise))
        # Prefer explicit oracle token; fall back to legacy "oracle" for older runs.
        o1 = index.get((modality, "noise10", "oracle_gt", "bounds", low_noise)) or index.get(
            (modality, "noise10", "oracle", "bounds", low_noise)
        )
        if not b1 or not bmax or not o1:
            problems.append("{} noise10 key points missing (low={}, high={})".format(modality, low_noise, high_noise))
            continue
        ap1 = float(b1.get("ap50") or 0.0)
        apmax = float(bmax.get("ap50") or 0.0)
        oap = float(o1.get("ap50") or 0.0)
        if ap1 < 1e-5:
            problems.append("{} baseline AP@1 too close to zero ({:.3e})".format(modality, ap1))
        delta = ap1 - apmax
        if abs(delta) < float(flat_eps):
            problems.append(
                "{} baseline too flat vs noise (AP@1 {:.4f}, AP@max {:.4f}, |Δ|<{:.3f})".format(
                    modality, ap1, apmax, float(flat_eps)
                )
            )
        if delta < -0.01:
            problems.append(
                "{} baseline increases with noise (AP@1 {:.4f} -> AP@max {:.4f})".format(modality, ap1, apmax)
            )
        if oap < ap1 - 1e-3:
            problems.append(
                "{} oracle below baseline at n={} (oracle {:.4f}, baseline {:.4f})".format(modality, low_noise, oap, ap1)
            )

    if problems:
        raise RuntimeError("shape gate failed: " + "; ".join(problems[:6]))

    _append_log(log_path, "quality gates passed for run_id={}".format(run_id))
    return run_dir


def _write_report(report_path, payload):
    lines = []
    lines.append("# OPV2V Autopilot Report")
    lines.append("")
    lines.append("- generated_at: {}".format(_now()))
    for k in sorted(payload.keys()):
        lines.append("- {}: {}".format(k, payload[k]))
    lines.append("")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Autopilot OPV2V benchmark with self-healing gates.")
    ap.add_argument("--python-bin", type=Path, default=PY39)
    ap.add_argument("--camera-model", type=Path, default=ROOT / "HEAL" / "opencood" / "logs" / "opv2v_camera_v2xvit_full_prope")
    ap.add_argument("--lidar-model", type=Path, default=ROOT / "HEAL" / "opencood" / "logs" / "freealign_repro_opv2v_baseline")
    ap.add_argument(
        "--camera-ckpt",
        type=Path,
        default=ROOT / "HEAL" / "opencood" / "logs" / "opv2v_camera_v2xvit_full_prope" / "net_epoch_bestval_at21.pth",
        help="Checkpoint for exporting camera stage1 cache.",
    )
    ap.add_argument(
        "--camera-stage1",
        type=Path,
        default=ROOT / "data" / "OPV2V" / "detected" / "opv2v_camera_v2xvit_stage1_percav" / "test" / "stage1_boxes.json",
    )
    ap.add_argument(
        "--lidar-stage1",
        type=Path,
        default=ROOT / "data" / "OPV2V" / "detected" / "opv2v_lidar_v2xvit_stage1" / "test" / "stage1_boxes.json",
    )
    ap.add_argument("--expected-samples", type=int, default=2170)
    ap.add_argument("--gpus", type=str, default="0,1,2,3,4,5,6,7,8,9")
    ap.add_argument("--max-per-gpu", type=int, default=3)
    ap.add_argument("--num-workers", type=int, default=0)
    ap.add_argument("--smoke-noise-list", type=str, default="1,5")
    ap.add_argument("--smoke-max-eval-samples", type=int, default=100)
    ap.add_argument("--full-noise-list", type=str, default="0,1,2,3,4,5,6,7,8,9,10")
    ap.add_argument("--full-max-eval-samples", type=int, default=0)
    ap.add_argument(
        "--skip-full",
        action="store_true",
        help="Stop after the smoke run passes gates (useful for fast diagnostics / evidence collection).",
    )
    ap.add_argument(
        "--comm-range-gating",
        type=str,
        default="noisy",
        choices=["auto", "clean", "noisy"],
        help="Freeze comm-range pruning semantics for online runtime (recommended: noisy).",
    )
    ap.add_argument("--comm-range-override", type=int, default=70)
    ap.add_argument("--pose-compare-distance-threshold", type=float, default=3.0)
    ap.add_argument("--pose-current-precision-threshold", type=float, default=1.8)
    ap.add_argument("--pose-min-precision-improvement", type=float, default=0.0)
    ap.add_argument("--pose-min-matched-improvement", type=int, default=0)
    ap.add_argument("--max-smoke-retries", type=int, default=2)
    ap.add_argument("--max-full-retries", type=int, default=2)
    ap.add_argument("--poll-seconds", type=int, default=120)
    ap.add_argument("--stall-polls", type=int, default=8)
    ap.add_argument("--stage1-shards", type=int, default=0, help="0=auto (one shard per GPU in --gpus).")
    ap.add_argument("--stage1-shard-gpus", type=str, default="", help="Empty=use --gpus.")
    ap.add_argument("--tag", type=str, default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    args = ap.parse_args()

    # Fill auto defaults.
    all_gpus = [x.strip() for x in str(args.gpus).split(",") if x.strip()]
    if int(args.stage1_shards) <= 0:
        args.stage1_shards = max(1, len(all_gpus))
    if not str(args.stage1_shard_gpus).strip():
        args.stage1_shard_gpus = args.gpus

    auto_dir = ROOT / "outputs" / ("opv2v_autopilot_" + args.tag)
    auto_dir.mkdir(parents=True, exist_ok=True)
    log_path = auto_dir / "autopilot.log"
    report_path = ROOT / "docs" / "operations" / ("opv2v_autopilot_report_" + args.tag + ".md")

    payload = {"tag": args.tag, "status": "running"}
    try:
        _append_log(log_path, "autopilot start tag={}".format(args.tag))
        _ensure_stage1(args, log_path)

        smoke_ok = False
        smoke_run_id = None
        for attempt in range(1, int(args.max_smoke_retries) + 1):
            smoke_run_id = "opv2v_autopilot_smoke_{}_a{}".format(args.tag, attempt)
            _append_log(log_path, "start smoke attempt {} run_id={}".format(attempt, smoke_run_id))
            try:
                proc, lf, run_dir, scheduler_log = _launch_scheduler(args, smoke_run_id, smoke=True)
                _append_log(log_path, "scheduler log: {}".format(scheduler_log))
                _wait_scheduler(args, proc, lf, run_dir, log_path)
                _summarize_and_gate(args, smoke_run_id, smoke=True, log_path=log_path)
                smoke_ok = True
                break
            except Exception as e:
                _append_log(log_path, "smoke attempt {} failed: {}".format(attempt, e))
                if attempt < int(args.max_smoke_retries):
                    _ensure_stage1(args, log_path)
                else:
                    raise

        if not smoke_ok:
            raise RuntimeError("smoke never passed")

        if bool(args.skip_full):
            # Smoke-only mode: treat the smoke run as the final run for reporting/auditing.
            full_run_id = smoke_run_id
            full_ok = True
            _append_log(log_path, "skip-full enabled; using smoke_run_id as final_run_id={}".format(full_run_id))
        else:
            full_run_id = None
            full_ok = False
            for attempt in range(1, int(args.max_full_retries) + 1):
                full_run_id = "opv2v_autopilot_full_{}_a{}".format(args.tag, attempt)
                _append_log(log_path, "start full attempt {} run_id={}".format(attempt, full_run_id))
                try:
                    proc, lf, run_dir, scheduler_log = _launch_scheduler(args, full_run_id, smoke=False)
                    _append_log(log_path, "scheduler log: {}".format(scheduler_log))
                    _wait_scheduler(args, proc, lf, run_dir, log_path)
                    _summarize_and_gate(args, full_run_id, smoke=False, log_path=log_path)
                    full_ok = True
                    break
                except Exception as e:
                    _append_log(log_path, "full attempt {} failed: {}".format(attempt, e))
                    if attempt < int(args.max_full_retries):
                        _ensure_stage1(args, log_path)
                    else:
                        raise

            if not full_ok:
                raise RuntimeError("full benchmark never passed gates")

        # Evidence report for final run.
        final_run_dir = ROOT / "outputs" / ("full_bench_" + full_run_id)
        audit_cmd = [
            str(args.python_bin),
            str(ROOT / "tools" / "audit_opv2v_fullbench_run.py"),
            "--run-dir",
            str(final_run_dir),
            "--out",
            str(ROOT / "docs" / "operations" / ("opv2v_fullbench_evidence_autopilot_" + args.tag + ".md")),
            "--max-log-examples",
            "2",
        ]
        proc = _run(audit_cmd, check=False, capture=True)
        if proc.returncode != 0:
            raise RuntimeError("audit failed rc={} tail:\n{}".format(proc.returncode, (proc.stdout or "")[-3000:]))
        _append_log(log_path, "audit report generated for {}".format(final_run_dir))

        payload.update(
            {
                "status": "success",
                "skip_full": bool(args.skip_full),
                "smoke_run_id": smoke_run_id,
                "full_run_id": full_run_id,
                "final_run_dir": final_run_dir,
                "final_results_json": final_run_dir / "results_ap50_from_yaml.json",
                "final_plots_dir": final_run_dir / "plots_yaml",
                "autopilot_log": log_path,
            }
        )
    except Exception as e:
        payload.update({"status": "failed", "error": str(e), "autopilot_log": log_path})
        _append_log(log_path, "autopilot failed: {}".format(e))
        _write_report(report_path, payload)
        raise

    _write_report(report_path, payload)
    _append_log(log_path, "autopilot done; report={}".format(report_path))


if __name__ == "__main__":
    main()
