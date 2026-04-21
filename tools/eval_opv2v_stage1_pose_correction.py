#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np


def _wrap_angle_deg(angle_deg: float) -> float:
    return float(((angle_deg + 180.0) % 360.0) - 180.0)


def _angle_abs_deg(angle_deg: float) -> float:
    return abs(_wrap_angle_deg(float(angle_deg)))


def _se2_from_pose(pose6: Sequence[float]) -> np.ndarray:
    x = float(pose6[0])
    y = float(pose6[1])
    yaw_deg = float(pose6[4])
    yaw = math.radians(yaw_deg)
    c = math.cos(yaw)
    s = math.sin(yaw)
    T = np.eye(3, dtype=np.float64)
    T[0, 0] = c
    T[0, 1] = -s
    T[1, 0] = s
    T[1, 1] = c
    T[0, 2] = x
    T[1, 2] = y
    return T


def _inv_se2(T: np.ndarray) -> np.ndarray:
    R = T[:2, :2]
    t = T[:2, 2:3]
    out = np.eye(3, dtype=np.float64)
    out[:2, :2] = R.T
    out[:2, 2:3] = -R.T @ t
    return out


def _rel_se2(ego_pose6: Sequence[float], cav_pose6: Sequence[float]) -> np.ndarray:
    T_e = _se2_from_pose(ego_pose6)
    T_c = _se2_from_pose(cav_pose6)
    return _inv_se2(T_e) @ T_c


def _se2_error(T_rel_est: np.ndarray, T_rel_true: np.ndarray) -> Tuple[float, float]:
    delta = _inv_se2(T_rel_true) @ T_rel_est
    te = float(np.hypot(delta[0, 2], delta[1, 2]))
    re = _angle_abs_deg(math.degrees(math.atan2(delta[1, 0], delta[0, 0])))
    return te, re


def _noise_pose6_gaussian(
    pose6_clean: np.ndarray,
    *,
    seed: int,
    pos_std: float,
    rot_std: float,
) -> np.ndarray:
    rs = np.random.RandomState(int(seed))
    noise = np.zeros_like(pose6_clean, dtype=np.float64)
    if pos_std > 0:
        noise[:, 0:2] = rs.normal(0.0, float(pos_std), size=(pose6_clean.shape[0], 2))
    if rot_std > 0:
        noise[:, 4] = rs.normal(0.0, float(rot_std), size=(pose6_clean.shape[0],))
    return pose6_clean + noise


@dataclass
class Metrics:
    te: List[float]
    re: List[float]

    def summary(self, *, thresholds: Sequence[float]) -> Dict[str, Any]:
        te = np.asarray(self.te, dtype=np.float64)
        re = np.asarray(self.re, dtype=np.float64)
        if te.size == 0:
            base = {
                "count": 0,
                "te_mean": None,
                "te_median": None,
                "te_p90": None,
                "re_mean": None,
                "re_median": None,
                "re_p90": None,
            }
            base["success"] = {str(th): None for th in thresholds}
            return base

        def _p(x: np.ndarray, q: float) -> float:
            return float(np.percentile(x, q))

        out: Dict[str, Any] = {
            "count": int(te.size),
            "te_mean": float(te.mean()),
            "te_median": float(np.median(te)),
            "te_p90": _p(te, 90.0),
            "re_mean": float(re.mean()),
            "re_median": float(np.median(re)),
            "re_p90": _p(re, 90.0),
        }
        success = {}
        for th in thresholds:
            th_f = float(th)
            ok = (te < th_f) & (re < th_f)
            success[str(th)] = float(ok.mean())
        out["success"] = success
        return out


