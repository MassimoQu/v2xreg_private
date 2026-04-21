#!/usr/bin/env python3
"""
Core benchmark pipeline launcher (DAIR reuse + OPV2V autopilot + V2V4Real core sweep).

User goals:
- Use all 10 GPUs as much as possible.
- Minimize failures (smoke + gates + retries for OPV2V).
- Fault tolerant: if OPV2V fails, still run V2V4Real; if V2V4Real has partial failures,
  still emit artifacts and exit non-zero at the very end.
"""

import argparse
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]
PY39 = ROOT / ".micromamba" / "envs" / "py39" / "bin" / "python"
V2X = ROOT / ".micromamba" / "envs" / "v2x" / "bin" / "python"


def _run(cmd: list[str], *, cwd: Path, env: dict, log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write("\n" + "=" * 80 + "\n")
        f.write("time: {}\n".format(time.strftime("%Y-%m-%d %H:%M:%S")))
        f.write("cmd: {}\n".format(" ".join(cmd)))
        f.write("=" * 80 + "\n")
        f.flush()
        proc = subprocess.run(cmd, cwd=str(cwd), env=env, stdout=f, stderr=subprocess.STDOUT)
        f.write("\nexit_code={}\n".format(proc.returncode))
        f.flush()
        return int(proc.returncode)


def _parse_full_run_id(report_path: Path) -> Optional[str]:
    if not report_path.exists():
        return None
    text = report_path.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"^- full_run_id: (.+?)\\s*$", text, flags=re.M)
    if not m:
        return None
    return m.group(1).strip()


