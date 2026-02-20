#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calib.config import load_config
from calib.data.dataset_manager import DatasetManager


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Precompute and cache image descriptors.")
    p.add_argument("--config", required=True, help="Pipeline YAML path.")
    p.add_argument("--cache-dir", required=True, help="Directory to store descriptor cache files.")
    p.add_argument("--start-index", type=int, default=None, help="Optional start index for sharded cache build.")
    p.add_argument("--max-samples", type=int, default=None, help="Optional max samples for sharded cache build.")
    p.add_argument("--progress", type=int, default=50, help="Progress print interval.")
    p.add_argument("--no-cache-read", action="store_true", help="Disable reading existing cache files.")
    p.add_argument("--no-cache-write", action="store_true", help="Disable writing cache files.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    cfg.data.use_image_descriptors = True
    cfg.data.image_descriptor = dict(cfg.data.image_descriptor or {})
    cfg.data.image_descriptor["cache_dir"] = str(args.cache_dir)
    cfg.data.image_descriptor["cache_read"] = not args.no_cache_read
    cfg.data.image_descriptor["cache_write"] = not args.no_cache_write
    if args.start_index is not None:
        cfg.data.start_index = int(args.start_index)
    if args.max_samples is not None:
        cfg.data.max_samples = int(args.max_samples)

    manager = DatasetManager(cfg.data)
    total = 0
    for sample in manager.samples():
        total += 1
        if args.progress and total % args.progress == 0:
            print(f"[descriptor-cache] processed {total} samples (index={sample.index})")
    print(f"[descriptor-cache] done: {total} samples")


if __name__ == "__main__":
    main()
