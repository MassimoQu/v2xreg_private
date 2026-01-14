#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List

from calib.config import load_config
from calib.pipelines.object_level import ObjectLevelPipeline


def _parse_floats(raw: str) -> List[float]:
    values: List[float] = []
    for token in (raw or '').split(','):
        token = token.strip()
        if not token:
            continue
        values.append(float(token))
    return values


def run_sweep(args):
    descriptor_weights = _parse_floats(args.descriptor_weights) or [0.0]
    prior_weights = _parse_floats(args.prior_weights) or [0.0]
    min_sims = _parse_floats(args.min_sims) or [0.0]
    out_dir = Path(args.output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for desc_w in descriptor_weights:
        for prior_w in prior_weights:
            for min_sim in min_sims:
                cfg = load_config(args.config)
                if args.max_samples is not None:
                    cfg.data.max_samples = int(args.max_samples)
                cfg.matching.descriptor_seed = True
                if 'descriptor' not in (cfg.matching.strategy or []):
                    cfg.matching.strategy = list(cfg.matching.strategy or []) + ['descriptor']
                cfg.matching.descriptor_weight = float(desc_w)
                cfg.matching.prior_weight = float(prior_w)
                cfg.matching.descriptor_min_similarity = float(min_sim)
                if args.descriptor_metric:
                    cfg.matching.descriptor_metric = str(args.descriptor_metric)
                tag = f"{args.tag_prefix}_dw{desc_w:.2f}_pw{prior_w:.2f}_ms{min_sim:.2f}"
                cfg.output.tag = (
                    tag.replace('-', 'n')
                    .replace('.', 'p')
                    .replace('+', 'p')
                )
                pipeline = ObjectLevelPipeline(cfg)
                summary = pipeline.run()
                results.append(
                    {
                        'descriptor_weight': desc_w,
                        'prior_weight': prior_w,
                        'descriptor_min_similarity': min_sim,
                        'output_tag': cfg.output.tag,
                        'summary': summary,
                    }
                )

    output_path = out_dir / f"{args.tag_prefix}_midfusion_sweep.json"
    with output_path.open('w', encoding='utf-8') as f:
        json.dump(
            {
                'config': args.config,
                'descriptor_weights': descriptor_weights,
                'prior_weights': prior_weights,
                'min_sims': min_sims,
                'results': results,
            },
            f,
            indent=2,
        )
    return results


def build_argparser():
    parser = argparse.ArgumentParser(description='Sweep mid-fusion descriptor/prior weights.')
    parser.add_argument('--config', required=True, help='Pipeline config path')
    parser.add_argument('--tag-prefix', required=True, help='Prefix for output tags')
    parser.add_argument('--descriptor-weights', default='5.0', help='Comma-separated descriptor weights')
    parser.add_argument('--prior-weights', default='5.0', help='Comma-separated hint(prior) weights')
    parser.add_argument('--min-sims', default='0.1', help='Comma-separated descriptor_min_similarity values')
    parser.add_argument('--descriptor-metric', default=None, help='Override descriptor metric (cosine/l2)')
    parser.add_argument('--max-samples', type=int, help='Limit dataset samples per run')
    parser.add_argument(
        '--output-dir',
        default='outputs/midfusion_sweeps',
        help='Directory where JSON summary will be saved',
    )
    return parser


def main():
    parser = build_argparser()
    args = parser.parse_args()
    run_sweep(args)


if __name__ == '__main__':
    main()

