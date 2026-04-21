#!/usr/bin/env python3
"""
Audit an OPV2V fullbench run directory and emit an evidence-first Markdown report.

Focus:
- What is *actually* done (run_state.jsonl is source of truth)
- Which failures happened historically (logs may contain both failure + later success)
- Whether results are semantically valid for pose-noise robustness (pose_override, stage1 integrity, pose_solver.applied)
"""

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None


Key = Tuple[str, str, str, str, str]  # modality, sweep, method, strategy, noise


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _safe_json_loads(line: str) -> Optional[dict]:
    try:
        obj = json.loads(line)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def load_config_snapshot(run_dir: Path) -> Optional[dict]:
    path = run_dir / "config_snapshot.json"
    if not path.exists():
        return None
    return json.loads(_read_text(path))


def normalize_noise(val: str) -> str:
    return f"{float(val):.1f}"


def parse_ap_filename(path: Path, run_id: str) -> Optional[Tuple[Key, str]]:
    stem = path.stem
    if not stem.startswith("AP030507_"):
        return None
    marker = f"_{run_id}_"
    pos = stem.find(marker)
    if pos < 0:
        return None
    pose_correction = stem[len("AP030507_") : pos]
    remainder = stem[pos + len(marker) :]

    m = re.match(r"^(camera|lidar)_(noise10|drop20)_single$", remainder)
    if m:
        modality, sweep = m.groups()
        return (modality, sweep, "single", "bounds", normalize_noise("0")), pose_correction

    m = re.match(r"^(camera|lidar)_(noise10|drop20)_(baseline|oracle)_n([0-9.]+)$", remainder)
    if m:
        modality, sweep, method, noise = m.groups()
        return (modality, sweep, method, "bounds", normalize_noise(noise)), pose_correction

    m = re.match(
        r"^(camera|lidar)_(noise10|drop20)_(v2xregpp|freealign|vips|cbm)_(best|stable)_n([0-9.]+)$",
        remainder,
    )
    if m:
        modality, sweep, method, strategy, noise = m.groups()
        return (modality, sweep, method, strategy, normalize_noise(noise)), pose_correction

    return None


def iter_run_state_events(state_path: Path) -> Iterable[dict]:
    if not state_path.exists():
        return []
    for line in _read_text(state_path).splitlines():
        if not line.strip():
            continue
        obj = _safe_json_loads(line)
        if obj:
            yield obj


def summarize_run_state(run_dir: Path) -> dict:
    state_path = run_dir / "run_state.jsonl"
    starts = Counter()
    ends = Counter()
    ever_failed: Dict[Key, List[int]] = defaultdict(list)
    last_end: Dict[Key, Tuple[float, int]] = {}

    for ev in iter_run_state_events(state_path):
        task = ev.get("task")
        if not isinstance(task, list) or len(task) != 5:
            continue
        key = tuple(task)  # type: ignore[assignment]
        if ev.get("event") == "start":
            starts[key] += 1
        elif ev.get("event") == "end":
            ends[key] += 1
            code = ev.get("code")
            if isinstance(code, int) and code != 0:
                ever_failed[key].append(code)
            t = ev.get("time")
            t_val = float(t) if isinstance(t, (int, float)) else float(len(last_end))
            if key not in last_end or t_val >= last_end[key][0]:
                last_end[key] = (t_val, int(code) if isinstance(code, int) else 999)

    final_codes = Counter(code for _, code in last_end.values())
    final_done = {k for k, (_, code) in last_end.items() if code == 0}
    in_progress = {k for k in starts if k not in last_end}

    return {
        "state_path": str(state_path),
        "unique_tasks_started": len(starts),
        "unique_tasks_ended": len(ends),
        "final_end_codes": dict(final_codes),
        "final_done_tasks": len(final_done),
        "final_in_progress_tasks": len(in_progress),
        "tasks_ever_failed": len(ever_failed),
        "ever_failed_keys": ever_failed,
        "last_end": last_end,
    }


def stage1_stats(stage1_path: Path) -> Optional[dict]:
    stage1_path = Path(stage1_path)
    if stage1_path.is_dir():
        stage1_path = stage1_path / "stage1_boxes.json"
    if not stage1_path.exists():
        return None
    obj = json.loads(_read_text(stage1_path))
    if not isinstance(obj, dict):
        return {"path": str(stage1_path), "error": f"expected dict, got {type(obj)}"}
    mismatch = 0
    for rec in obj.values():
        if not isinstance(rec, dict):
            continue
        cav = rec.get("cav_id_list")
        pred = rec.get("pred_corner3d_np_list")
        if cav is None or pred is None:
            continue
        try:
            if len(cav) != len(pred):
                mismatch += 1
        except Exception:
            mismatch += 1
    return {"path": str(stage1_path), "samples": len(obj), "len_mismatch": mismatch}


