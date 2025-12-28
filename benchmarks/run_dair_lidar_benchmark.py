#!/usr/bin/env python3
"""
Run LiDAR-Registration-Benchmark methods on the DAIR-V2X dataset that is bundled
with this repository. Results (per-sample and aggregate) are written to outputs/.
"""
import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import List, Dict, Any

import numpy as np
import open3d as o3d
from scipy.spatial.transform import Rotation as R

SCRIPT_DIR = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_DIR.parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from configs.legacy_api import cfg as project_cfg  # noqa: E402  pylint: disable=wrong-import-position
from configs.legacy_api import cfg_from_yaml_file as project_cfg_from_yaml  # noqa: E402
from configs.legacy_api import Logger  # noqa: E402
from calib.evaluation.metrics import FrameMetrics, aggregate_metrics  # noqa: E402
from v2x_calib.reader.CooperativeBatchingReader import CooperativeBatchingReader  # noqa: E402
from v2x_calib.utils import (  # noqa: E402
    convert_T_to_6DOF,
    get_RE_TE_by_compare_T_6DOF_result_true,
)


BENCHMARK_ROOT = PROJECT_ROOT / 'benchmarks' / 'third_party' / 'LiDAR-Registration-Benchmark'

if not BENCHMARK_ROOT.exists():
    raise FileNotFoundError(
        f"LiDAR-Registration-Benchmark submodule not found at {BENCHMARK_ROOT}. "
        "Please run `git submodule update --init --recursive` first.")

# Import benchmark utilities after ensuring the path is available.
sys.path.insert(0, str(BENCHMARK_ROOT))
from misc import config as benchmark_cfg_module  # type: ignore

try:
    from misc.registration import fpfh_teaser  # type: ignore
except ImportError:  # pragma: no cover
    # Only required for the "teaser" method. ICP/PICP runs do not need teaserpp_python.
    fpfh_teaser = None


def parse_args():
    parser = argparse.ArgumentParser(
        description="Evaluate LiDAR-Registration-Benchmark methods on DAIR-V2X data.")
    parser.add_argument('--project-config', type=str,
                        default='configs/hkust_lidar_global_config.yaml',
                        help='Path to the project config that includes DAIR-V2X paths.')
    parser.add_argument('--data-info', type=str, default=None,
                        help='Optional data_info.json override (recommended for paper subsets).')
    parser.add_argument('--data-root', type=str, default=None,
                        help='Optional dataset root override (folder containing infrastructure-side/vehicle-side).')
    parser.add_argument('--benchmark-config', type=str,
                        default=str(BENCHMARK_ROOT / 'configs/dataset.yaml'),
                        help='Config inside LiDAR-Registration-Benchmark that defines registration params.')
    parser.add_argument('--start', type=int, default=0,
                        help='Start index within the data_info list.')
    parser.add_argument('--end', type=int, default=-1,
                        help='End index (exclusive) within the data_info list. -1 means all.')
    parser.add_argument('--max-pairs', type=int, default=None,
                        help='Optional hard limit on how many pairs to evaluate.')
    parser.add_argument('--output-root', type=str, default='outputs',
                        help='Output root directory (default: outputs).')
    parser.add_argument('--output-tag', type=str, default=None,
                        help='Optional stable output folder name. '
                             'Defaults to a timestamp-based name.')
    parser.add_argument('--visualize', action='store_true',
                        help='Visualize the registration result via Open3D.')
    parser.add_argument('--method', type=str, default='teaser',
                        choices=['teaser', 'icp', 'picp'],
                        help='Registration method to run.')
    parser.add_argument('--trans-noise', type=float, default=0.0,
                        help='Std of translation noise applied to GT transform (meters).')
    parser.add_argument('--rot-noise-deg', type=float, default=0.0,
                        help='Std of rotation noise applied to GT transform (degrees).')
    parser.add_argument('--voxel', type=float, default=0.3,
                        help='Voxel size for ICP down-sampling (meters).')
    parser.add_argument('--max-corr', type=float, default=1.5,
                        help='Max correspondence distance for ICP (meters).')
    parser.add_argument('--max-iter', type=int, default=100,
                        help='Max ICP iterations (default: 100).')
    parser.add_argument('--max-delta-trans', type=float, default=float('inf'),
                        help='Optional sanity gate: if ICP changes translation more than this (meters) '
                             'relative to the provided initial transform, fall back to the initial transform.')
    parser.add_argument('--max-delta-rot-deg', type=float, default=float('inf'),
                        help='Optional sanity gate: if ICP changes rotation more than this (degrees) '
                             'relative to the provided initial transform, fall back to the initial transform.')
    parser.add_argument('--log-every', type=int, default=50,
                        help='Log a detailed line every N frames (default: 50).')
    parser.add_argument('--seed', type=int, default=2025,
                        help='Random seed for noise injection.')
    return parser.parse_args()


