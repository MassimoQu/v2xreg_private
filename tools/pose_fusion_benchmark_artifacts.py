#!/usr/bin/env python3
import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Sequence, Set, Tuple, Union


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_T01_COMMAND = (
    "PYTHONPATH=HEAL .micromamba/envs/py39/bin/python "
    "HEAL/opencood/tools/test_pose_provider_runtime.py"
    " && "
    "PYTHONPATH=HEAL .micromamba/envs/py39/bin/python -m unittest "
    "HEAL/opencood/tools/test_inference_w_noise_runtime_config.py"
    " && "
    "PYTHONPATH=HEAL .micromamba/envs/py39/bin/python -m unittest "
    "HEAL/opencood/tools/test_train_utils_pose_provider_cache.py"
)
DEFAULT_GT_PATTERNS = [r"oracle_gt", r"lidar_pose_clean_np", r"pose_source\"?\s*[:=]\s*['\"]?gt"]
DEFAULT_ALLOWED_ORACLE_PATTERN = r"oracle"
DEFAULT_T05_WHITELIST = [
    "run_id",
    "created_at_utc",
    "protocol.runtime_mode",
    "protocol.solver_backend",
    "protocol.pose_source",
    "extras",
]


class GateResult(NamedTuple):
    gate_id: str
    status: str
    reason: str
    evidence: Dict[str, Any]


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _abs_path(path: Union[str, Path]) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    return (REPO_ROOT / p).resolve()


def _hash_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _file_record(path: Union[str, Path]) -> Dict[str, Any]:
    abs_path = _abs_path(path)
    rec: Dict[str, Any] = {"path": str(abs_path), "exists": abs_path.exists()}
    if abs_path.exists() and abs_path.is_file():
        stat = abs_path.stat()
        rec.update(
            {
                "size_bytes": stat.st_size,
                "mtime_utc": dt.datetime.fromtimestamp(
                    stat.st_mtime, tz=dt.timezone.utc
                ).replace(microsecond=0).isoformat(),
                "sha256": _hash_file(abs_path),
            }
        )
    return rec


def _git_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {}
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            check=True,
        ).stdout.strip()
        info["commit"] = commit
    except Exception:
        info["commit"] = None

    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            check=True,
        ).stdout.splitlines()
        info["dirty"] = len(status) > 0
        info["dirty_file_count"] = len(status)
    except Exception:
        info["dirty"] = None
        info["dirty_file_count"] = None
    return info


def _parse_kv_pairs(pairs: Sequence[str]) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"Invalid --extra item (expect key=value): {pair}")
        key, value = pair.split("=", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def build_manifest(
    *,
    run_id: str,
    dataset_split: str,
    runtime_mode: Optional[str],
    solver_backend: Optional[str],
    fusion_method: Optional[str],
    noise_schedule: Optional[str],
    dropout_schedule: Optional[str],
    model_dirs: Sequence[str],
    config_files: Sequence[str],
    checkpoint_files: Sequence[str],
    script_files: Sequence[str],
    stage1_files: Sequence[str],
    result_sources: Sequence[str],
    extras: Mapping[str, str],
) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "created_at_utc": _utc_now(),
        "repo_root": str(REPO_ROOT),
        "git": _git_info(),
        "protocol": {
            "dataset_split": dataset_split,
            "runtime_mode": runtime_mode,
            "solver_backend": solver_backend,
            "fusion_method": fusion_method,
            "noise_schedule": noise_schedule,
            "dropout_schedule": dropout_schedule,
        },
        "artifacts": {
            "model_dirs": [
                {"path": str(_abs_path(p)), "exists": _abs_path(p).exists()} for p in model_dirs
            ],
            "config_files": [_file_record(p) for p in config_files],
            "checkpoint_files": [_file_record(p) for p in checkpoint_files],
            "script_files": [_file_record(p) for p in script_files],
            "stage1_result_files": [_file_record(p) for p in stage1_files],
            "result_sources": [_file_record(p) for p in result_sources],
        },
        "extras": dict(extras),
    }


