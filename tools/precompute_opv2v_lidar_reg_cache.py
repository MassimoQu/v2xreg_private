#!/usr/bin/env python3
"""
Precompute OPV2V test split LiDAR-registration caches for lidar_reg / HKUST baselines.

Why:
  - Raw LiDAR registration (FPFH + RANSAC/FGR/TEASER + ICP) is CPU-expensive.
  - In OPV2V fullbench we sweep many noise levels, but raw point clouds do not change.
  - This script computes per-(sample_idx, ego_id, cav_id) relative transforms once and
    saves them as a JSON cache that Stage1LidarRegPoseCorrector can reuse.

Cache format (JSON):
  {
    "meta": {...},
    "pairs": {
      "<sample_idx>|<ego_id>|<cav_id>": {"T": [[4x4]], "fitness": float, "inlier_rmse": float} | null
    }
  }

Notes:
  - Cache is keyed by dataset index (sample_idx) used by inference_w_noise.py (0..len-1).
  - Transforms are cav->ego in LiDAR coordinates (dst <- src), matching Stage1LidarRegPoseCorrector.
"""

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import hashlib

import numpy as np

# Imported from HEAL via PYTHONPATH=$PWD/HEAL
from opencood.data_utils.datasets import build_dataset
from opencood.extrinsics.late_fusion.lidar_registration import (
    LidarRegistrationConfig,
    LidarRegistrationEstimator,
)
from opencood.hypes_yaml import yaml_utils
from opencood.utils.pcd_utils import mask_ego_points


def _atomic_write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _find_ego_id(base_data_dict: Dict[Any, Dict[str, Any]]) -> Optional[Any]:
    for cav_id, cav in base_data_dict.items():
        if isinstance(cav, dict) and bool(cav.get("ego", False)):
            return cav_id
    return next(iter(base_data_dict.keys()), None)


def _pair_key(sample_idx: int, ego_id: Any, cav_id: Any) -> str:
    return f"{int(sample_idx)}|{str(ego_id)}|{str(cav_id)}"