def resolve_path(base_dir: Path, maybe_relative: str) -> str:
    path = Path(maybe_relative)
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return str(path)


def format_result(inf_id: str, veh_id: str, re: float, te: float,
                  runtime: float, success: bool) -> Dict[str, Any]:
    return {
        "infra_id": inf_id,
        "vehicle_id": veh_id,
        "rotation_error_deg": re,
        "translation_error_m": te,
        "runtime_s": runtime,
        "success": bool(success)
    }


def summarize_results(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not records:
        return {
            "total_pairs": 0,
            "success_pairs": 0,
            "success_rate": 0.0,
            "avg_rotation_error_deg": None,
            "avg_translation_error_m": None,
            "avg_runtime_s": None
        }
    rotation_errors = np.array([entry["rotation_error_deg"] for entry in records])
    translation_errors = np.array([entry["translation_error_m"] for entry in records])
    runtimes = np.array([entry["runtime_s"] for entry in records])
    successes = np.array([entry["success"] for entry in records])
    return {
        "total_pairs": int(len(records)),
        "success_pairs": int(successes.sum()),
        "success_rate": float(successes.mean()),
        "avg_rotation_error_deg": float(rotation_errors.mean()),
        "avg_translation_error_m": float(translation_errors.mean()),
        "avg_runtime_s": float(runtimes.mean())
    }


def add_transform_noise(T: np.ndarray, trans_std: float, rot_std_deg: float,
                        rng: np.random.Generator) -> np.ndarray:
    if trans_std <= 0 and rot_std_deg <= 0:
        return T.copy()
    # Paper Table III noise: apply a left-multiplicative SE(3) perturbation with
    # equal-magnitude translation (m) and rotation (deg) Gaussian noise.
    delta_t = rng.normal(scale=trans_std, size=3)
    delta_euler_deg = rng.normal(scale=rot_std_deg, size=3)
    delta_R = R.from_euler("xyz", delta_euler_deg, degrees=True).as_matrix()
    noise_T = np.eye(4)
    noise_T[:3, :3] = delta_R
    noise_T[:3, 3] = delta_t
    return noise_T @ T


def numpy_to_pcd(points: np.ndarray) -> o3d.geometry.PointCloud:
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(points[:, :3])
    return pcd


def run_icp_solver(infra_pc: np.ndarray,
                   veh_pc: np.ndarray,
                   T_init: np.ndarray,
                   *,
                   voxel: float,
                   max_corr: float,
                   point_to_plane: bool,
                   max_iter: int) -> np.ndarray:
    src = numpy_to_pcd(infra_pc)
    tgt = numpy_to_pcd(veh_pc)
    if voxel > 0:
        src = src.voxel_down_sample(voxel)
        tgt = tgt.voxel_down_sample(voxel)
    if point_to_plane:
        tgt.estimate_normals(
            o3d.geometry.KDTreeSearchParamHybrid(radius=max(voxel * 2.0, 0.3), max_nn=30)
        )
        estimation = o3d.pipelines.registration.TransformationEstimationPointToPlane()
    else:
        estimation = o3d.pipelines.registration.TransformationEstimationPointToPoint()
    criteria = o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=max_iter)
    reg = o3d.pipelines.registration.registration_icp(
        src,
        tgt,
        max_corr,
        T_init,
        estimation,
        criteria,
    )
    return reg.transformation


def compute_se3_delta(T_new: np.ndarray, T_ref: np.ndarray) -> tuple[float, float]:
    """Return (delta_rot_deg, delta_trans_m) for T_new relative to T_ref."""
    T_delta = T_new @ np.linalg.inv(T_ref)
    rot = R.from_matrix(T_delta[:3, :3])
    delta_rot_deg = float(np.degrees(rot.magnitude()))
    delta_trans_m = float(np.linalg.norm(T_delta[:3, 3]))
    return delta_rot_deg, delta_trans_m


