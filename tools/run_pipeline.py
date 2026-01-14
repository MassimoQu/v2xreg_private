#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calib.config import load_config
from calib.pipelines.object_level import ObjectLevelPipeline


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run a single pipeline config and write outputs.")
    p.add_argument("--config", required=True, help="Pipeline YAML path.")
    p.add_argument("--tag", required=True, help="Output tag (directory name under root_dir).")
    p.add_argument("--root-dir", default=None, help="Optional override for output.root_dir.")
    p.add_argument("--max-samples", type=int, default=None, help="Optional cap on number of samples.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    cfg.output.tag = str(args.tag)
    if args.root_dir is not None:
        cfg.output.root_dir = str(args.root_dir)
    if args.max_samples is not None:
        cfg.data.max_samples = int(args.max_samples)
    result = ObjectLevelPipeline(cfg).run()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()


