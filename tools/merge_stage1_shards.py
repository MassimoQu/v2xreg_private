#!/usr/bin/env python3
"""
Merge sharded stage1 cache exports (JSON dict shards) into a single stage1_boxes.json.

This is designed for the OPV2V per-CAV exporter which can run in parallel across GPUs:
  stage1_boxes_shardXXofYY.json  -> stage1_boxes.json
"""

import argparse
import json
from pathlib import Path


def _load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8", errors="ignore"))


def _expected_shard_name(shard_index, num_shards):
    return "stage1_boxes_shard{:02d}of{:02d}.json".format(int(shard_index), int(num_shards))


def main():
    ap = argparse.ArgumentParser(description="Merge stage1 cache shards into stage1_boxes.json")
    ap.add_argument("--shard-dir", type=Path, required=True, help="Directory containing shard JSONs.")
    ap.add_argument("--num-shards", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument(
        "--write-head200",
        action="store_true",
        help="Also write stage1_boxes_head200.json next to --out (deterministic first-200 keys).",
    )
    ap.add_argument("--head-n", type=int, default=200, help="Number of samples to keep for the head cache (default: 200).")
    ap.add_argument("--expected-samples", type=int, default=0)
    ap.add_argument("--require-contiguous-keys", action="store_true")
    args = ap.parse_args()

    if int(args.num_shards) <= 0:
        raise SystemExit("num_shards must be >= 1")

    merged = {}
    for i in range(int(args.num_shards)):
        shard_path = args.shard_dir / _expected_shard_name(i, int(args.num_shards))
        if not shard_path.exists():
            raise SystemExit("Missing shard: {}".format(shard_path))
        obj = _load_json(shard_path)
        if not isinstance(obj, dict):
            raise SystemExit("Shard must be a JSON dict: {} (got {})".format(shard_path, type(obj)))
        for k, v in obj.items():
            ks = str(k)
            if ks in merged:
                raise SystemExit("Duplicate sample key {} from shard {}".format(ks, shard_path))
            merged[ks] = v

    if int(args.expected_samples) > 0 and len(merged) != int(args.expected_samples):
        raise SystemExit(
            "sample_count_mismatch: expected={} actual={} (out={})".format(
                int(args.expected_samples), len(merged), args.out
            )
        )

    if args.require_contiguous_keys and merged:
        keys = set()
        bad = 0
        for k in merged.keys():
            try:
                keys.add(int(k))
            except Exception:
                bad += 1
        if bad:
            raise SystemExit("Non-integer sample keys found: {} (out={})".format(bad, args.out))
        max_k = max(keys)
        missing = [x for x in range(max_k + 1) if x not in keys]
        if missing:
            raise SystemExit("Missing sample keys: first_missing={}".format(missing[:20]))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(merged, sort_keys=True), encoding="utf-8")
    print("Wrote merged stage1 cache: {} (samples={})".format(args.out, len(merged)))

    if bool(args.write_head200):
        head_n = int(args.head_n)
        if head_n <= 0:
            raise SystemExit("--head-n must be >= 1 when --write-head200 is enabled")
        keys_sorted = sorted((int(k), str(k)) for k in merged.keys() if str(k).isdigit())
        head_keys = [ks for _ik, ks in keys_sorted[:head_n]]
        head = {k: merged[k] for k in head_keys}
        if args.out.name == "stage1_boxes.json":
            head_path = args.out.with_name(f"stage1_boxes_head{head_n}.json")
        else:
            stem = args.out.stem
            head_path = args.out.with_name(f"{stem}_head{head_n}{args.out.suffix}")
        head_path.write_text(json.dumps(head, sort_keys=True), encoding="utf-8")
        print("Wrote head cache: {} (samples={})".format(head_path, len(head)))


if __name__ == "__main__":
    main()
