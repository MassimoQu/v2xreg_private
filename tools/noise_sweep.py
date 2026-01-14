#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List

from calib.config import load_config
from calib.pipelines.object_level import ObjectLevelPipeline


def _parse_floats(raw: str) -> List[float]:
    values = []
    for token in raw.split(','):
        token = token.strip()
        if not token:
            continue
        values.append(float(token))
    if not values:
        values.append(0.0)
    return values


def run_sweep(args):
    translations = _parse_floats(args.translations)
    rotations = _parse_floats(args.rotations)
    out_dir = Path(args.output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for t_bias in translations:
        for r_bias in rotations:
            cfg = load_config(args.config)
            if args.core_components:
                cfg.matching.core_components = list(args.core_components)
            if args.max_samples is not None:
                cfg.data.max_samples = int(args.max_samples)
            cfg.data.noise = {
                'pos_std': args.pos_std,
                'rot_std': args.rot_std,
                'pos_mean': args.pos_mean,
                'rot_mean': args.rot_mean,
                'offset': [t_bias, 0.0, 0.0, 0.0, 0.0, r_bias],
                'target': args.target,
            }
            tag = f"{args.tag_prefix}_pos{t_bias:.2f}_rot{r_bias:.1f}"
            cfg.output.tag = tag.replace('-', 'n').replace('.', 'p')
            pipeline = ObjectLevelPipeline(cfg)
            summary = pipeline.run()
            results.append(
                {
                    'translation_bias_m': t_bias,
                    'rotation_bias_deg': r_bias,
                    'pos_std': args.pos_std,
                    'rot_std': args.rot_std,
                    'output_tag': cfg.output.tag,
                    'summary': summary,
                }
            )
    output_path = out_dir / f"{args.tag_prefix}_noise_results.json"
    with output_path.open('w', encoding='utf-8') as f:
        json.dump(
            {
                'config': args.config,
                'target': args.target,
                'translations': translations,
                'rotations': rotations,
                'pos_std': args.pos_std,
                'rot_std': args.rot_std,
                'results': results,
            },
            f,
            indent=2,
        )
    return results


def build_argparser():
    parser = argparse.ArgumentParser(description='Sweep translation/rotation bias for calibration robustness')
    parser.add_argument('--config', required=True, help='Pipeline config path')
    parser.add_argument('--tag-prefix', required=True, help='Prefix for output tags')
    parser.add_argument('--translations', default='0.0', help='Comma-separated translation biases (meters along x)')
    parser.add_argument('--rotations', default='0.0', help='Comma-separated yaw biases (degrees)')
    parser.add_argument('--pos-std', type=float, default=0.0, help='Gaussian std for translation jitter (m)')
    parser.add_argument('--rot-std', type=float, default=0.0, help='Gaussian std for yaw jitter (deg)')
    parser.add_argument('--pos-mean', type=float, default=0.0, help='Mean translation bias (m)')
    parser.add_argument('--rot-mean', type=float, default=0.0, help='Mean yaw bias (deg)')
    parser.add_argument('--target', default='vehicle', help='Agent to perturb: vehicle/infra/both')
    parser.add_argument(
        '--core-components',
        nargs='+',
        help='Override matching.core_components (default: keep config)',
    )
    parser.add_argument('--max-samples', type=int, help='Limit dataset samples per run')
    parser.add_argument(
        '--output-dir',
        default='outputs/factor_sweeps',
        help='Directory where JSON summary will be saved',
    )
    return parser


def main():
    parser = build_argparser()
    args = parser.parse_args()
    run_sweep(args)


if __name__ == '__main__':
    main()