def detect_pose_override(model_dir: Path) -> dict:
    cfg_path = Path(model_dir) / "config.yaml"
    if not cfg_path.exists():
        return {"config": str(cfg_path), "exists": False}

    text = _read_text(cfg_path)
    result = {"config": str(cfg_path), "exists": True, "pose_override_found": False}

    # Prefer YAML parse when available.
    if yaml is not None:
        try:
            obj = yaml.safe_load(text)
            pose_override = (obj or {}).get("pose_override") or {}
            if isinstance(pose_override, dict) and pose_override:
                result["pose_override_found"] = True
                result["enabled"] = bool(pose_override.get("enabled", False))
                result["mode"] = pose_override.get("mode")
                result["apply_to"] = pose_override.get("apply_to")
            return result
        except Exception:
            pass

    # Fallback: cheap regex scan.
    if "pose_override" not in text:
        return result
    result["pose_override_found"] = True
    enabled = re.search(r"^\s*enabled:\s*true\s*$", text, flags=re.IGNORECASE | re.MULTILINE) is not None
    mode_m = re.search(r"^\s*mode:\s*([A-Za-z0-9_]+)\s*$", text, flags=re.MULTILINE)
    result["enabled"] = enabled
    result["mode"] = mode_m.group(1) if mode_m else None
    return result


def classify_log_failure(log_text: str) -> Optional[str]:
    if "Cannot re-initialize CUDA in forked subprocess" in log_text:
        return "cuda_fork_reinit"
    if "CUDA out of memory" in log_text:
        return "cuda_oom"
    if re.search(r"^\s*Killed\s*$", log_text, flags=re.MULTILINE):
        return "killed"
    if "DataLoader worker process" in log_text and "RuntimeError" in log_text:
        return "dataloader_runtimeerror"
    if "Traceback (most recent call last)" in log_text:
        return "traceback"
    return None


def extract_failure_snippet(log_text: str, *, max_lines: int = 25) -> List[str]:
    lines = log_text.splitlines()
    # Try to start from the first traceback.
    for i, line in enumerate(lines):
        if "Cannot re-initialize CUDA in forked subprocess" in line:
            start = max(0, i - 8)
            return lines[start : start + max_lines]
        if line.startswith("Traceback (most recent call last):"):
            return lines[i : i + max_lines]
    return lines[-max_lines:]


def log_path_for_task(run_dir: Path, key: Key) -> Path:
    modality, sweep, method, strategy, noise = key
    return run_dir / "logs" / f"{modality}_{sweep}_{method}_{strategy}_n{noise}.log"


def scan_yaml_metrics(model_dir: Path, *, run_id: str) -> Dict[Key, dict]:
    data: Dict[Key, dict] = {}
    chosen_mtime: Dict[Key, float] = {}
    model_dir = Path(model_dir)
    if not model_dir.exists():
        return data
    for path in sorted(model_dir.glob("AP030507_*.yaml")):
        parsed = parse_ap_filename(path, run_id=run_id)
        if not parsed:
            continue
        key, pose_correction = parsed
        if yaml is None:
            continue
        obj = yaml.safe_load(_read_text(path))
        mtime = path.stat().st_mtime
        if key in chosen_mtime and mtime < chosen_mtime[key]:
            continue
        chosen_mtime[key] = mtime

        def _first_float(v: Any) -> Optional[float]:
            if isinstance(v, list) and v:
                try:
                    return float(v[0])
                except Exception:
                    return None
            if isinstance(v, (int, float)):
                return float(v)
            return None

        entry = {
            "pose_correction": pose_correction,
            "ap30": _first_float(obj.get("ap30")),
            "ap50": _first_float(obj.get("ap50")),
            "ap70": _first_float(obj.get("ap70")),
        }
        ts = (obj.get("timing_stats") or [{}])[0] if isinstance(obj.get("timing_stats"), list) else {}
        if isinstance(ts, dict):
            entry.update(
                {
                    "infer_fps": ts.get("infer_fps"),
                    "infer_sec": ts.get("infer_sec"),
                    "pose_fps": ts.get("pose_fps"),
                    "pose_sec": ts.get("pose_sec"),
                    "samples": ts.get("samples"),
                }
            )
            ps = ts.get("pose_solver")
            if isinstance(ps, dict):
                entry.update(
                    {
                        "pose_solver_applied": ps.get("applied"),
                        "pose_solver_avg_time_sec": ps.get("avg_time_sec"),
                        "pose_solver_samples": ps.get("samples"),
                    }
                )
        data[key] = entry
    return data


