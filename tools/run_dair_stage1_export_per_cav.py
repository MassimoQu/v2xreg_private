#!/usr/bin/env python3
"""
Export DAIR-V2X stage1 boxes in *per-CAV local frames* (sharded) + merge + validate.

This is the DAIR analogue of tools/run_v2v4real_stage1_export_per_cav.py.

Why this exists:
  Core box-based pose solvers (V2X-Reg++/FreeAlign/VIPS/CBM) assume that
  `pred_corner3d_np_list[k]` is expressed in the k-th agent's *local frame*.
  For DAIR, many historical detected caches are in a common frame and/or
  contain dummy poses, which breaks both comm-range analysis and core benchmarks.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


ROOT = Path(__file__).resolve().parents[1]
HEAL_DIR = ROOT / "HEAL"

DEFAULT_HYPES = HEAL_DIR / "opencood" / "logs" / "HeterBaseline_DAIR_lidar_v2xvit_2023_09_09_11_19_26" / "config.yaml"
DEFAULT_CKPT = (
    HEAL_DIR
    / "opencood"
    / "logs"
    / "HeterBaseline_DAIR_lidar_v2xvit_2023_09_09_11_19_26"
    / "net_epoch_bestval_at17.pth"
)
DEFAULT_OUT_DIR = ROOT / "data" / "DAIR-V2X" / "detected" / "lidar_v2xvit_stage1_percav"

DEFAULT_EXPORT_PY = Path("/home/qqxluca/.micromamba/envs/heal/bin/python")
DEFAULT_CHECK_PY = ROOT / ".micromamba" / "envs" / "py39" / "bin" / "python"

EXPORT_SCRIPT = HEAL_DIR / "opencood" / "tools" / "export_stage1_boxes_per_cav.py"


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _parse_csv(s: str) -> List[str]:
    return [x.strip() for x in str(s or "").split(",") if x.strip()]


def _resolve_path(p: Path) -> Path:
    p = Path(p)
    if p.is_absolute():
        return p
    return (ROOT / p).resolve()


def _expected_per_shard(total: int, shard: int, num_shards: int) -> int:
    base = int(total) // int(num_shards)
    rem = int(total) % int(num_shards)
    return base + (1 if int(shard) < rem else 0)


def _load_json_len(path: Path) -> Optional[int]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    return len(obj)


@dataclass(frozen=True)
class ShardTask:
    shard_index: int
    gpu: int
    out_path: Path
    log_path: Path


def _run_shard(
    *,
    task: ShardTask,
    export_python: Path,
    hypes_yaml: Path,
    ckpt: Path,
    output_dir: Path,
    split: str,
    num_shards: int,
    max_samples: int,
    comm_range_override: Optional[float],
    log_interval: int,
) -> int:
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(int(task.gpu))
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("OMP_NUM_THREADS", "1")
    env.setdefault("MKL_NUM_THREADS", "1")
    env.setdefault("OPENBLAS_NUM_THREADS", "1")
    env.setdefault("NUMEXPR_NUM_THREADS", "1")
    # Make HEAL importable.
    env["PYTHONPATH"] = str(HEAL_DIR)

    cmd = [
        str(export_python),
        "-u",
        str(EXPORT_SCRIPT),
        "--hypes_yaml",
        str(hypes_yaml),
        "--stage1_checkpoint",
        str(ckpt),
        "--output_dir",
        str(output_dir),
        "--split",
        str(split),
        "--shard-index",
        str(int(task.shard_index)),
        "--num-shards",
        str(int(num_shards)),
        "--log-interval",
        str(int(log_interval)),
    ]
    if comm_range_override is not None:
        cmd.extend(["--comm_range_override", str(float(comm_range_override))])
    if int(max_samples) > 0:
        cmd.extend(["--max_samples", str(int(max_samples))])

    task.log_path.parent.mkdir(parents=True, exist_ok=True)
    with task.log_path.open("w", encoding="utf-8") as f:
        f.write(f"time: {_now()}\n")
        f.write(f"gpu: {task.gpu}\n")
        f.write(f"shard_index: {task.shard_index}/{num_shards}\n")
        f.write(f"cmd: {' '.join(cmd)}\n\n")
        f.flush()
        proc = subprocess.run(cmd, cwd=str(ROOT), env=env, stdout=f, stderr=subprocess.STDOUT)
        f.write(f"\nexit_code={proc.returncode}\n")
        return int(proc.returncode)


def _run_check(cmd: List[str], *, log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write("\n" + "=" * 80 + "\n")
        f.write("time: {}\n".format(_now()))
        f.write("cmd: {}\n".format(" ".join(cmd)))
        f.write("=" * 80 + "\n\n")
        f.flush()
        proc = subprocess.run(cmd, cwd=str(ROOT), stdout=f, stderr=subprocess.STDOUT)
        f.write("\nexit_code={}\n".format(proc.returncode))
        return int(proc.returncode)


def main() -> None:
    ap = argparse.ArgumentParser(description="Export + merge + validate per-CAV DAIR stage1 cache (sharded).")
    ap.add_argument("--tag", type=str, default=time.strftime("%Y%m%d_%H%M%S"))
    ap.add_argument("--gpus", type=str, default="0,1,2,3,4,5,6,7,8,9")
    ap.add_argument("--num-shards", type=int, default=0, help="0=use len(--gpus).")
    ap.add_argument("--export-python", type=Path, default=DEFAULT_EXPORT_PY)
    ap.add_argument("--check-python", type=Path, default=DEFAULT_CHECK_PY)
    ap.add_argument("--hypes-yaml", type=Path, default=DEFAULT_HYPES)
    ap.add_argument("--stage1-checkpoint", type=Path, default=DEFAULT_CKPT)
    ap.add_argument("--output-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--split", type=str, default="test")
    ap.add_argument("--expected-samples", type=int, default=0, help="0=skip strict count checks; otherwise used for resume/merge checks.")
    ap.add_argument("--max-samples", type=int, default=0, help="0=full; >0 for smoke export.")
    ap.add_argument("--comm-range-override", type=float, default=None)
    ap.add_argument("--log-interval", type=int, default=50)
    ap.add_argument("--skip-existing-shards", action="store_true")
    ap.add_argument("--delete-shards-after-merge", action="store_true")
    args = ap.parse_args()

    gpus = [int(x) for x in _parse_csv(args.gpus)]
    if not gpus:
        raise SystemExit("--gpus must be non-empty")
    num_shards = int(args.num_shards) if int(args.num_shards) > 0 else len(gpus)
    if num_shards <= 0:
        raise SystemExit("--num-shards must be >= 1")

    export_python = Path(args.export_python)
    check_python = Path(args.check_python)
    hypes_yaml = _resolve_path(Path(args.hypes_yaml))
    ckpt = _resolve_path(Path(args.stage1_checkpoint))
    output_dir = _resolve_path(Path(args.output_dir))

    if not export_python.exists():
        raise SystemExit(f"export-python not found: {export_python}")
    if not check_python.exists():
        raise SystemExit(f"check-python not found: {check_python}")
    if not hypes_yaml.exists():
        raise SystemExit(f"hypes-yaml not found: {hypes_yaml}")
    if not ckpt.exists():
        raise SystemExit(f"stage1-checkpoint not found: {ckpt}")
    if not EXPORT_SCRIPT.exists():
        raise SystemExit(f"export script not found: {EXPORT_SCRIPT}")

    split = str(args.split or "test").lower()
    split_dir = output_dir / split
    split_dir.mkdir(parents=True, exist_ok=True)

    run_dir = ROOT / "outputs" / ("dair_stage1_export_" + str(args.tag))
    log_dir = run_dir / "logs"
    run_dir.mkdir(parents=True, exist_ok=True)

    effective_expected = int(args.expected_samples) if int(args.expected_samples) > 0 else None
    if int(args.max_samples) > 0:
        effective_expected = int(args.max_samples) if effective_expected is None else min(int(args.max_samples), effective_expected)
    head_expected = 200 if effective_expected is None else min(200, int(effective_expected))

    q: "queue.Queue[int]" = queue.Queue()
    skipped: List[Dict[str, object]] = []
    for shard_index in range(num_shards):
        shard_path = split_dir / f"stage1_boxes_shard{int(shard_index):02d}of{int(num_shards):02d}.json"
        if bool(args.skip_existing_shards) and shard_path.exists():
            if effective_expected is not None:
                exp_cnt = _expected_per_shard(effective_expected, shard_index, num_shards)
                got = _load_json_len(shard_path)
                if got == exp_cnt:
                    skipped.append({"shard": shard_index, "path": str(shard_path), "count": got})
                    continue
            else:
                got = _load_json_len(shard_path)
                if got is not None and got > 0:
                    skipped.append({"shard": shard_index, "path": str(shard_path), "count": got})
                    continue
        q.put(shard_index)

    shard_errors: List[Dict[str, object]] = []
    lock = threading.Lock()

    def worker(gpu: int):
        while True:
            try:
                shard_index = q.get_nowait()
            except queue.Empty:
                return
            shard_path = split_dir / f"stage1_boxes_shard{int(shard_index):02d}of{int(num_shards):02d}.json"
            log_path = log_dir / f"shard{int(shard_index):02d}.log"
            task = ShardTask(shard_index=shard_index, gpu=gpu, out_path=shard_path, log_path=log_path)
            rc = _run_shard(
                task=task,
                export_python=export_python,
                hypes_yaml=hypes_yaml,
                ckpt=ckpt,
                output_dir=output_dir,
                split=split,
                num_shards=num_shards,
                max_samples=int(args.max_samples),
                comm_range_override=args.comm_range_override,
                log_interval=int(args.log_interval),
            )
            if rc != 0:
                with lock:
                    shard_errors.append({"shard": shard_index, "gpu": gpu, "rc": rc, "log": str(log_path)})

    threads = []
    for gpu in gpus:
        t = threading.Thread(target=worker, args=(int(gpu),), daemon=True)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()

    status = {
        "time": _now(),
        "tag": str(args.tag),
        "split": split,
        "output_dir": str(output_dir),
        "hypes_yaml": str(hypes_yaml),
        "checkpoint": str(ckpt),
        "num_shards": int(num_shards),
        "gpus": gpus,
        "skipped": skipped,
        "shard_errors": shard_errors,
    }
    (run_dir / "run_state.json").write_text(json.dumps(status, indent=2, sort_keys=True), encoding="utf-8")

    if shard_errors:
        print("[stage1-export] shard failures (continuing to merge check):")
        for e in shard_errors:
            print("  -", e)

    merged_path = split_dir / "stage1_boxes.json"
    merge_log = run_dir / "merge_and_validate.log"

    # Merge only if all shard files exist.
    missing = []
    for shard_index in range(num_shards):
        p = split_dir / f"stage1_boxes_shard{int(shard_index):02d}of{int(num_shards):02d}.json"
        if not p.exists():
            missing.append(str(p))
    if missing:
        with merge_log.open("a", encoding="utf-8") as f:
            f.write("Missing shard files (skip merge):\n")
            for p in missing:
                f.write("  - {}\n".format(p))
        raise SystemExit(1)

    # 1) merge + write head200
    rc = _run_check(
        [
            str(check_python),
            "-u",
            str(ROOT / "tools" / "merge_stage1_shards.py"),
            "--shard-dir",
            str(split_dir),
            "--num-shards",
            str(int(num_shards)),
            "--out",
            str(merged_path),
            "--write-head200",
            "--head-n",
            str(int(head_expected)),
        ],
        log_path=merge_log,
    )
    if rc != 0:
        raise SystemExit(rc)

    # 2) structural + semantic validators
    rc = _run_check(
        [str(check_python), "-u", str(ROOT / "tools" / "validate_stage1_cache.py"), "--stage1", str(merged_path.with_name(f"stage1_boxes_head{head_expected}.json"))],
        log_path=merge_log,
    )
    if rc != 0:
        raise SystemExit(rc)
    rc = _run_check(
        [
            str(check_python),
            "-u",
            str(ROOT / "tools" / "validate_stage1_semantics.py"),
            "--stage1",
            str(merged_path),
            "--prefer-head200",
            "--num-samples",
            "50",
            "--min-valid-samples",
            "10",
        ],
        log_path=merge_log,
    )
    if rc != 0:
        raise SystemExit(rc)

    if bool(args.delete_shards_after_merge):
        for shard_index in range(num_shards):
            p = split_dir / f"stage1_boxes_shard{int(shard_index):02d}of{int(num_shards):02d}.json"
            try:
                p.unlink()
            except Exception:
                pass

    print(f"[OK] merged per-CAV stage1 cache: {merged_path}")


if __name__ == "__main__":
    main()

