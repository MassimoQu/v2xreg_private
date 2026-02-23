#!/usr/bin/env python3
"""
Merge sharded OPV2V lidar_reg cache JSONs into a single cache file.

Shard files are produced by tools/precompute_opv2v_lidar_reg_cache.py with:
  --num-shards N --shard-id i
and default naming:
  data/OPV2V/lidar_reg_cache/shards/opv2v_test_<global_method>_shard{i}of{N}.json

Output format matches Stage1LidarRegPoseCorrector cache contract:
  {"meta": {...}, "pairs": {...}}
"""

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _load_cache(path: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    obj: Dict[str, Any] = {}
    pairs: Dict[str, Any] = {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {}, {}
    if not isinstance(obj, dict):
        return {}, {}
    raw_pairs = obj.get("pairs")
    if isinstance(raw_pairs, dict):
        pairs = raw_pairs
    return obj, pairs


def _json_dumps(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True, help="Output merged cache path.")
    p.add_argument("--in-dir", type=Path, default=None, help="Directory containing shard jsons.")
    p.add_argument(
        "--pattern",
        type=str,
        default="opv2v_test_*_shard*of*.json",
        help="Glob pattern used under --in-dir.",
    )
    p.add_argument("--inputs", nargs="*", default=None, help="Explicit shard json paths (overrides --in-dir).")
    p.add_argument("--strict", action="store_true", help="Fail on conflicting duplicate keys.")
    args = p.parse_args()

    inputs: List[Path] = []
    if args.inputs:
        inputs = [Path(x) for x in args.inputs if str(x).strip()]
    elif args.in_dir:
        inputs = sorted(Path(args.in_dir).glob(str(args.pattern)))
    else:
        raise SystemExit("Provide either --inputs ... or --in-dir <dir>.")

    if not inputs:
        raise SystemExit("No shard files found.")

    merged_pairs: Dict[str, Any] = {}
    source_meta: List[Dict[str, Any]] = []

    global_method: Optional[str] = None
    cfg_sig: Optional[str] = None
    num_shards: Optional[int] = None

    conflicts: List[str] = []

    for path in inputs:
        obj, pairs = _load_cache(path)
        if not pairs:
            continue
        meta = obj.get("meta") if isinstance(obj.get("meta"), dict) else {}
        source_meta.append({"path": str(path), "meta": meta})

        gm = meta.get("global_method") if isinstance(meta, dict) else None
        if gm is not None:
            if global_method is None:
                global_method = str(gm)
            elif str(gm) != str(global_method):
                raise SystemExit(f"global_method mismatch: {path} has {gm}, expected {global_method}")

        ns = meta.get("num_shards") if isinstance(meta, dict) else None
        if ns is not None:
            try:
                ns_i = int(ns)
            except Exception:
                ns_i = None
            if ns_i is not None:
                if num_shards is None:
                    num_shards = ns_i
                elif int(num_shards) != int(ns_i):
                    raise SystemExit(f"num_shards mismatch: {path} has {ns_i}, expected {num_shards}")

        cfg = meta.get("cfg") if isinstance(meta, dict) else None
        if isinstance(cfg, dict):
            sig = _json_dumps(cfg)
            if cfg_sig is None:
                cfg_sig = sig
            elif sig != cfg_sig:
                raise SystemExit(f"cfg mismatch (likely different precompute settings): {path}")

        for k, v in pairs.items():
            if k not in merged_pairs:
                merged_pairs[k] = v
                continue
            if _json_dumps(merged_pairs[k]) != _json_dumps(v):
                conflicts.append(k)
                if args.strict:
                    raise SystemExit(f"conflict on key {k} between shards (example file: {path})")

    out_meta: Dict[str, Any] = {
        "merged_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "global_method": global_method,
        "num_shards": num_shards,
        "sources": [str(p) for p in inputs],
        "source_meta": source_meta[:20],  # keep it small
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({"meta": out_meta, "pairs": merged_pairs}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    msg = f"Wrote {args.out} (pairs={len(merged_pairs)})"
    if conflicts:
        msg += f" with conflicts={len(conflicts)} (kept first)"
    print(msg)


if __name__ == "__main__":
    main()