def _md_code(s: str) -> str:
    return f"`{s}`"


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit OPV2V fullbench run into a Markdown evidence report.")
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=None, help="Markdown output path (default: docs/operations/...).")
    ap.add_argument("--max-log-examples", type=int, default=2)
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    cfg = load_config_snapshot(run_dir) or {}
    run_id = cfg.get("run_id")
    if not run_id:
        name = run_dir.name
        run_id = name[len("full_bench_") :] if name.startswith("full_bench_") else name

    out = args.out
    if out is None:
        stamp = datetime.now().strftime("%Y%m%d")
        out = Path("docs/operations") / f"opv2v_fullbench_evidence_{stamp}.md"

    state = summarize_run_state(run_dir)

    camera_model = Path(cfg.get("camera_model", "")) if cfg.get("camera_model") else None
    lidar_model = Path(cfg.get("lidar_model", "")) if cfg.get("lidar_model") else None
    camera_stage1 = Path(cfg.get("camera_stage1", "")) if cfg.get("camera_stage1") else None
    lidar_stage1 = Path(cfg.get("lidar_stage1", "")) if cfg.get("lidar_stage1") else None

    # Log failure signatures (historical failures; many tasks may later succeed).
    sig_counter: Counter[str] = Counter()
    sig_examples: Dict[str, List[Tuple[Key, Path, List[str]]]] = defaultdict(list)
    for key in sorted(state["ever_failed_keys"].keys()):  # type: ignore[union-attr]
        log_path = log_path_for_task(run_dir, key)
        if not log_path.exists():
            continue
        text = _read_text(log_path)
        sig = classify_log_failure(text) or "unknown"
        sig_counter[sig] += 1
        if len(sig_examples[sig]) < int(args.max_log_examples):
            sig_examples[sig].append((key, log_path, extract_failure_snippet(text)))

    # YAML metrics scan (optional if PyYAML missing).
    yaml_entries: Dict[Key, dict] = {}
    if camera_model:
        yaml_entries.update(scan_yaml_metrics(camera_model, run_id=run_id))
    if lidar_model:
        yaml_entries.update(scan_yaml_metrics(lidar_model, run_id=run_id))

    # Basic curve sanity stats (AP50 span).
    spans: Dict[Tuple[str, str, str, str], dict] = {}
    grouped: Dict[Tuple[str, str, str, str], List[Tuple[float, float]]] = defaultdict(list)
    for (mod, sweep, method, strategy, noise), entry in yaml_entries.items():
        ap50 = entry.get("ap50")
        if ap50 is None:
            continue
        grouped[(mod, sweep, method, strategy)].append((float(noise), float(ap50)))
    for k, pts in grouped.items():
        pts = sorted(pts)
        ys = [y for _, y in pts]
        spans[k] = {"n": len(pts), "min": min(ys), "max": max(ys), "span": max(ys) - min(ys)}

    # Pose solver applied summary.
    applied_summary: Dict[Tuple[str, str, str, str], dict] = {}
    applied_pts: Dict[Tuple[str, str, str, str], List[int]] = defaultdict(list)
    for (mod, sweep, method, strategy, _noise), entry in yaml_entries.items():
        if method in {"v2xregpp", "freealign", "vips", "cbm"}:
            v = entry.get("pose_solver_applied")
            if isinstance(v, int):
                applied_pts[(mod, sweep, method, strategy)].append(v)
    for k, vs in applied_pts.items():
        applied_summary[k] = {"min": min(vs), "max": max(vs), "all_zero": all(x == 0 for x in vs)}

    # Stage1 cache stats.
    st_camera = stage1_stats(camera_stage1) if camera_stage1 else None
    st_lidar = stage1_stats(lidar_stage1) if lidar_stage1 else None

    # Pose override detection.
    po_camera = detect_pose_override(camera_model) if camera_model else None
    po_lidar = detect_pose_override(lidar_model) if lidar_model else None

    # task_summary.json mismatch evidence (if present)
    task_summary_path = run_dir / "task_summary.json"
    task_summary_raw = None
    if task_summary_path.exists():
        try:
            task_summary_raw = json.loads(_read_text(task_summary_path))
        except Exception:
            task_summary_raw = {"error": "failed to parse", "path": str(task_summary_path)}

    out.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    lines.append(f"# OPV2V Fullbench Evidence Report ({datetime.now().strftime('%Y-%m-%d')})")
    lines.append("")
    lines.append("## 0) Executive Conclusions")
    lines.append("")
    lines.append(f"- Run dir: {_md_code(str(run_dir))}")
    lines.append(f"- Run id: {_md_code(str(run_id))}")
    lines.append(f"- Source of truth: {_md_code(str(run_dir / 'run_state.jsonl'))} (NOT log grepping)")
    lines.append("")
    lines.append("## 1) Run State (What Actually Finished)")
    lines.append("")
    lines.append(f"- unique_tasks_started: {state['unique_tasks_started']}")
    lines.append(f"- unique_tasks_ended: {state['unique_tasks_ended']}")
    lines.append(f"- final_end_codes: {state['final_end_codes']}")
    lines.append(f"- final_done_tasks: {state['final_done_tasks']}")
    lines.append(f"- tasks_ever_failed (historical): {state['tasks_ever_failed']}")
    lines.append("")
    if task_summary_raw is not None:
        lines.append("### task_summary.json (May Be Stale/Misleading)")
        lines.append("")
        lines.append(f"- path: {_md_code(str(task_summary_path))}")
        lines.append("```json")
        lines.append(json.dumps(task_summary_raw, indent=2, sort_keys=True))
        lines.append("```")
        lines.append("")
    lines.append("## 2) Historical Failures (Why It Failed Before)")
    lines.append("")
    if not sig_counter:
        lines.append("- No failures recorded in run_state.jsonl.")
    else:
        lines.append("- Failure signatures (count tasks that *ever* saw a non-zero exit):")
        for sig, n in sig_counter.most_common():
            lines.append(f"  - {sig}: {n}")
        lines.append("")
        for sig, exs in sig_examples.items():
            lines.append(f"### Example: {sig}")
            lines.append("")
            for key, log_path, snippet in exs:
                lines.append(f"- task: {_md_code('/'.join(key))}")
                lines.append(f"- log: {_md_code(str(log_path))}")
                lines.append("```")
                lines.extend(snippet)
                lines.append("```")
                lines.append("")

    lines.append("## 3) Stage1 Cache Integrity (Hard Requirement for Pose-Correction)")
    lines.append("")
    if st_camera:
        lines.append(f"- camera stage1: {_md_code(st_camera['path'])} samples={st_camera.get('samples')} len_mismatch={st_camera.get('len_mismatch')}")
    if st_lidar:
        lines.append(f"- lidar stage1: {_md_code(st_lidar['path'])} samples={st_lidar.get('samples')} len_mismatch={st_lidar.get('len_mismatch')}")
    lines.append("")

    lines.append("## 4) Pose Override (Can Cancel Noise Sweeps)")
    lines.append("")
    if po_camera:
        lines.append(f"- camera model config: {_md_code(po_camera['config'])} pose_override_found={po_camera.get('pose_override_found')} enabled={po_camera.get('enabled')} mode={po_camera.get('mode')}")
    if po_lidar:
        lines.append(f"- lidar model config: {_md_code(po_lidar['config'])} pose_override_found={po_lidar.get('pose_override_found')} enabled={po_lidar.get('enabled')} mode={po_lidar.get('mode')}")
    lines.append("")

    lines.append("## 5) YAML-Derived Sanity Stats (AP Span + pose_solver.applied)")
    lines.append("")
    if yaml is None:
        lines.append("- PyYAML not available; skipping YAML scan. Run with the micromamba py39 environment.")
    else:
        # Highlight a few key curves.
        key_focus = [
            ("lidar", "noise10", "baseline", "bounds"),
            ("lidar", "noise10", "oracle", "bounds"),
            ("camera", "noise10", "v2xregpp", "best"),
        ]
        for mod, sweep, method, strategy in key_focus:
            s = spans.get((mod, sweep, method, strategy))
            if s:
                lines.append(f"- AP50 span {mod}/{sweep}/{method}/{strategy}: n={s['n']} min={s['min']:.6f} max={s['max']:.6f} span={s['span']:.6f}")
        lines.append("")
        # Applied summary (flag all-zero)
        flagged = [k for k, v in applied_summary.items() if v.get("all_zero")]
        if flagged:
            lines.append("- pose_solver.applied all-zero lines (these pose-correction methods likely did NOT apply):")
            for (mod, sweep, method, strategy) in sorted(flagged)[:20]:
                v = applied_summary[(mod, sweep, method, strategy)]
                lines.append(f"  - {mod}/{sweep}/{method}/{strategy}: applied_min={v['min']} applied_max={v['max']}")
            if len(flagged) > 20:
                lines.append(f"  - ... ({len(flagged)-20} more)")
            lines.append("")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote evidence report: {out}")


if __name__ == "__main__":
    main()