def _load_json_or_jsonl(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    if path.suffix.lower() == ".jsonl":
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not lines:
            raise ValueError(f"Empty jsonl file: {path}")
        return json.loads(lines[-1])
    raise ValueError(f"Unsupported metric file type: {path}")


def _pick_metric(obj: Mapping[str, Any], candidates: Sequence[str]) -> Optional[float]:
    for key in candidates:
        if key in obj:
            try:
                return float(obj[key])
            except Exception:
                return None
    return None


def _extract_ap_metrics(obj: Mapping[str, Any]) -> Dict[str, Optional[float]]:
    return {
        "ap30": _pick_metric(obj, ["mean_ap30", "ap30", "AP30", "ap_30"]),
        "ap50": _pick_metric(obj, ["mean_ap50", "ap50", "AP50", "ap_50"]),
        "ap70": _pick_metric(obj, ["mean_ap70", "ap70", "AP70", "ap_70"]),
    }


def _extract_pose_metrics(obj: Mapping[str, Any]) -> Dict[str, Optional[float]]:
    return {
        "rel_trans_m": _pick_metric(
            obj,
            [
                "mean_rel_trans_m",
                "median_rel_trans_m",
                "rel_trans_m",
                "mRTE",
                "mRTE@1.0",
            ],
        ),
        "rel_yaw_deg": _pick_metric(
            obj,
            [
                "mean_rel_yaw_deg",
                "median_rel_yaw_deg",
                "rel_yaw_deg",
                "mRRE",
                "mRRE@1.0",
            ],
        ),
    }


def _ap_delta(lhs: Mapping[str, Optional[float]], rhs: Mapping[str, Optional[float]]) -> Tuple[float, Dict[str, float]]:
    per_key: Dict[str, float] = {}
    for key in ("ap30", "ap50", "ap70"):
        lv = lhs.get(key)
        rv = rhs.get(key)
        if lv is None or rv is None:
            continue
        per_key[key] = abs(lv - rv)
    return (max(per_key.values()) if per_key else float("inf"), per_key)


def _pose_delta(lhs: Mapping[str, Optional[float]], rhs: Mapping[str, Optional[float]]) -> Tuple[float, Dict[str, float]]:
    per_key: Dict[str, float] = {}
    for key in ("rel_trans_m", "rel_yaw_deg"):
        lv = lhs.get(key)
        rv = rhs.get(key)
        if lv is None or rv is None:
            continue
        per_key[key] = abs(lv - rv)
    return (max(per_key.values()) if per_key else float("inf"), per_key)


def _run_shell(command: str, timeout_sec: int) -> Dict[str, Any]:
    proc = subprocess.run(
        ["bash", "-lc", command],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        timeout=timeout_sec,
        check=False,
    )
    return {
        "command": command,
        "returncode": proc.returncode,
        "stdout_tail": "\n".join(proc.stdout.splitlines()[-40:]),
        "stderr_tail": "\n".join(proc.stderr.splitlines()[-40:]),
    }


def _expand_paths(patterns: Sequence[str]) -> List[Path]:
    out: List[Path] = []
    for pattern in patterns:
        abs_pattern = _abs_path(pattern)
        parent = abs_pattern.parent
        matches = sorted(parent.glob(abs_pattern.name))
        out.extend(matches)
    dedup: List[Path] = []
    seen = set()  # type: Set[str]
    for item in out:
        key = str(item.resolve())
        if key in seen:
            continue
        seen.add(key)
        dedup.append(item)
    return dedup


def _flatten_json(obj: Any, prefix: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if isinstance(obj, dict):
        for key in sorted(obj.keys()):
            nxt = key if not prefix else prefix + "." + str(key)
            out.update(_flatten_json(obj[key], nxt))
        return out
    if isinstance(obj, list):
        for idx, val in enumerate(obj):
            nxt = str(idx) if not prefix else prefix + "." + str(idx)
            out.update(_flatten_json(val, nxt))
        return out
    out[prefix] = obj
    return out


def _prefix_any(path: str, prefixes: Sequence[str]) -> bool:
    for pref in prefixes:
        if path == pref or path.startswith(pref + "."):
            return True
    return False


def _compare_manifests_for_t05(
    current_manifest: Mapping[str, Any],
    reference_manifest: Mapping[str, Any],
    whitelist: Sequence[str],
) -> Dict[str, Any]:
    lhs = _flatten_json(reference_manifest)
    rhs = _flatten_json(current_manifest)
    all_keys = sorted(set(lhs.keys()) | set(rhs.keys()))

    mismatches: List[Dict[str, Any]] = []
    ignored: List[str] = []
    for key in all_keys:
        if _prefix_any(key, whitelist):
            ignored.append(key)
            continue
        lv = lhs.get(key, "__MISSING__")
        rv = rhs.get(key, "__MISSING__")
        if lv != rv:
            mismatches.append({"field": key, "reference": lv, "current": rv})

    return {
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "ignored_key_count": len(ignored),
        "whitelist": list(whitelist),
    }


def _read_jsonl_rows(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def _extract_timing_objects(row: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    out: List[Mapping[str, Any]] = []
    for key in ["pose_timing", "timing", "timing_summary"]:
        maybe = row.get(key)
        if isinstance(maybe, Mapping):
            out.append(maybe)
    return out


def _safe_float(val: Any) -> Optional[float]:
    try:
        return float(val)
    except Exception:
        return None


def _safe_int(val: Any) -> Optional[int]:
    try:
        return int(val)
    except Exception:
        return None


def _topk_methods_by_ap50(rows: Sequence[Mapping[str, Any]], k: int = 2) -> List[str]:
    best: Dict[str, float] = {}
    for row in rows:
        method = row.get("method")
        strategy = row.get("strategy")
        if method is None:
            job_id = row.get("job_id")
            if job_id is not None:
                method_key = str(job_id)
            else:
                continue
        else:
            method_key = str(method)
            if strategy is not None:
                method_key += ":" + str(strategy)
        ap50 = _safe_float(
            row.get("mean_ap50")
            if "mean_ap50" in row
            else row.get("ap50") if "ap50" in row else row.get("AP50")
        )
        if ap50 is None:
            continue
        prev = best.get(method_key)
        if prev is None or ap50 > prev:
            best[method_key] = ap50
    ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
    return [name for name, _ in ranked[:k]]


def _classify_bound_bucket(row: Mapping[str, Any]) -> Optional[str]:
    mode = row.get("runtime_mode")
    if isinstance(mode, str):
        mode = mode.lower().strip()
        if mode == "single_only":
            return "single_only"
        if mode == "register_and_fuse":
            return "register_and_fuse"
        if mode == "fusion_only":
            src = str(row.get("pose_source") or "").lower().strip()
            if src == "gt":
                return "fusion_only_gt"
            return "fusion_only_non_gt"

    pose_corr = str(row.get("pose_correction") or "").lower().strip()
    if pose_corr == "oracle_gt":
        return "fusion_only_gt"
    if pose_corr in {"none", "identity", "noisy_input"}:
        return "fusion_only_non_gt"

    method = str(row.get("method") or "").lower().strip()
    if method in {"v2xregpp", "freealign", "vips", "cbm", "image_match", "lidar_reg", "pgc"}:
        return "register_and_fuse"
    if "single" in str(row.get("job_id") or "").lower():
        return "single_only"
    return None


def evaluate_gates(
    *,
    run_id: str,
    manifest_path: Path,
    t01_command: str,
    t01_timeout_sec: int,
    run_t01: bool,
    t02_baseline: Optional[Path],
    t02_provider: Optional[Path],
    t03_offline: Optional[Path],
    t03_online: Optional[Path],
    t02_ap_threshold: float,
    t03_ap_threshold: float,
    t03_pose_threshold: float,
    audit_patterns: Sequence[str],
    leak_patterns: Sequence[str],
    oracle_allow_pattern: str,
    strict: bool,
    t05_reference_manifest: Optional[Path] = None,
    t05_whitelist: Optional[Sequence[str]] = None,
    t06_results: Optional[Path] = None,
    t07_reference_results: Optional[Path] = None,
    t07_candidate_results: Optional[Path] = None,
    t07_min_gain: float = 1.3,
    t08_reference_results: Optional[Path] = None,
    t08_candidate_results: Optional[Path] = None,
    t09_results: Optional[Path] = None,
    t10_rollback_command: Optional[str] = None,
    t10_timeout_sec: int = 120,
) -> List[GateResult]:
    gates: List[GateResult] = []

    t00_evidence: Dict[str, Any] = {"manifest": str(manifest_path), "exists": manifest_path.exists()}
    if not manifest_path.exists():
        gates.append(
            GateResult(
                gate_id="T00",
                status="FAIL",
                reason="manifest file missing",
                evidence=t00_evidence,
            )
        )
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            required = ["run_id", "protocol", "artifacts"]
            missing = [key for key in required if key not in manifest]
            if missing:
                gates.append(
                    GateResult(
                        gate_id="T00",
                        status="FAIL",
                        reason=f"manifest missing keys: {missing}",
                        evidence={**t00_evidence, "missing": missing},
                    )
                )
            else:
                gates.append(
                    GateResult(
                        gate_id="T00",
                        status="PASS",
                        reason="manifest exists and contains required keys",
                        evidence=t00_evidence,
                    )
                )
        except Exception as exc:
            gates.append(
                GateResult(
                    gate_id="T00",
                    status="FAIL",
                    reason=f"manifest parse error: {exc}",
                    evidence=t00_evidence,
                )
            )

    if run_t01:
        evidence = _run_shell(t01_command, timeout_sec=t01_timeout_sec)
        status = "PASS" if evidence["returncode"] == 0 else "FAIL"
        reason = "runtime contract test passed" if status == "PASS" else "runtime contract command failed"
        gates.append(GateResult("T01", status, reason, evidence))
    else:
        gates.append(
            GateResult(
                "T01",
                "SKIP",
                "t01 execution disabled by --skip-t01",
                {"command": t01_command},
            )
        )

    if t02_baseline and t02_provider:
        lhs = _load_json_or_jsonl(t02_baseline)
        rhs = _load_json_or_jsonl(t02_provider)
        lhs_ap = _extract_ap_metrics(lhs)
        rhs_ap = _extract_ap_metrics(rhs)
        max_delta, per_key = _ap_delta(lhs_ap, rhs_ap)
        status = "PASS" if max_delta <= t02_ap_threshold else "FAIL"
        gates.append(
            GateResult(
                "T02",
                status,
                f"max AP delta={max_delta:.6g}, threshold={t02_ap_threshold}",
                {
                    "baseline": str(t02_baseline),
                    "provider": str(t02_provider),
                    "baseline_ap": lhs_ap,
                    "provider_ap": rhs_ap,
                    "delta": per_key,
                },
            )
        )
    else:
        status = "FAIL" if strict else "SKIP"
        gates.append(
            GateResult(
                "T02",
                status,
                "missing t02 inputs (--t02-baseline/--t02-provider)",
                {"baseline": str(t02_baseline) if t02_baseline else None, "provider": str(t02_provider) if t02_provider else None},
            )
        )

    if t03_offline and t03_online:
        lhs = _load_json_or_jsonl(t03_offline)
        rhs = _load_json_or_jsonl(t03_online)
        lhs_ap = _extract_ap_metrics(lhs)
        rhs_ap = _extract_ap_metrics(rhs)
        lhs_pose = _extract_pose_metrics(lhs)
        rhs_pose = _extract_pose_metrics(rhs)
        max_ap_delta, ap_delta = _ap_delta(lhs_ap, rhs_ap)
        max_pose_delta, pose_delta = _pose_delta(lhs_pose, rhs_pose)
        status = "PASS" if (max_ap_delta <= t03_ap_threshold and max_pose_delta <= t03_pose_threshold) else "FAIL"
        gates.append(
            GateResult(
                "T03",
                status,
                (
                    f"max AP delta={max_ap_delta:.6g} (thr={t03_ap_threshold}), "
                    f"max pose delta={max_pose_delta:.6g} (thr={t03_pose_threshold})"
                ),
                {
                    "offline": str(t03_offline),
                    "online": str(t03_online),
                    "offline_ap": lhs_ap,
                    "online_ap": rhs_ap,
                    "ap_delta": ap_delta,
                    "offline_pose": lhs_pose,
                    "online_pose": rhs_pose,
                    "pose_delta": pose_delta,
                },
            )
        )
    else:
        status = "FAIL" if strict else "SKIP"
        gates.append(
            GateResult(
                "T03",
                status,
                "missing t03 inputs (--t03-offline/--t03-online)",
                {"offline": str(t03_offline) if t03_offline else None, "online": str(t03_online) if t03_online else None},
            )
        )

    leak_regexes = [re.compile(p) for p in leak_patterns]
    oracle_re = re.compile(oracle_allow_pattern)
    audit_files = _expand_paths(audit_patterns)
    hits: List[Dict[str, Any]] = []
    for path in audit_files:
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        for line_idx, line in enumerate(lines, 1):
            for pattern in leak_regexes:
                if not pattern.search(line):
                    continue
                is_oracle = bool(oracle_re.search(str(path))) or bool(oracle_re.search(line))
                hits.append(
                    {
                        "file": str(path),
                        "line": line_idx,
                        "pattern": pattern.pattern,
                        "allowed_oracle": is_oracle,
                        "snippet": line[:240],
                    }
                )

    non_oracle_hits = [hit for hit in hits if not hit["allowed_oracle"]]
    if not audit_files:
        status = "FAIL" if strict else "SKIP"
        reason = "no audit files matched"
    elif non_oracle_hits:
        status = "FAIL"
        reason = f"found {len(non_oracle_hits)} non-oracle GT leakage hits"
    else:
        status = "PASS"
        reason = "no GT leakage hit in non-oracle files"
    gates.append(
        GateResult(
            "T04",
            status,
            reason,
            {
                "run_id": run_id,
                "audit_file_count": len(audit_files),
                "audit_files": [str(p) for p in audit_files],
                "total_hits": len(hits),
                "non_oracle_hits": non_oracle_hits,
                "oracle_pattern": oracle_allow_pattern,
                "leak_patterns": list(leak_patterns),
            },
        )
    )

    # T05: fairness diff-check against a frozen reference manifest.
    if t05_reference_manifest is not None:
        if t05_reference_manifest.exists() and manifest_path.exists():
            cur = json.loads(manifest_path.read_text(encoding="utf-8"))
            ref = json.loads(t05_reference_manifest.read_text(encoding="utf-8"))
            whitelist = list(t05_whitelist or [])
            cmp_info = _compare_manifests_for_t05(cur, ref, whitelist)
            t05_status = "PASS" if int(cmp_info.get("mismatch_count", 0)) == 0 else "FAIL"
            gates.append(
                GateResult(
                    "T05",
                    t05_status,
                    "manifest fairness diff-check",
                    {
                        "reference_manifest": str(t05_reference_manifest),
                        "current_manifest": str(manifest_path),
                        **cmp_info,
                    },
                )
            )
        else:
            t05_status = "SKIP"
            gates.append(
                GateResult(
                    "T05",
                    t05_status,
                    "missing reference/current manifest for T05",
                    {
                        "reference_manifest": str(t05_reference_manifest),
                        "current_manifest": str(manifest_path),
                    },
                )
            )
    else:
        t05_status = "SKIP"
        gates.append(
            GateResult(
                "T05",
                t05_status,
                "missing --t05-reference-manifest",
                {},
            )
        )

    # T06: GPU residency check from results rows.
    if t06_results is not None and t06_results.exists():
        rows = _read_jsonl_rows(t06_results)
        bad_fallback = []
        missing_timing_rows = 0
        for idx, row in enumerate(rows):
            timing_objs = _extract_timing_objects(row)
            if not timing_objs:
                missing_timing_rows += 1
                continue
            for timing in timing_objs:
                cfc = _safe_int(timing.get("cpu_fallback_count"))
                if cfc is not None and cfc > 0:
                    bad_fallback.append({"row": idx + 1, "cpu_fallback_count": cfc})
        if bad_fallback:
            t06_status = "FAIL"
            t06_reason = "cpu_fallback_count > 0 detected"
        elif rows and missing_timing_rows == len(rows):
            t06_status = "SKIP"
            t06_reason = "timing payload missing in all rows"
        else:
            t06_status = "PASS"
            t06_reason = "no mandatory CPU fallback in timing payload"
        gates.append(
            GateResult(
                "T06",
                t06_status,
                t06_reason,
                {
                    "results": str(t06_results),
                    "row_count": len(rows),
                    "missing_timing_rows": missing_timing_rows,
                    "bad_fallback": bad_fallback[:50],
                },
            )
        )
    else:
        t06_status = "SKIP"
        gates.append(
            GateResult(
                "T06",
                t06_status,
                "missing --t06-results",
                {"results": str(t06_results) if t06_results else None},
            )
        )

    # T07: throughput gain (soft gate).
    if (
        t07_reference_results is not None
        and t07_reference_results.exists()
        and t07_candidate_results is not None
        and t07_candidate_results.exists()
    ):
        ref = _load_json_or_jsonl(t07_reference_results)
        cand = _load_json_or_jsonl(t07_candidate_results)
        ref_fps = _safe_float(ref.get("mean_infer_fps") if "mean_infer_fps" in ref else ref.get("infer_fps"))
        cand_fps = _safe_float(cand.get("mean_infer_fps") if "mean_infer_fps" in cand else cand.get("infer_fps"))
        if ref_fps is None or cand_fps is None or ref_fps <= 0:
            t07_status = "SKIP"
            t07_reason = "missing fps metrics"
            ratio = None
        else:
            ratio = float(cand_fps / ref_fps)
            t07_status = "PASS" if ratio >= float(t07_min_gain) else "FAIL"
            t07_reason = "candidate/reference fps ratio"
        gates.append(
            GateResult(
                "T07",
                t07_status,
                t07_reason,
                {
                    "reference_results": str(t07_reference_results),
                    "candidate_results": str(t07_candidate_results),
                    "reference_fps": ref_fps,
                    "candidate_fps": cand_fps,
                    "ratio": ratio,
                    "min_gain": float(t07_min_gain),
                },
            )
        )
    else:
        gates.append(
            GateResult(
                "T07",
                "SKIP",
                "missing --t07-reference-results/--t07-candidate-results",
                {
                    "reference_results": str(t07_reference_results) if t07_reference_results else None,
                    "candidate_results": str(t07_candidate_results) if t07_candidate_results else None,
                },
            )
        )

    # T08: ranking stability top1/top2 by AP50 (soft gate).
    if (
        t08_reference_results is not None
        and t08_reference_results.exists()
        and t08_candidate_results is not None
        and t08_candidate_results.exists()
    ):
        ref_rows = _read_jsonl_rows(t08_reference_results)
        cand_rows = _read_jsonl_rows(t08_candidate_results)
        ref_top = _topk_methods_by_ap50(ref_rows, k=2)
        cand_top = _topk_methods_by_ap50(cand_rows, k=2)
        stable = bool(ref_top) and bool(cand_top) and ref_top[:2] == cand_top[:2]
        gates.append(
            GateResult(
                "T08",
                "PASS" if stable else "FAIL",
                "top-2 AP50 ranking stability",
                {
                    "reference_results": str(t08_reference_results),
                    "candidate_results": str(t08_candidate_results),
                    "reference_top2": ref_top,
                    "candidate_top2": cand_top,
                },
            )
        )
    else:
        gates.append(
            GateResult(
                "T08",
                "SKIP",
                "missing --t08-reference-results/--t08-candidate-results",
                {
                    "reference_results": str(t08_reference_results) if t08_reference_results else None,
                    "candidate_results": str(t08_candidate_results) if t08_candidate_results else None,
                },
            )
        )

    # T09: bound sanity check.
    if t09_results is not None and t09_results.exists():
        rows = _read_jsonl_rows(t09_results)
        buckets = {
            "single_only": 0,
            "fusion_only_non_gt": 0,
            "fusion_only_gt": 0,
            "register_and_fuse": 0,
        }
        for row in rows:
            bucket = _classify_bound_bucket(row)
            if bucket in buckets:
                buckets[bucket] += 1
        missing_buckets = [name for name, cnt in buckets.items() if cnt <= 0]
        t09_status = "PASS" if not missing_buckets else ("FAIL" if strict else "SKIP")
        gates.append(
            GateResult(
                "T09",
                t09_status,
                "bound sanity coverage",
                {
                    "results": str(t09_results),
                    "bucket_counts": buckets,
                    "missing_buckets": missing_buckets,
                },
            )
        )
    else:
        t09_status = "SKIP"
        gates.append(
            GateResult(
                "T09",
                t09_status,
                "missing --t09-results",
                {"results": str(t09_results) if t09_results else None},
            )
        )

    # T10: rollback command smoke.
    if t10_rollback_command:
        t10_evidence = _run_shell(t10_rollback_command, timeout_sec=int(t10_timeout_sec))
        t10_status = "PASS" if int(t10_evidence.get("returncode", 1)) == 0 else "FAIL"
        gates.append(
            GateResult(
                "T10",
                t10_status,
                "rollback command execution",
                t10_evidence,
            )
        )
    else:
        t10_status = "SKIP"
        gates.append(
            GateResult(
                "T10",
                t10_status,
                "missing --t10-rollback-command",
                {},
            )
        )

    return gates


def _write_gate_report_markdown(path: Path, run_id: str, manifest_path: Path, gates: Sequence[GateResult]) -> None:
    hard_gates = {"T00", "T01", "T02", "T03", "T04", "T05", "T06", "T09", "T10"}
    hard_failed = [g.gate_id for g in gates if g.gate_id in hard_gates and g.status == "FAIL"]
    summary = "PASS" if not hard_failed else "FAIL"
    lines: List[str] = []
    lines.append(f"# Benchmark Gate Report ({run_id})")
    lines.append("")
    lines.append(f"- generated_at_utc: {_utc_now()}")
    lines.append(f"- repo_root: `{REPO_ROOT}`")
    lines.append(f"- manifest: `{manifest_path}`")
    lines.append(f"- overall_status: **{summary}**")
    lines.append(f"- hard_failed: {', '.join(hard_failed) if hard_failed else 'none'}")
    lines.append("")
    lines.append("| Gate | Status | Reason |")
    lines.append("| --- | --- | --- |")
    for gate in gates:
        reason = gate.reason.replace("|", "\\|")
        lines.append(f"| {gate.gate_id} | {gate.status} | {reason} |")
    lines.append("")
    for gate in gates:
        lines.append(f"## {gate.gate_id} evidence")
        lines.append("```json")
        lines.append(json.dumps(gate.evidence, ensure_ascii=True, indent=2))
        lines.append("```")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_gate_report_json(path: Path, run_id: str, manifest_path: Path, gates: Sequence[GateResult]) -> None:
    hard_gates = {"T00", "T01", "T02", "T03", "T04", "T05", "T06", "T09", "T10"}
    hard_failed = [g.gate_id for g in gates if g.gate_id in hard_gates and g.status == "FAIL"]
    payload = {
        "run_id": run_id,
        "generated_at_utc": _utc_now(),
        "repo_root": str(REPO_ROOT),
        "manifest": str(manifest_path),
        "overall_status": "PASS" if not hard_failed else "FAIL",
        "hard_failed": hard_failed,
        "gates": [
            {
                "gate_id": g.gate_id,
                "status": g.status,
                "reason": g.reason,
                "evidence": g.evidence,
            }
            for g in gates
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def consolidate_results(
    *,
    run_id: str,
    sources: Sequence[Path],
    output_path: Path,
    dedupe_key: str,
    strict: bool,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for source in sources:
        if not source.exists():
            if strict:
                raise FileNotFoundError(source)
            continue
        for line_idx, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            obj = json.loads(line)
            obj.setdefault("run_id", run_id)
            obj.setdefault("source_file", str(source))
            obj.setdefault("source_line", line_idx)
            rows.append(obj)

    if dedupe_key:
        dedup: Dict[Any, Dict[str, Any]] = {}
        for row in rows:
            key = row.get(dedupe_key)
            if key is None:
                if strict:
                    raise ValueError(f"Missing dedupe key '{dedupe_key}' in row: {row}")
                continue
            dedup[key] = row
        rows = list(dedup.values())

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=True) + "\n")

    return {
        "run_id": run_id,
        "output": str(output_path),
        "row_count": len(rows),
        "sources": [str(p) for p in sources],
        "dedupe_key": dedupe_key,
    }


def _manifest_cmd(args: argparse.Namespace) -> int:
    out_path = _abs_path(args.output or f"outputs/benchmark_manifest_{args.run_id}.json")
    extras = _parse_kv_pairs(args.extra)
    manifest = build_manifest(
        run_id=args.run_id,
        dataset_split=args.dataset_split,
        runtime_mode=args.runtime_mode,
        solver_backend=args.solver_backend,
        fusion_method=args.fusion_method,
        noise_schedule=args.noise_schedule,
        dropout_schedule=args.dropout_schedule,
        model_dirs=args.model_dir,
        config_files=args.config,
        checkpoint_files=args.checkpoint,
        script_files=args.script,
        stage1_files=args.stage1_result,
        result_sources=args.result_source,
        extras=extras,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2), encoding="utf-8")
    print(f"[manifest] wrote {out_path}")
    return 0


def _gate_cmd(args: argparse.Namespace) -> int:
    manifest_path = _abs_path(args.manifest or f"outputs/benchmark_manifest_{args.run_id}.json")
    report_path = _abs_path(args.output or f"outputs/benchmark_gate_report_{args.run_id}.md")
    report_json_path = report_path.with_suffix(".json")

    default_audit = [f"outputs/{args.run_id}*.jsonl", f"outputs/{args.run_id}*.md"]
    audit_patterns = args.audit_glob if args.audit_glob else default_audit

    gates = evaluate_gates(
        run_id=args.run_id,
        manifest_path=manifest_path,
        t01_command=args.t01_command,
        t01_timeout_sec=args.t01_timeout_sec,
        run_t01=not args.skip_t01,
        t02_baseline=_abs_path(args.t02_baseline) if args.t02_baseline else None,
        t02_provider=_abs_path(args.t02_provider) if args.t02_provider else None,
        t03_offline=_abs_path(args.t03_offline) if args.t03_offline else None,
        t03_online=_abs_path(args.t03_online) if args.t03_online else None,
        t02_ap_threshold=args.t02_ap_threshold,
        t03_ap_threshold=args.t03_ap_threshold,
        t03_pose_threshold=args.t03_pose_threshold,
        audit_patterns=audit_patterns,
        leak_patterns=args.leak_pattern,
        oracle_allow_pattern=args.oracle_pattern,
        strict=not args.allow_missing,
        t05_reference_manifest=_abs_path(args.t05_reference_manifest)
        if args.t05_reference_manifest
        else None,
        t05_whitelist=args.t05_whitelist,
        t06_results=_abs_path(args.t06_results) if args.t06_results else None,
        t07_reference_results=_abs_path(args.t07_reference_results)
        if args.t07_reference_results
        else None,
        t07_candidate_results=_abs_path(args.t07_candidate_results)
        if args.t07_candidate_results
        else None,
        t07_min_gain=args.t07_min_gain,
        t08_reference_results=_abs_path(args.t08_reference_results)
        if args.t08_reference_results
        else None,
        t08_candidate_results=_abs_path(args.t08_candidate_results)
        if args.t08_candidate_results
        else None,
        t09_results=_abs_path(args.t09_results) if args.t09_results else None,
        t10_rollback_command=args.t10_rollback_command,
        t10_timeout_sec=args.t10_timeout_sec,
    )

    _write_gate_report_markdown(report_path, args.run_id, manifest_path, gates)
    _write_gate_report_json(report_json_path, args.run_id, manifest_path, gates)
    failed = [g for g in gates if g.status == "FAIL"]
    print(f"[gate-report] wrote {report_path}")
    print(f"[gate-report] wrote {report_json_path}")
    if failed:
        print("[gate-report] failed gates:", ", ".join(g.gate_id for g in failed))
        return 2
    return 0


def _consolidate_cmd(args: argparse.Namespace) -> int:
    out_path = _abs_path(args.output or f"outputs/benchmark_results_{args.run_id}.jsonl")
    source_paths = [_abs_path(path) for path in args.source]
    summary = consolidate_results(
        run_id=args.run_id,
        sources=source_paths,
        output_path=out_path,
        dedupe_key=args.dedupe_key,
        strict=not args.allow_missing,
    )
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate benchmark manifest / gate report / consolidated results for HEAL pose+fusion runs."
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True

    p_manifest = subparsers.add_parser("manifest", help="Generate outputs/benchmark_manifest_RUNID.json")
    p_manifest.add_argument("--run-id", required=True)
    p_manifest.add_argument("--dataset-split", required=True)
    p_manifest.add_argument("--runtime-mode")
    p_manifest.add_argument("--solver-backend")
    p_manifest.add_argument("--fusion-method")
    p_manifest.add_argument("--noise-schedule")
    p_manifest.add_argument("--dropout-schedule")
    p_manifest.add_argument("--model-dir", action="append", default=[])
    p_manifest.add_argument("--config", action="append", default=[])
    p_manifest.add_argument("--checkpoint", action="append", default=[])
    p_manifest.add_argument("--script", action="append", default=[])
    p_manifest.add_argument("--stage1-result", action="append", default=[])
    p_manifest.add_argument("--result-source", action="append", default=[])
    p_manifest.add_argument("--extra", action="append", default=[])
    p_manifest.add_argument("--output")
    p_manifest.set_defaults(func=_manifest_cmd)

    p_gate = subparsers.add_parser("gate-report", help="Run T00-T10 gate checks and generate markdown/json report")
    p_gate.add_argument("--run-id", required=True)
    p_gate.add_argument("--manifest")
    p_gate.add_argument("--output")
    p_gate.add_argument("--skip-t01", action="store_true", help="Skip executing T01 command")
    p_gate.add_argument("--t01-command", default=DEFAULT_T01_COMMAND)
    p_gate.add_argument("--t01-timeout-sec", type=int, default=900)
    p_gate.add_argument("--t02-baseline")
    p_gate.add_argument("--t02-provider")
    p_gate.add_argument("--t03-offline")
    p_gate.add_argument("--t03-online")
    p_gate.add_argument("--t02-ap-threshold", type=float, default=1e-4)
    p_gate.add_argument("--t03-ap-threshold", type=float, default=1e-4)
    p_gate.add_argument("--t03-pose-threshold", type=float, default=1e-3)
    p_gate.add_argument(
        "--audit-glob",
        action="append",
        default=[],
        help="Glob (repo-relative) for T04 audit files. Defaults to outputs/<run_id>*.jsonl and outputs/<run_id>*.md",
    )
    p_gate.add_argument("--leak-pattern", action="append", default=DEFAULT_GT_PATTERNS)
    p_gate.add_argument("--oracle-pattern", default=DEFAULT_ALLOWED_ORACLE_PATTERN)
    p_gate.add_argument(
        "--allow-missing",
        action="store_true",
        help="Do not fail missing optional gate inputs (mark SKIP instead)",
    )
    p_gate.add_argument("--t05-reference-manifest")
    p_gate.add_argument(
        "--t05-whitelist",
        action="append",
        default=list(DEFAULT_T05_WHITELIST),
        help="Whitelist field prefix for T05 fairness diff-check; can be repeated.",
    )
    p_gate.add_argument("--t06-results")
    p_gate.add_argument("--t07-reference-results")
    p_gate.add_argument("--t07-candidate-results")
    p_gate.add_argument("--t07-min-gain", type=float, default=1.3)
    p_gate.add_argument("--t08-reference-results")
    p_gate.add_argument("--t08-candidate-results")
    p_gate.add_argument("--t09-results")
    p_gate.add_argument("--t10-rollback-command")
    p_gate.add_argument("--t10-timeout-sec", type=int, default=120)
    p_gate.set_defaults(func=_gate_cmd)

    p_cons = subparsers.add_parser("consolidate-results", help="Merge result jsonl files into benchmark_results_RUNID.jsonl")
    p_cons.add_argument("--run-id", required=True)
    p_cons.add_argument("--source", action="append", required=True)
    p_cons.add_argument("--dedupe-key", default="job_id")
    p_cons.add_argument("--allow-missing", action="store_true")
    p_cons.add_argument("--output")
    p_cons.set_defaults(func=_consolidate_cmd)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
