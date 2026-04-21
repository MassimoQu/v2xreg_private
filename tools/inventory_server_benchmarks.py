#!/usr/bin/env python3
"""Inventory benchmark artifacts on this server.

Why: a lot of work lives in `outputs/` but never gets recorded in the cloud
Project. This script produces a de-noised, machine-readable inventory so we can
map local runs -> cloud Epics/Tasks/Runs without relying on manual archaeology.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import pathlib
from typing import Any, Dict, List, Optional


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
OUTPUTS = REPO_ROOT / "outputs"
DOCS = REPO_ROOT / "docs" / "operations"


def _load_json(path: pathlib.Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_jsonl(path: pathlib.Path, limit: int = 100000) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            if i >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    except Exception:
        return []
    return out


def _mtime_iso(path: pathlib.Path) -> str:
    try:
        ts = path.stat().st_mtime
        return dt.datetime.fromtimestamp(ts).isoformat(timespec="seconds")
    except Exception:
        return ""


def _parse_timestamp(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return dt.datetime.strptime(value, fmt).isoformat(timespec="seconds")
        except Exception:
            pass
    return value


def _summarize_run_state(path: pathlib.Path) -> Dict[str, Any]:
    """Best-effort summary for `run_state.jsonl` produced by autopilot/fullbench."""
    entries = _load_jsonl(path, limit=20000)
    started_at = ""
    ended_at = ""
    final_status = ""
    failures = 0
    total = 0
    for e in entries:
        if not isinstance(e, dict):
            continue
        total += 1
        ev = str(e.get("event") or e.get("type") or "")
        ts = str(e.get("ts") or e.get("timestamp") or "")
        if ev in {"run_start", "start", "begin"} and not started_at:
            started_at = ts
        if ev in {"run_end", "end", "finish", "done"}:
            ended_at = ts or ended_at
            final_status = str(e.get("status") or final_status)
        if str(e.get("status") or "").lower() in {"failed", "error"}:
            failures += 1
    return {
        "run_state_path": str(path),
        "run_state_mtime": _mtime_iso(path),
        "run_started_at": started_at,
        "run_ended_at": ended_at,
        "run_final_status": final_status,
        "run_state_entries": total,
        "run_state_failures": failures,
    }


@dataclasses.dataclass
class Inventory:
    generated_at: str
    repo_root: str
    items: List[Dict[str, Any]]


def collect_fullbench_runs() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for cfg_path in sorted(OUTPUTS.glob("full_bench*/config_snapshot.json")):
        cfg = _load_json(cfg_path) or {}
        run_dir = cfg_path.parent
        item: Dict[str, Any] = {
            "kind": "fullbench_run",
            "run_dir": str(run_dir),
            "config_snapshot_path": str(cfg_path),
            "config_snapshot_mtime": _mtime_iso(cfg_path),
            "run_id": cfg.get("run_id") or run_dir.name,
            "timestamp": _parse_timestamp(str(cfg.get("timestamp") or "")) or _mtime_iso(cfg_path),
            "modalities": cfg.get("modalities"),
            "sweeps": cfg.get("sweeps"),
            "methods": cfg.get("methods") or [],
            "solver_backend": cfg.get("solver_backend"),
            "runtime_mode": cfg.get("runtime_mode"),
            "pose_source": cfg.get("pose_source"),
            "comm_range_gating": cfg.get("comm_range_gating"),
            "camera_model": cfg.get("camera_model"),
            "lidar_model": cfg.get("lidar_model"),
            "camera_stage1": cfg.get("camera_stage1"),
            "lidar_stage1": cfg.get("lidar_stage1"),
            "git_commit": cfg.get("git_commit"),
            "git_branch": cfg.get("git_branch"),
            "git_dirty": cfg.get("git_dirty"),
            "heal_commit": cfg.get("heal_commit"),
            "heal_branch": cfg.get("heal_branch"),
            "heal_dirty": cfg.get("heal_dirty"),
        }
        rs_path = run_dir / "run_state.jsonl"
        if rs_path.exists():
            item.update(_summarize_run_state(rs_path))
        items.append(item)
    return items


def collect_core_runs_from_manifest() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for manifest_path in sorted(OUTPUTS.glob("**/manifest.json")):
        # Keep this small: there are currently only a few manifest.json files.
        manifest = _load_json(manifest_path) or {}
        run_dir = manifest_path.parent
        item: Dict[str, Any] = {
            "kind": "core_run",
            "run_dir": str(run_dir),
            "manifest_path": str(manifest_path),
            "manifest_mtime": _mtime_iso(manifest_path),
            "tag": manifest.get("tag"),
            "dataset": manifest.get("dataset"),
            "modality": manifest.get("modality"),
            "suite": manifest.get("suite"),
            "split_noise": manifest.get("split_noise"),
            "noise_pairs": manifest.get("noise_pairs") or [],
        }

        # method_specs exists in newer manifests; jobs exists in older.
        method_specs = manifest.get("method_specs") or []
        jobs = manifest.get("jobs") or []
        if method_specs:
            item["methods"] = [m.get("name") for m in method_specs if isinstance(m, dict) and m.get("name")]
            # Try to capture canonical stage1/model_dir from first non-empty spec.
            first = next((m for m in method_specs if isinstance(m, dict)), None)
            if first:
                item["comm_range"] = first.get("comm_range")
                item["pos_std_list"] = first.get("pos_std_list")
                item["rot_std_list"] = first.get("rot_std_list")
        elif jobs:
            item["methods"] = [j.get("name") for j in jobs if isinstance(j, dict) and j.get("name")]
            first = next((j for j in jobs if isinstance(j, dict)), None)
            if first:
                item["comm_range"] = first.get("comm_range")
                item["pos_std_list"] = first.get("pos_std_list")
                item["rot_std_list"] = first.get("rot_std_list")
                item["model_dir"] = first.get("model_dir")
                item["stage1_result"] = first.get("stage1_result")

        results_path = run_dir / "results.jsonl"
        if results_path.exists():
            item["results_path"] = str(results_path)
            item["results_mtime"] = _mtime_iso(results_path)
            item["results_lines"] = sum(1 for _ in results_path.open("r", encoding="utf-8", errors="ignore"))
        items.append(item)
    return items


def collect_pose_sweep_results() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for path in sorted(OUTPUTS.glob("pose_sweep_*_results.jsonl")):
        first = {}
        lines = _load_jsonl(path, limit=1)
        if lines:
            first = lines[0]
        item: Dict[str, Any] = {
            "kind": "pose_sweep_results",
            "results_path": str(path),
            "results_mtime": _mtime_iso(path),
            "example_model_dir": first.get("model_dir"),
            "example_stage1_result": first.get("stage1_result"),
            "example_pos_std_list": first.get("pos_std_list"),
            "example_rot_std_list": first.get("rot_std_list"),
        }
        # Count lines without loading the whole file into memory.
        try:
            item["entries"] = sum(1 for _ in path.open("r", encoding="utf-8", errors="ignore"))
        except Exception:
            item["entries"] = 0
        items.append(item)
    return items


def collect_aggregate_reports() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for name in (
        "benchmark_unified_20260220",
        "benchmark_fullmatrix_20260220",
        "benchmark_fullmatrix_audit_20260224",
        "benchmark_fullmatrix_mapping_20260223",
    ):
        path = OUTPUTS / name
        if not path.exists():
            continue
        items.append(
            {
                "kind": "aggregate_report",
                "path": str(path),
                "mtime": _mtime_iso(path),
            }
        )
    return items


def write_markdown(items: List[Dict[str, Any]], out_path: pathlib.Path) -> None:
    fullbench = [x for x in items if x.get("kind") == "fullbench_run"]
    core = [x for x in items if x.get("kind") == "core_run"]
    sweeps = [x for x in items if x.get("kind") == "pose_sweep_results"]
    aggs = [x for x in items if x.get("kind") == "aggregate_report"]

    def md_escape(s: Any) -> str:
        return str(s).replace("|", "\\|")

    lines: List[str] = []
    lines.append(f"# Server Benchmark Inventory ({dt.date.today().isoformat()})\n")
    lines.append("这份清单是从 `outputs/` 自动扫描生成的（去掉了“只在脑子里/只在 tmux 里”的信息丢失）。\n")

    lines.append("## 1) Fullbench Runs (OPV2V-style)\n")
    lines.append("| run_id | timestamp | modalities | sweeps | comm_range_gating | solver/runtime | methods | run_dir |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for x in sorted(fullbench, key=lambda d: d.get("timestamp") or "", reverse=True):
        lines.append(
            "| {} | {} | {} | {} | {} | {} | {} | `{}` |".format(
                md_escape(x.get("run_id")),
                md_escape(x.get("timestamp")),
                md_escape(x.get("modalities")),
                md_escape(x.get("sweeps")),
                md_escape(x.get("comm_range_gating")),
                md_escape(f"{x.get('solver_backend')}/{x.get('runtime_mode')}"),
                md_escape(",".join(x.get("methods") or [])),
                md_escape(x.get("run_dir")),
            )
        )
    if not fullbench:
        lines.append("_None found._")

    lines.append("\n## 2) Core Runs (DAIR/V2V4Real core pipeline)\n")
    lines.append("| dataset | modality | tag | suite | noise_points | methods | run_dir |")
    lines.append("| --- | --- | --- | --- | ---: | --- | --- |")
    for x in sorted(core, key=lambda d: d.get("manifest_mtime") or "", reverse=True):
        noise_points = len(x.get("noise_pairs") or [])
        lines.append(
            "| {} | {} | {} | {} | {} | {} | `{}` |".format(
                md_escape(x.get("dataset") or ""),
                md_escape(x.get("modality") or ""),
                md_escape(x.get("tag") or ""),
                md_escape(x.get("suite") or ""),
                md_escape(noise_points),
                md_escape(",".join([m for m in (x.get("methods") or []) if m])),
                md_escape(x.get("run_dir")),
            )
        )
    if not core:
        lines.append("_None found._")

    lines.append("\n## 3) Pose Sweep Results (DAIR-style)\n")
    lines.append("| file | entries | pos_std_list | rot_std_list | example_model_dir |")
    lines.append("| --- | ---: | --- | --- | --- |")
    for x in sorted(sweeps, key=lambda d: d.get("results_mtime") or "", reverse=True):
        lines.append(
            "| `{}` | {} | {} | {} | `{}` |".format(
                md_escape(x.get("results_path")),
                md_escape(x.get("entries")),
                md_escape(x.get("example_pos_std_list")),
                md_escape(x.get("example_rot_std_list")),
                md_escape(x.get("example_model_dir") or ""),
            )
        )
    if not sweeps:
        lines.append("_None found._")

    lines.append("\n## 4) Aggregate Reports\n")
    for x in aggs:
        lines.append(f"- `{x.get('path')}`")
    if not aggs:
        lines.append("_None found._")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    items: List[Dict[str, Any]] = []
    items.extend(collect_fullbench_runs())
    items.extend(collect_core_runs_from_manifest())
    items.extend(collect_pose_sweep_results())
    items.extend(collect_aggregate_reports())

    inv = Inventory(
        generated_at=dt.datetime.now().isoformat(timespec="seconds"),
        repo_root=str(REPO_ROOT),
        items=items,
    )

    stamp = dt.datetime.now().strftime("%Y%m%d")
    out_json = OUTPUTS / f"server_benchmark_inventory_{stamp}.json"
    out_md = DOCS / f"server_benchmark_inventory_{stamp}.md"

    out_json.write_text(json.dumps(dataclasses.asdict(inv), indent=2, sort_keys=True), encoding="utf-8")
    write_markdown(items, out_md)
    print(f"Wrote {out_json}")
    print(f"Wrote {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