def _load_existing(path: Path) -> Tuple[dict, dict]:
    if not path.exists():
        return {}, {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {}, {}
    if not isinstance(obj, dict):
        return {}, {}
    pairs = obj.get("pairs")
    if not isinstance(pairs, dict):
        pairs = {}
    return obj, pairs


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--model-dir",
        type=Path,
        default=Path("HEAL/opencood/logs/freealign_repro_opv2v_baseline"),
        help="Model dir that provides the OPV2V dataset config.yaml (validate_dir will be set to test_dir).",
    )
    p.add_argument(
        "--global-method",
        type=str,
        default="ransac",
        choices=["ransac", "fgr", "teaser_gnctls", "teaser_fgr", "teaser_quatro"],
        help="LidarRegistrationConfig.global_method.",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output JSON path. Default: data/OPV2V/lidar_reg_cache/opv2v_test_<global_method>.json",
    )
    p.add_argument("--max-samples", type=int, default=0, help="Optional cap (0=full test split).")
    p.add_argument("--save-every", type=int, default=10, help="Flush cache to disk every N samples.")
    p.add_argument("--resume", action="store_true", help="Resume from existing cache (skip existing keys).")
    p.add_argument("--seed", type=int, default=303, help="Seed used for any internal downsampling randomness.")
    p.add_argument(
        "--num-shards",
        type=int,
        default=1,
        help="Optional sharding for parallel precompute. This process handles indices where idx %% num_shards == shard_id.",
    )
    p.add_argument("--shard-id", type=int, default=0, help="Shard id in [0, num_shards).")

    # Optional overrides for speed/quality trade-offs.
    p.add_argument("--voxel-size-m", type=float, default=1.0)
    p.add_argument("--max-corr-dist-m", type=float, default=2.0)
    p.add_argument("--ransac-n", type=int, default=4)
    p.add_argument("--ransac-max-iter", type=int, default=50000)
    p.add_argument("--ransac-confidence", type=float, default=0.999)
    p.add_argument("--icp-max-iter", type=int, default=50)
    p.add_argument("--min-points", type=int, default=200)
    p.add_argument("--max-points", type=int, default=60000)
    p.add_argument("--teaser-noise-bound-m", type=float, default=2.0)
    p.add_argument("--teaser-max-correspondences", type=int, default=8000)

    args = p.parse_args()

    model_dir = Path(args.model_dir)
    cfg_path = model_dir / "config.yaml"
    if not cfg_path.exists():
        raise SystemExit(f"Missing config.yaml under model dir: {cfg_path}")

    hypes = yaml_utils.load_yaml(str(cfg_path), opt=None) or {}
    if not isinstance(hypes, dict):
        raise SystemExit(f"Invalid YAML config: {cfg_path}")
    # inference_w_noise.py uses test split by setting validate_dir=test_dir.
    if "test_dir" in hypes:
        hypes["validate_dir"] = hypes["test_dir"]

    num_shards = max(1, int(args.num_shards or 1))
    shard_id = int(args.shard_id or 0)
    if shard_id < 0 or shard_id >= num_shards:
        raise SystemExit(f"--shard-id must be in [0, {num_shards}), got {shard_id}")

    if args.out:
        out = Path(args.out)
    else:
        cache_root = Path("data/OPV2V/lidar_reg_cache")
        if num_shards <= 1:
            out = cache_root / f"opv2v_test_{args.global_method}.json"
        else:
            shard_dir = cache_root / "shards"
            out = shard_dir / f"opv2v_test_{args.global_method}_shard{shard_id}of{num_shards}.json"

    existing_obj: dict = {}
    pairs: dict = {}
    if args.resume and out.exists():
        existing_obj, pairs = _load_existing(out)

    cfg = LidarRegistrationConfig(
        voxel_size_m=float(args.voxel_size_m),
        max_corr_dist_m=float(args.max_corr_dist_m),
        ransac_n=int(args.ransac_n),
        ransac_max_iter=int(args.ransac_max_iter),
        ransac_confidence=float(args.ransac_confidence),
        global_method=str(args.global_method),
        icp_max_iter=int(args.icp_max_iter),
        min_points=int(args.min_points),
        max_points=int(args.max_points),
        teaser_noise_bound_m=float(args.teaser_noise_bound_m),
        teaser_max_correspondences=int(args.teaser_max_correspondences),
    )
    estimator = LidarRegistrationEstimator(cfg=cfg)

    # Deterministic-ish downsampling in our own code paths (Open3D may still be nondeterministic).
    np.random.seed(int(args.seed))

    dataset = build_dataset(hypes, visualize=True, train=False)
    total = len(dataset)
    cap = int(args.max_samples or 0)
    if cap > 0:
        total = min(total, cap)
    indices = list(range(total))
    if num_shards > 1:
        indices = [i for i in indices if (int(i) % num_shards) == shard_id]
    shard_total = len(indices)

    meta = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model_dir": str(model_dir),
        "validate_dir": str(hypes.get("validate_dir", "")),
        "global_method": str(args.global_method),
        "num_shards": int(num_shards),
        "shard_id": int(shard_id),
        "cfg": {
            "voxel_size_m": cfg.voxel_size_m,
            "max_corr_dist_m": cfg.max_corr_dist_m,
            "ransac_n": cfg.ransac_n,
            "ransac_max_iter": cfg.ransac_max_iter,
            "ransac_confidence": cfg.ransac_confidence,
            "icp_max_iter": cfg.icp_max_iter,
            "min_points": cfg.min_points,
            "max_points": cfg.max_points,
            "teaser_noise_bound_m": cfg.teaser_noise_bound_m,
            "teaser_max_correspondences": cfg.teaser_max_correspondences,
        },
        "seed": int(args.seed),
        "max_samples": int(args.max_samples or 0),
    }

    start = time.perf_counter()
    for local_i, idx in enumerate(indices):
        base = dataset.retrieve_base_data(idx)
        if not isinstance(base, dict) or not base:
            continue
        ego_id = _find_ego_id(base)
        if ego_id is None or ego_id not in base:
            continue
        ego_points = (base.get(ego_id) or {}).get("lidar_np")
        if ego_points is None:
            continue
        ego_points = mask_ego_points(np.asarray(ego_points))

        for cav_id, cav in base.items():
            if cav_id == ego_id:
                continue
            key = _pair_key(idx, ego_id, cav_id)
            if args.resume and key in pairs:
                continue
            cav_points = (cav or {}).get("lidar_np") if isinstance(cav, dict) else None
            if cav_points is None:
                pairs[key] = None
                continue
            cav_points = mask_ego_points(np.asarray(cav_points))

            # Keep per-pair downsampling deterministic across resume / loop order changes.
            # NOTE: Don't use Python's built-in hash() here because it is salted per process by default.
            try:
                pair_sig = f"{idx}|{ego_id}|{cav_id}".encode("utf-8", errors="ignore")
                pair_hash = int(hashlib.md5(pair_sig).hexdigest()[:8], 16)
                seed_val = (int(args.seed) * 1000003 + int(idx) * 97 + int(pair_hash)) & 0xFFFFFFFF
                np.random.seed(int(seed_val))
            except Exception:
                pass

            est = estimator.estimate_from_points(cav_points, ego_points)
            if not est.success or est.T is None:
                pairs[key] = None
                continue
            T = np.asarray(est.T, dtype=np.float64).reshape(4, 4)
            pairs[key] = {
                "T": T.tolist(),
                "fitness": float(est.extra.get("fitness", 0.0) or 0.0),
                "inlier_rmse": float(est.extra.get("inlier_rmse", 0.0) or 0.0),
            }

        if int(args.save_every) > 0 and (local_i + 1) % int(args.save_every) == 0:
            _atomic_write_json(out, {"meta": meta, "pairs": pairs})
            elapsed = time.perf_counter() - start
            print(f"[{local_i+1}/{shard_total}] wrote {out} (pairs={len(pairs)}) elapsed={elapsed:.1f}s")

    _atomic_write_json(out, {"meta": meta, "pairs": pairs})
    elapsed = time.perf_counter() - start
    print(f"Done. wrote {out} (pairs={len(pairs)}) elapsed={elapsed:.1f}s")


if __name__ == "__main__":
    main()
