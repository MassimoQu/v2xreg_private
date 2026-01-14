#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calib.config import load_config
from calib.pipelines.object_level import ObjectLevelPipeline


EXPERIMENTS: List[Dict] = [
    {
        'tag': 'dair_v2xreg_oiou_gt15',
        'description': 'V2X-Reg (oIoU) with GT boxes, top-15',
        'overrides': {
            'filters.top_k': 15,
            'matching.core_components': ['iou'],
        },
    },
    {
        'tag': 'dair_v2xregpp_gt_inf',
        'description': 'V2X-Reg++ with GT boxes, keep all boxes',
        'overrides': {
            'filters.top_k': 0,
            'matching.seed_top_k': 25,
        },
    },
    {
        'tag': 'dair_v2xregpp_gt25',
        'description': 'V2X-Reg++ with GT boxes, top-25',
        'overrides': {
            'filters.top_k': 25,
        },
    },
    {
        'tag': 'dair_v2xregpp_gt15',
        'description': 'V2X-Reg++ with GT boxes, top-15',
        'overrides': {
            'filters.top_k': 15,
        },
    },
    {
        'tag': 'dair_v2xregpp_gt10',
        'description': 'V2X-Reg++ with GT boxes, top-10',
        'overrides': {
            'filters.top_k': 10,
        },
    },
    {
        'tag': 'dair_v2xregpp_pp15',
        'description': 'V2X-Reg++ with PointPillars detections, top-15',
        'overrides': {
            'filters.top_k': 15,
            'data.use_detection': True,
            'data.detection_cache': 'data/DAIR-V2X/detected/detected_boxes_test.json',
        },
    },
    {
        'tag': 'dair_v2xregpp_pp15_robust',
        'description': 'V2X-Reg++ with PointPillars detections, robust SVD (outlier pruning), top-15',
        'overrides': {
            'filters.top_k': 15,
            'data.use_detection': True,
            'data.detection_cache': 'data/DAIR-V2X/detected/detected_boxes_test.json',
            'solver.max_iterations': 2,
            'matching.resolve_180_ambiguity': False,
        },
    },
    {
        'tag': 'dair_v2xregpp_pp15_robust_180',
        'description': 'V2X-Reg++ with PointPillars detections, robust SVD + 180 ambiguity resolution, top-15',
        'overrides': {
            'filters.top_k': 15,
            'data.use_detection': True,
            'data.detection_cache': 'data/DAIR-V2X/detected/detected_boxes_test.json',
            'solver.max_iterations': 2,
            'matching.resolve_180_ambiguity': True,
        },
    },
    {
        'tag': 'dair_v2xregpp_sc15',
        'description': 'V2X-Reg++ with SECOND detections, top-15',
        'overrides': {
            'filters.top_k': 15,
            'data.use_detection': True,
            'data.detection_cache': 'data/DAIR-V2X/detected/dairv2x-second_uncertainty/test/stage1_boxes.json',
        },
    },
    {
        'tag': 'dair_v2xregpp_sc15_robust',
        'description': 'V2X-Reg++ with SECOND detections, robust SVD (outlier pruning), top-15',
        'overrides': {
            'filters.top_k': 15,
            'data.use_detection': True,
            'data.detection_cache': 'data/DAIR-V2X/detected/dairv2x-second_uncertainty/test/stage1_boxes.json',
            'solver.max_iterations': 2,
            'matching.resolve_180_ambiguity': False,
        },
    },
    {
        'tag': 'dair_v2xregpp_sc15_robust_180',
        'description': 'V2X-Reg++ with SECOND detections, robust SVD + 180 ambiguity resolution, top-15',
        'overrides': {
            'filters.top_k': 15,
            'data.use_detection': True,
            'data.detection_cache': 'data/DAIR-V2X/detected/dairv2x-second_uncertainty/test/stage1_boxes.json',
            'solver.max_iterations': 2,
            'matching.resolve_180_ambiguity': True,
        },
    },
    {
        'tag': 'dair_v2xregpp_gt25_hsvd',
        'description': 'V2X-Reg++ GT top-25 with highest-score SVD (hSVD)',
        'overrides': {
            'filters.top_k': 25,
            'matching.filter_strategy': 'topRetained',
        },
    },
    {
        'tag': 'dair_v2xregpp_gt25_msvd',
        'description': 'V2X-Reg++ GT top-25 with mean SVD (mSVD)',
        'overrides': {
            'filters.top_k': 25,
            'matching.matches2extrinsic': 'evenSVD',
        },
    },
    {
        'tag': 'dair_v2xregpp_pp15_midfusion_bevdesc',
        'description': 'Mid-fusion: detections + BEV descriptors (descriptor-seeded + hint matching), top-15',
        'overrides': {
            'filters.top_k': 15,
            'data.use_detection': True,
            'data.detection_cache': 'data/DAIR-V2X/detected/veh_rsu_dual_bevdesc/stage1_boxes.json',
            'matching.strategy': ['category', 'core', 'descriptor'],
            'matching.descriptor_seed': True,
            'matching.descriptor_weight': 5.0,
            'matching.descriptor_metric': 'cosine',
            'matching.descriptor_min_similarity': 0.1,
            'matching.descriptor_max_pairs': 30,
            'matching.prior_weight': 5.0,
            'solver.max_iterations': 2,
            'solver.inlier_threshold_m': 1.25,
        },
    },
    {
        'tag': 'dair_v2xregpp_midfusion_bevpeaks',
        'description': 'Mid-fusion: BEV peak features (descriptor-seeded + hint matching)',
        'overrides': {
            'data.use_detection': False,
            'data.use_features': True,
            'data.feature_cache': 'data/DAIR-V2X/detected/veh_rsu_dual_bevpeaks/stage1_boxes.json',
            'filters.top_k': 64,
            'filters.priority_categories': ['feature'],
            'filters.min_confidence': 0.35,
            'matching.strategy': ['core', 'descriptor'],
            'matching.core_components': ['centerpoint_distance'],
            'matching.distance_thresholds': {'feature': 1.25},
            'matching.descriptor_seed': True,
            'matching.descriptor_weight': 3.0,
            'matching.descriptor_metric': 'cosine',
            'matching.descriptor_min_similarity': 0.2,
            'matching.descriptor_max_pairs': 64,
            'matching.prior_weight': 5.0,
            'solver.max_iterations': 2,
            'solver.inlier_threshold_m': 1.5,
            'solver.min_inliers': 6,
        },
    },
]


