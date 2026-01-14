from __future__ import annotations

from typing import List, Tuple

from calib.config import MatchingConfig, SolverConfig
from v2x_calib.search import Matches2Extrinsics
from v2x_calib.utils import convert_T_to_6DOF, get_RE_TE_by_compare_T_6DOF_result_true


class ExtrinsicSolver:
    def __init__(self, matching_cfg: MatchingConfig, solver_cfg: SolverConfig) -> None:
        self.matching_cfg = matching_cfg
        self.solver_cfg = solver_cfg

    def solve(self, infra_boxes, veh_boxes, matches_score, T_true):
        if not matches_score:
            return [0, 0, 0, 0, 0, 0], float('inf'), float('inf')
        conf_exp = float(getattr(self.solver_cfg, 'confidence_weight_exponent', 0.0) or 0.0)
        conf_min = float(getattr(self.solver_cfg, 'confidence_weight_min', 0.0) or 0.0)
        if conf_exp > 0.0:
            adjusted = []

            def _conf(box) -> float:
                if box is None:
                    return 1.0
                if hasattr(box, 'get_confidence'):
                    try:
                        val = box.get_confidence()
                    except Exception:
                        val = None
                    if val is not None:
                        try:
                            return float(val)
                        except Exception:
                            return 1.0
                try:
                    return float(getattr(box, 'confidence', 1.0))
                except Exception:
                    return 1.0

            for (i, j), score in matches_score:
                try:
                    base = float(score)
                except Exception:
                    base = 0.0
                if base <= 0.0:
                    adjusted.append(((int(i), int(j)), base))
                    continue
                try:
                    ci = max(0.0, _conf(infra_boxes[int(i)]))
                    cj = max(0.0, _conf(veh_boxes[int(j)]))
                except Exception:
                    ci = cj = 1.0
                prod = max(float(ci) * float(cj), conf_min)
                weight = base * (prod ** conf_exp)
                adjusted.append(((int(i), int(j)), float(weight)))
            matches_score = adjusted
        solver = Matches2Extrinsics(
            infra_boxes,
            veh_boxes,
            matches_score_list=matches_score,
            svd_strategy=self.matching_cfg.svd_strategy,
            resolve_180_ambiguity=getattr(self.matching_cfg, 'resolve_180_ambiguity', False),
            max_iterations=getattr(self.solver_cfg, 'max_iterations', 1),
            inlier_threshold_m=getattr(self.solver_cfg, 'inlier_threshold_m', 0.0),
            mad_scale=getattr(self.solver_cfg, 'mad_scale', 2.5),
            min_inliers=getattr(self.solver_cfg, 'min_inliers', 1),
        )
        T6 = solver.get_combined_extrinsic(
            matches2extrinsic_strategies=self.matching_cfg.matches2extrinsic
        )
        RE, TE = get_RE_TE_by_compare_T_6DOF_result_true(T6, convert_T_to_6DOF(T_true))
        return T6, RE, TE


__all__ = ['ExtrinsicSolver']