def main() -> None:
    ap = argparse.ArgumentParser(description="Run core benchmark pipeline (DAIR + OPV2V + V2V4Real).")
    ap.add_argument("--tag", type=str, default=time.strftime("%Y%m%d_%H%M%S"))
    ap.add_argument("--gpus", type=str, default="0,1,2,3,4,5,6,7,8,9")
    ap.add_argument(
        "--comm-range-gating",
        type=str,
        default="noisy",
        choices=["clean", "noisy"],
        help="Freeze comm-range pruning semantics for online benchmarks (clean=diagnostic, noisy=system).",
    )
    # Defaults tuned for higher CPU/GPU utilization on 10x3090 without being too aggressive.
    ap.add_argument("--dair-modalities", type=str, default="camera,lidar")
    ap.add_argument("--dair-comm-range", type=int, default=100)
    ap.add_argument("--dair-max-per-gpu", type=int, default=2)
    ap.add_argument("--dair-split-noise", action="store_true")
    ap.add_argument("--dair-suite", type=str, default="core", choices=["core", "core_plus_stable"])
    ap.add_argument("--dair-allow-comm-range-mismatch", action="store_true")
    ap.add_argument("--dair-allow-pose-override", action="store_true")
    ap.add_argument("--opv2v-max-per-gpu", type=int, default=3)
    ap.add_argument("--v2v4real-max-per-gpu", type=int, default=2)
    ap.add_argument("--v2v4real-comm-range", type=int, default=70)
    ap.add_argument("--v2v4real-split-noise", action="store_true")
    ap.add_argument("--v2v4real-suite", type=str, default="core", choices=["core", "core_plus_stable"])
    ap.add_argument("--v2v4real-allow-comm-range-mismatch", action="store_true")
    ap.add_argument("--v2v4real-allow-pose-override", action="store_true")
    ap.add_argument("--skip-dair", action="store_true")
    ap.add_argument("--skip-opv2v", action="store_true")
    ap.add_argument("--skip-v2v4real", action="store_true")
    args = ap.parse_args()

    tag = str(args.tag)
    out_dir = ROOT / "outputs" / ("core_pipeline_" + tag)
    out_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["OMP_NUM_THREADS"] = env.get("OMP_NUM_THREADS", "1")
    env["MKL_NUM_THREADS"] = env.get("MKL_NUM_THREADS", "1")
    env["OPENBLAS_NUM_THREADS"] = env.get("OPENBLAS_NUM_THREADS", "1")
    env["NUMEXPR_NUM_THREADS"] = env.get("NUMEXPR_NUM_THREADS", "1")

    failures = []

    # 0) DAIR core runner (camera + lidar)
    if not bool(args.skip_dair):
        dair_log = out_dir / "dair_core.log"
        cmd = [
            str(PY39),
            "-u",
            str(ROOT / "tools" / "run_dair_core_benchmark.py"),
            "--tag",
            tag,
            "--gpus",
            str(args.gpus),
            "--max-per-gpu",
            str(int(args.dair_max_per_gpu)),
            "--suite",
            str(args.dair_suite),
            "--modalities",
            str(args.dair_modalities),
            "--comm-range",
            str(int(args.dair_comm_range)),
            "--comm-range-gating",
            str(args.comm_range_gating),
        ]
        if bool(args.dair_allow_comm_range_mismatch):
            cmd.append("--allow-comm-range-mismatch")
        if bool(args.dair_allow_pose_override):
            cmd.append("--allow-pose-override")
        if bool(args.dair_split_noise):
            cmd.append("--split-noise")
        rc = _run(cmd, cwd=ROOT, env=env, log_path=dair_log)
        if rc != 0:
            failures.append("dair_core_failed rc={}".format(rc))

    # 1) OPV2V autopilot (smoke->full with retries)
    full_run_id = None
    if not bool(args.skip_opv2v):
        opv2v_log = out_dir / "opv2v_autopilot.log"
        cmd = [
            str(PY39),
            "-u",
            str(ROOT / "tools" / "opv2v_benchmark_autopilot.py"),
            "--tag",
            tag,
            "--gpus",
            str(args.gpus),
            "--max-per-gpu",
            str(int(args.opv2v_max_per_gpu)),
            "--num-workers",
            "0",
            "--comm-range-gating",
            str(args.comm_range_gating),
        ]
        rc = _run(cmd, cwd=ROOT, env=env, log_path=opv2v_log)
        if rc != 0:
            failures.append("opv2v_autopilot_failed rc={}".format(rc))
        report_path = ROOT / "docs" / "operations" / ("opv2v_autopilot_report_" + tag + ".md")
        full_run_id = _parse_full_run_id(report_path)

        # 1.1) If full run exists, build unified/fullmatrix artifacts under this pipeline dir.
        if full_run_id:
            run_dir = ROOT / "outputs" / ("full_bench_" + full_run_id)
            # fullmatrix
            rc = _run(
                [
                    str(V2X),
                    str(ROOT / "tools" / "build_fullmatrix_benchmark_report.py"),
                    "--opv2v-run-dir",
                    str(run_dir),
                    "--out-dir",
                    str(out_dir / "benchmark_fullmatrix"),
                ],
                cwd=ROOT,
                env=env,
                log_path=out_dir / "build_fullmatrix.log",
            )
            if rc != 0:
                failures.append("build_fullmatrix_failed rc={}".format(rc))
            # unified
            rc = _run(
                [
                    str(V2X),
                    str(ROOT / "tools" / "build_unified_benchmark_report.py"),
                    "--opv2v-run-dir",
                    str(run_dir),
                    "--out-dir",
                    str(out_dir / "benchmark_unified"),
                ],
                cwd=ROOT,
                env=env,
                log_path=out_dir / "build_unified.log",
            )
            if rc != 0:
                failures.append("build_unified_failed rc={}".format(rc))
        else:
            failures.append("opv2v_full_run_id_missing (autopilot likely failed before full)")

    # 2) V2V4Real core sweep (10 jobs -> fill 10 GPUs)
    if not bool(args.skip_v2v4real):
        v2v4_log = out_dir / "v2v4real_core.log"
        cmd = [
            str(PY39),
            "-u",
            str(ROOT / "tools" / "run_v2v4real_core_benchmark.py"),
            "--tag",
            tag,
            "--gpus",
            str(args.gpus),
            "--max-per-gpu",
            str(int(args.v2v4real_max_per_gpu)),
            "--suite",
            str(args.v2v4real_suite),
            "--comm-range",
            str(int(args.v2v4real_comm_range)),
            "--comm-range-gating",
            str(args.comm_range_gating),
        ]
        if bool(args.v2v4real_allow_comm_range_mismatch):
            cmd.append("--allow-comm-range-mismatch")
        if bool(args.v2v4real_allow_pose_override):
            cmd.append("--allow-pose-override")
        if bool(args.v2v4real_split_noise):
            cmd.append("--split-noise")
        rc = _run(cmd, cwd=ROOT, env=env, log_path=v2v4_log)
        if rc != 0:
            failures.append("v2v4real_core_failed rc={}".format(rc))
        # Always attempt summarize/plots (even when the run had partial failures).
        v2v4_run_dir = ROOT / "outputs" / ("v2v4real_core_" + tag)
        plot_cmd = [
            str(PY39),
            "-u",
            str(ROOT / "tools" / "summarize_v2v4real_core_from_yaml.py"),
            "--run-dir",
            str(v2v4_run_dir),
            "--clean-plot-dir",
        ]
        if rc != 0:
            plot_cmd.append("--allow-incomplete")
        rc_plot = _run(plot_cmd, cwd=ROOT, env=env, log_path=out_dir / "v2v4real_summarize.log")
        if rc_plot != 0:
            failures.append("v2v4real_summarize_failed rc={}".format(rc_plot))

    # 3) Final summary
    summary = out_dir / "SUMMARY.md"
    lines = []
    lines.append("# Core Benchmark Pipeline Summary")
    lines.append("")
    lines.append("- tag: `{}`".format(tag))
    if full_run_id:
        lines.append("- opv2v_full_run_id: `{}`".format(full_run_id))
        lines.append("- opv2v_full_run_dir: `{}`".format("outputs/full_bench_" + full_run_id))
        lines.append("- unified_out_dir: `{}`".format(str((out_dir / "benchmark_unified").relative_to(ROOT))))
        lines.append("- fullmatrix_out_dir: `{}`".format(str((out_dir / "benchmark_fullmatrix").relative_to(ROOT))))
    else:
        lines.append("- opv2v_full_run_id: `NA`")
    lines.append("- dair_out_dir: `{}`".format("outputs/dair_core_" + tag))
    lines.append("- v2v4real_out_dir: `{}`".format("outputs/v2v4real_core_" + tag))
    lines.append("")
    if failures:
        lines.append("## Failures")
        lines.append("")
        for f in failures:
            lines.append("- " + f)
    else:
        lines.append("## Status")
        lines.append("")
        lines.append("- success")
    summary.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("pipeline_out_dir:", out_dir)
    print("summary:", summary)
    if failures:
        raise SystemExit("pipeline finished with failures: {}".format("; ".join(failures[:6])))


if __name__ == "__main__":
    main()