def apply_overrides(cfg, overrides: Dict[str, object]) -> None:
    for path, value in overrides.items():
        parts = path.split('.')
        target = cfg
        for attr in parts[:-1]:
            target = getattr(target, attr)
        setattr(target, parts[-1], value)


def main() -> None:
    parser = argparse.ArgumentParser(description='Run DAIR-V2X pipeline experiments sequentially.')
    parser.add_argument('--config', default='configs/pipeline.yaml', help='Base pipeline config path.')
    parser.add_argument(
        '--tag-prefix',
        default='',
        help='Optional prefix added to every output.tag (useful to avoid overwriting old runs).',
    )
    parser.add_argument(
        '--tags',
        nargs='*',
        help='Optional subset of experiment tags to run. Defaults to all configured experiments.',
    )
    args = parser.parse_args()

    results = {}
    selected = [exp for exp in EXPERIMENTS if not args.tags or exp['tag'] in args.tags]
    for exp in selected:
        cfg = load_config(args.config)
        prefix = str(args.tag_prefix or '')
        apply_overrides(cfg, {'output.tag': f"{prefix}{exp['tag']}"})
        apply_overrides(cfg, exp['overrides'])
        print(f"\n[RUN] {exp['tag']}: {exp['description']}")
        pipeline = ObjectLevelPipeline(cfg)
        summary = pipeline.run()
        results[exp['tag']] = summary
        print(json.dumps(summary, indent=2))

    print('\nAll experiments completed:')
    for tag, summary in results.items():
        print(f"- {tag}: {summary.get('mRRE@1.0', 0):.3f} deg, {summary.get('mRTE@1.0', 0):.3f} m")


if __name__ == '__main__':
    main()