def main():
    args = parse_args()

    project_cfg_from_yaml(resolve_path(PROJECT_ROOT, args.project_config), project_cfg)
    benchmark_cfg_module.cfg_from_yaml_file(
        resolve_path(BENCHMARK_ROOT, args.benchmark_config), benchmark_cfg_module.cfg)

    if args.data_root:
        project_cfg.data.data_root_path = resolve_path(PROJECT_ROOT, args.data_root)
    else:
        project_cfg.data.data_root_path = resolve_path(PROJECT_ROOT, project_cfg.data.data_root_path)

    if args.data_info:
        project_cfg.data.data_info_path = resolve_path(PROJECT_ROOT, args.data_info)
    else:
        project_cfg.data.data_info_path = resolve_path(PROJECT_ROOT, project_cfg.data.data_info_path)

    reader = CooperativeBatchingReader(path_data_info=project_cfg.data.data_info_path,
                                       path_data_folder=project_cfg.data.data_root_path)
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    logger = Logger(f"dair_lidar_benchmark_{args.method}_{timestamp}")

    output_root = Path(resolve_path(PROJECT_ROOT, args.output_root))
    output_root.mkdir(parents=True, exist_ok=True)
    tag_name = args.output_tag or f"dair_lidar_benchmark_{args.method}_{timestamp}"
    output_dir = output_root / tag_name
    output_dir.mkdir(parents=True, exist_ok=True)
    detail_path = output_dir / 'details.jsonl'
    rng = np.random.default_rng(args.seed)

    records: List[FrameMetrics] = []
    processed = 0

    with open(detail_path, 'w') as detail_file:
        for (inf_id, veh_id, inf_pc, veh_pc, T_true) in \
                reader.generate_infra_vehicle_pointcloud(start_idx=args.start, end_idx=args.end):
            if args.max_pairs is not None and processed >= args.max_pairs:
                break

            t_start = perf_counter()
            delta_rot_deg = None
            delta_trans_m = None
            used_fallback = False
            if args.method == 'teaser':
                if fpfh_teaser is None:
                    raise ImportError(
                        "Failed to import LiDAR-Registration-Benchmark.misc.registration.fpfh_teaser. "
                        "Please ensure `teaserpp_python` and `open3d` are installed if you want to run '--method teaser'."
                    )
                T_pred = fpfh_teaser(inf_pc, veh_pc, args.visualize)
            elif args.method in {'icp', 'picp'}:
                T_init = add_transform_noise(
                    T_true, args.trans_noise, args.rot_noise_deg, rng
                )
                if args.max_iter <= 0:
                    T_pred = T_init
                    used_fallback = True
                else:
                    T_icp = run_icp_solver(
                        inf_pc,
                        veh_pc,
                        T_init,
                        voxel=args.voxel,
                        max_corr=args.max_corr,
                        point_to_plane=(args.method == 'picp'),
                        max_iter=args.max_iter,
                    )
                    delta_rot_deg, delta_trans_m = compute_se3_delta(T_icp, T_init)
                    if delta_trans_m > args.max_delta_trans or delta_rot_deg > args.max_delta_rot_deg:
                        T_pred = T_init
                        used_fallback = True
                    else:
                        T_pred = T_icp
            else:  # pragma: no cover
                raise ValueError(f"Unsupported method: {args.method}")
            t_end = perf_counter()

            RE, TE = get_RE_TE_by_compare_T_6DOF_result_true(
                convert_T_to_6DOF(T_pred), convert_T_to_6DOF(T_true))
            runtime = t_end - t_start

            detail_file.write(json.dumps({
                "infra_id": inf_id,
                "veh_id": veh_id,
                "RE": float(RE),
                "TE": float(TE),
                "time": float(runtime),
                "delta_rot_deg": delta_rot_deg,
                "delta_trans_m": delta_trans_m,
                "used_fallback": used_fallback,
            }) + '\n')
            records.append(FrameMetrics(
                infra_id=str(inf_id),
                veh_id=str(veh_id),
                RE=float(RE),
                TE=float(TE),
                stability=0.0,
                time_cost=float(runtime),
                matches_count=0,
            ))
            processed += 1

            if args.log_every > 0 and (processed == 1 or processed % args.log_every == 0):
                logger.info(
                    f"[{processed}] inf_id={inf_id} veh_id={veh_id} "
                    f"RE={RE:.2f}deg TE={TE:.2f}m time={runtime:.3f}s")

    summary = aggregate_metrics(records, thresholds=[1.0, 2.0, 3.0])
    metrics_path = output_dir / 'metrics.json'
    with open(metrics_path, 'w') as metrics_file:
        json.dump(summary, metrics_file, indent=2)

    logger.info("==== Summary ====")
    logger.info(json.dumps(summary, indent=2))
    logger.close()
    print(f"Detailed per-pair metrics: {detail_path}")
    print(f"Aggregated metrics: {metrics_path}")


if __name__ == '__main__':
    main()
