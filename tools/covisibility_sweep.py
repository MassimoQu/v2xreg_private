#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Optional

from calib.config import load_config
from calib.pipelines.object_level import ObjectLevelPipeline


def _parse_limits(raw: str) -> List[Optional[int]]:
    values = []
    for part in raw.split(','):
        token = part.strip().lower()
        if not token:
            continue
        if token in {'inf', 'none', 'max'}:
            values.append(None)
        else:
            values.append(int(token))
    if not values:
        raise ValueError('No limit values provided')
    return values


def _format_limit(value: Optional[int]) -> str:
    return 'inf' if value in (None, 0) else str(value)


def run_sweep(args) -> List[dict]:
    limits = _parse_limits(args.limits)
    results = []
    out_dir = Path(args.output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    for value in limits:
        cfg = load_config(args.config)
        limit = None if value in (None, 0) else max(1, int(value))
        if args.core_components:
            cfg.matching.core_components = list(args.core_components)
        cfg.matching.max_retained_matches = limit
        if args.topk is not None:
            cfg.filters.top_k = int(args.topk)
        else:
            cfg.filters.top_k = 0 if value in (None, 0) else max(1, int(value))
        if args.max_samples is not None:
            cfg.data.max_samples = int(args.max_samples)
        tag = f"{args.tag_prefix}_k{_format_limit(value)}"
        cfg.output.tag = tag
        pipeline = ObjectLevelPipeline(cfg)
        summary = pipeline.run()
        record = {
            'limit': _format_limit(value),
            'max_retained_matches': limit,
            'filters_top_k': cfg.filters.top_k,
            'output_tag': tag,
            'summary': summary,
        }
        results.append(record)
    output_json = out_dir / f"{args.tag_prefix}_results.json"
    with output_json.open('w', encoding='utf-8') as f:
        json.dump(
            {
                'config': args.config,
                'limits': [_format_limit(v) for v in limits],
                'core_components': args.core_components or 'config',
                'tag_prefix': args.tag_prefix,
                'results': results,
            },
            f,
            indent=2,
        )
    return results


def build_argparser():
    parser = argparse.ArgumentParser(description='Run covisibility sweeps for V2X calibration')
    parser.add_argument('--config', required=True, help='Path to pipeline config YAML')
    parser.add_argument(
        '--limits',
        required=True,
        help='Comma-separated list of max retained matches per frame (use "inf" for unlimited)',
    )
    parser.add_argument('--tag-prefix', required=True, help='Prefix for output/summary tagging')
    parser.add_argument(
        '--core-components',
        nargs='+',
        help='Override matching.core_components (default: keep config value)',
    )
    parser.add_argument(
        '--topk',
        type=int,
        help='Force filters.top_k to this value instead of tying it to each limit',
    )
    parser.add_argument(
        '--output-dir',
        default='outputs/factor_sweeps',
        help='Directory to store sweep JSON summaries',
    )
    parser.add_argument(
        '--max-samples',
        type=int,
        help='Override data.max_samples to shorten each run',
    )
    return parser


def main():
    parser = build_argparser()
    args = parser.parse_args()
    run_sweep(args)


if __name__ == '__main__':
    main()