def _load_stage1(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _sorted_indices(stage1: Mapping[str, Any]) -> List[int]:
    indices = []
    for k in stage1.keys():
        try:
            indices.append(int(k))
        except Exception:
            continue
    indices.sort()
    return indices


def _as_boxes_list(raw) -> List[np.ndarray]:
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        try:
            arr = np.asarray(item, dtype=np.float64)
        except Exception:
            arr = np.zeros((0, 8, 3), dtype=np.float64)
        out.append(arr)
    return out


def _as_uncertainty_list(raw) -> List[np.ndarray]:
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        try:
            arr = np.asarray(item, dtype=np.float64)
        except Exception:
            arr = np.zeros((0, 3), dtype=np.float64)
        out.append(arr)
    return out


def _run_freealign(
    *,
    freealign_repo: Path,
    pred_corners_list: List[np.ndarray],
    noisy_pose6: np.ndarray,
    uncertainty_list: Optional[List[np.ndarray]],
    box_align_kwargs: Dict[str, Any],
) -> Optional[np.ndarray]:
    if int(sum(int(len(x)) for x in pred_corners_list)) == 0:
        return None
    from opencood.models.sub_modules.box_align_v2 import box_alignment_relative_sample_np  # type: ignore

    refined = box_alignment_relative_sample_np(
        pred_corners_list,
        np.asarray(noisy_pose6, dtype=np.float64),
        uncertainty_list=uncertainty_list,
        **box_align_kwargs,
    )
    refined = np.asarray(refined, dtype=np.float64)
    if refined.ndim != 2 or refined.shape[1] != 3:
        return None
    out = np.asarray(noisy_pose6, dtype=np.float64).copy()
    out[:, [0, 1, 4]] = refined
    return out


def _run_v2xregpp(
    *,
    cav_id_list: Sequence[Any],
    noisy_pose6: np.ndarray,
    clean_pose6: np.ndarray,
    stage1_result: Mapping[str, Any],
    sample_idx: int,
    corrector,
) -> Optional[np.ndarray]:
    base_data_dict: Dict[Any, Dict[str, Any]] = {}
    for cav_id, pose_noisy, pose_clean in zip(cav_id_list, noisy_pose6.tolist(), clean_pose6.tolist()):
        base_data_dict[cav_id] = {
            "params": {"lidar_pose": list(pose_noisy), "lidar_pose_clean": list(pose_clean)},
            "ego": cav_id == cav_id_list[0],
        }
    ok = corrector.apply(
        sample_idx=int(sample_idx),
        cav_id_list=list(cav_id_list),
        base_data_dict=base_data_dict,
        stage1_result=stage1_result,
    )
    if not ok:
        return None
    out = np.asarray([base_data_dict[cid]["params"]["lidar_pose"] for cid in cav_id_list], dtype=np.float64)
    if out.shape != noisy_pose6.shape:
        return None
    return out


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    default_stage1 = os.environ.get(
        "OPV2V_STAGE1",
        str(repo_root / "data/OPV2V/detected/opv2v_lidar_v2xvit_stage1/test/stage1_boxes.json"),
    )
    default_freealign_repo = os.environ.get("FREEALIGN_REPO", "")
    default_heal_root = os.environ.get("HEAL_ROOT", str(repo_root / "HEAL"))
    default_v2xreg_root = os.environ.get("V2XREG_ROOT", str(repo_root))

    parser = argparse.ArgumentParser()
    parser.add_argument("--stage1_json", type=str, default=default_stage1)
    parser.add_argument("--method", type=str, choices=["baseline", "freealign", "v2xregpp"], required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--pos_std", type=float, default=3.0)
    parser.add_argument("--rot_std", type=float, default=3.0)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--max_samples", type=int, default=0, help="0 means all")
    parser.add_argument("--thresholds", type=str, default="1,2,3")

    parser.add_argument("--freealign_repo", type=str, default=default_freealign_repo)
    parser.add_argument("--fa_use_uncertainty", action="store_true", default=True)
    parser.add_argument("--fa_landmark_se2", action="store_true", default=True)
    parser.add_argument("--fa_adaptive_landmark", action="store_true", default=False)
    parser.add_argument("--fa_normalize_uncertainty", action="store_true", default=False)
    parser.add_argument("--fa_abandon_hard_cases", action="store_true", default=True)
    parser.add_argument("--fa_drop_hard_boxes", action="store_true", default=True)
    parser.add_argument("--fa_drop_unsure_edge", action="store_true", default=False)
    parser.add_argument("--fa_thres", type=float, default=1.5)
    parser.add_argument("--fa_yaw_var_thres", type=float, default=0.2)
    parser.add_argument("--fa_max_iterations", type=int, default=1000)
    parser.add_argument(
        "--fa_no_pose_init",
        action="store_true",
        default=False,
        help="Use a no-initial-pose setting (all zeros, yaw=1deg) as the algorithm input.",
    )

    parser.add_argument("--heal_root", type=str, default=default_heal_root)
    parser.add_argument("--v2xreg_root", type=str, default=default_v2xreg_root)
    parser.add_argument("--v2xregpp_config", type=str, default="configs/dair/pipeline.yaml")
    parser.add_argument("--v2xregpp_mode", type=str, default="initfree", choices=["initfree", "stable"])
    parser.add_argument("--v2xregpp_min_matches", type=int, default=3)
    parser.add_argument("--v2xregpp_min_stability", type=float, default=0.0)
    parser.add_argument("--v2xregpp_min_precision_improvement", type=float, default=0.1)
    parser.add_argument("--v2xregpp_min_matched_improvement", type=int, default=1)
    parser.add_argument("--v2xregpp_apply_if_current_precision_below", type=float, default=-1.0)

    args = parser.parse_args()

    stage1_path = Path(args.stage1_json).expanduser().resolve()
    if not stage1_path.exists():
        raise FileNotFoundError(
            f"Stage1 cache not found: {stage1_path}. "
            "Set --stage1_json or OPV2V_STAGE1 to a valid stage1_boxes.json."
        )
    stage1 = _load_stage1(stage1_path)

    indices = _sorted_indices(stage1)
    if args.start > 0:
        indices = [i for i in indices if i >= int(args.start)]
    if args.max_samples and int(args.max_samples) > 0:
        indices = indices[: int(args.max_samples)]

    thresholds = [float(x) for x in str(args.thresholds).split(",") if x.strip()]
    thresholds = thresholds or [1.0, 2.0, 3.0]

    before_all = Metrics(te=[], re=[])
    after_all = Metrics(te=[], re=[])
    before_eligible = Metrics(te=[], re=[])
    after_eligible = Metrics(te=[], re=[])

    frames_total = 0
    pairs_total = 0
    pairs_eligible = 0
    pairs_updated = 0

    freealign_repo = Path(args.freealign_repo).expanduser().resolve() if args.freealign_repo else None
    heal_root = Path(args.heal_root).expanduser().resolve()
    v2xreg_root = Path(args.v2xreg_root).expanduser().resolve()
    v2xregpp_config = Path(args.v2xregpp_config)
    if not v2xregpp_config.is_absolute():
        v2xregpp_config = (v2xreg_root / v2xregpp_config).resolve()

    if args.method == "freealign":
        if freealign_repo is None or not freealign_repo.exists():
            raise FileNotFoundError(
                "FreeAlign repo not found. Set --freealign_repo or FREEALIGN_REPO."
            )
        sys.path.insert(0, str(freealign_repo))
    elif args.method == "v2xregpp":
        if not heal_root.exists():
            raise FileNotFoundError("HEAL repo not found. Set --heal_root or HEAL_ROOT.")
        sys.path.insert(0, str(heal_root))

    try:
        v2xregpp_corrector = None
        if args.method == "v2xregpp":
            from opencood.extrinsics.pose_correction.stage1_v2xregpp import (  # type: ignore
                Stage1V2XRegPPPoseCorrector,
            )

            v2xregpp_corrector = Stage1V2XRegPPPoseCorrector(
                config_path=str(v2xregpp_config),
                mode=str(args.v2xregpp_mode),
                bbox_type="detected",
                use_occ_hint=False,
                use_occ_pose=False,
                force_occ_pose=False,
                occ_from_lidar=False,
                icp_refine=False,
                min_matches=int(args.v2xregpp_min_matches),
                min_stability=float(args.v2xregpp_min_stability),
                min_precision_improvement=float(args.v2xregpp_min_precision_improvement),
                min_matched_improvement=int(args.v2xregpp_min_matched_improvement),
                apply_if_current_precision_below=float(args.v2xregpp_apply_if_current_precision_below),
                freeze_ego=True,
            )

        for sample_idx in indices:
            content = stage1.get(str(sample_idx))
            if not isinstance(content, Mapping):
                continue
            cav_id_list = content.get("cav_id_list") or []
            if not isinstance(cav_id_list, list) or len(cav_id_list) < 2:
                continue

            clean_pose = np.asarray(content.get("lidar_pose_clean_np"), dtype=np.float64)
            if clean_pose.ndim != 2 or clean_pose.shape[0] != len(cav_id_list) or clean_pose.shape[1] < 6:
                continue
            clean_pose = clean_pose[:, :6]

            noisy_pose = _noise_pose6_gaussian(
                clean_pose,
                seed=int(args.seed) + int(sample_idx),
                pos_std=float(args.pos_std),
                rot_std=float(args.rot_std),
            )

            pred_corners_list = _as_boxes_list(content.get("pred_corner3d_np_list"))
            uncertainty_list = _as_uncertainty_list(content.get("uncertainty_np_list"))
            if len(pred_corners_list) != len(cav_id_list):
                continue

            pose_init = noisy_pose
            corrected_pose: Optional[np.ndarray]
            updated_local: bool

            if args.method == "baseline":
                corrected_pose = pose_init
                updated_local = False
            elif args.method == "freealign":
                if bool(args.fa_no_pose_init):
                    pose_init = np.zeros_like(noisy_pose, dtype=np.float64)
                    pose_init[:, 4] = 1.0

                box_align_kwargs = {
                    "use_uncertainty": bool(args.fa_use_uncertainty),
                    "landmark_SE2": bool(args.fa_landmark_se2),
                    "adaptive_landmark": bool(args.fa_adaptive_landmark),
                    "normalize_uncertainty": bool(args.fa_normalize_uncertainty),
                    "abandon_hard_cases": bool(args.fa_abandon_hard_cases),
                    "drop_hard_boxes": bool(args.fa_drop_hard_boxes),
                    "drop_unsure_edge": bool(args.fa_drop_unsure_edge),
                    "thres": float(args.fa_thres),
                    "yaw_var_thres": float(args.fa_yaw_var_thres),
                    "max_iterations": int(args.fa_max_iterations),
                }
                corrected_pose = _run_freealign(
                    freealign_repo=freealign_repo,
                    pred_corners_list=pred_corners_list,
                    noisy_pose6=pose_init,
                    uncertainty_list=uncertainty_list if bool(args.fa_use_uncertainty) else None,
                    box_align_kwargs=box_align_kwargs,
                )
                if corrected_pose is None:
                    corrected_pose = pose_init
                    updated_local = False
                else:
                    updated_local = True
            else:
                corrected_pose = _run_v2xregpp(
                    cav_id_list=cav_id_list,
                    noisy_pose6=pose_init,
                    clean_pose6=clean_pose,
                    stage1_result=stage1,
                    sample_idx=int(sample_idx),
                    corrector=v2xregpp_corrector,
                )
                if corrected_pose is None:
                    corrected_pose = pose_init
                    updated_local = False
                else:
                    updated_local = True

            ego_clean = clean_pose[0]
            ego_noisy = pose_init[0]
            ego_corr = corrected_pose[0]

            frames_total += 1
            if updated_local:
                pairs_updated += max(0, len(cav_id_list) - 1)

            for j in range(1, len(cav_id_list)):
                pairs_total += 1
                cav_clean = clean_pose[j]
                cav_noisy = pose_init[j]
                cav_corr = corrected_pose[j]

                T_rel_clean = _rel_se2(ego_clean, cav_clean)
                T_rel_noisy = _rel_se2(ego_noisy, cav_noisy)
                T_rel_corr = _rel_se2(ego_corr, cav_corr)

                te0, re0 = _se2_error(T_rel_noisy, T_rel_clean)
                te1, re1 = _se2_error(T_rel_corr, T_rel_clean)
                before_all.te.append(te0)
                before_all.re.append(re0)
                after_all.te.append(te1)
                after_all.re.append(re1)

                eligible = bool(len(pred_corners_list[0]) > 0 and len(pred_corners_list[j]) > 0)
                if eligible:
                    pairs_eligible += 1
                    before_eligible.te.append(te0)
                    before_eligible.re.append(re0)
                    after_eligible.te.append(te1)
                    after_eligible.re.append(re1)
    finally:
        if args.method in {"freealign", "v2xregpp"} and sys.path:
            sys.path.pop(0)

    payload = {
        "method": args.method,
        "stage1_json": str(stage1_path),
        "seed": int(args.seed),
        "noise": {"pos_std": float(args.pos_std), "rot_std": float(args.rot_std)},
        "counts": {
            "frames": int(frames_total),
            "pairs_total": int(pairs_total),
            "pairs_eligible": int(pairs_eligible),
            "pairs_updated_assuming_all_non_ego": int(pairs_updated),
        },
        "all_pairs": {"before": before_all.summary(thresholds=thresholds), "after": after_all.summary(thresholds=thresholds)},
        "eligible_pairs": {
            "before": before_eligible.summary(thresholds=thresholds),
            "after": after_eligible.summary(thresholds=thresholds),
        },
    }

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
