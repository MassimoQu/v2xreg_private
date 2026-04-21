import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
HEAL = ROOT / "HEAL"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(HEAL) not in sys.path:
    sys.path.insert(0, str(HEAL))


def _cube_corners(center_xyz, *, size=2.0):
    cx, cy, cz = [float(x) for x in center_xyz]
    d = float(size) / 2.0
    return np.asarray(
        [
            [cx - d, cy - d, cz - d],
            [cx - d, cy + d, cz - d],
            [cx + d, cy + d, cz - d],
            [cx + d, cy - d, cz - d],
            [cx - d, cy - d, cz + d],
            [cx - d, cy + d, cz + d],
            [cx + d, cy + d, cz + d],
            [cx + d, cy - d, cz + d],
        ],
        dtype=np.float64,
    )


class Stage1VipsCbmDirectionTest(unittest.TestCase):
    def test_vips_cbm_corrector_calls_estimator_as_cav_to_ego(self):
        """
        Regression: VIPS/CBM estimators return T that maps (arg1 -> arg2). The stage1
        corrector must therefore call estimate(cav_boxes, ego_boxes) so that rel_T is
        (cav -> ego). A swapped order silently makes VIPS/CBM look terrible.
        """
        from opencood.extrinsics.bbox_utils import bbox3d_to_state7
        from opencood.extrinsics.pose_correction.stage1_vips_cbm import _Stage1BasePoseCorrector
        from opencood.extrinsics.types import ExtrinsicEstimate

        ego_center = (5.0, 0.0, 0.0)
        cav_center = (-7.0, 0.0, 0.0)
        stage1 = {
            "0": {
                "cav_id_list": ["0", "1"],
                "pred_corner3d_np_list": [
                    [_cube_corners(ego_center).tolist()],
                    [_cube_corners(cav_center).tolist()],
                ],
                "lidar_pose_clean_np": [
                    [0, 0, 0, 0, 0, 0],
                    [10, 0, 0, 0, 0, 0],
                ],
            }
        }
        base_data_dict = {
            "0": {"ego": True, "params": {"lidar_pose": [0, 0, 0, 0, 0, 0]}},
            "1": {"ego": False, "params": {"lidar_pose": [10, 0, 0, 0, 0, 0]}},
        }

        @dataclass
        class _DummyCorrector(_Stage1BasePoseCorrector):
            last_src_center: Optional[Tuple[float, float, float]] = None
            last_dst_center: Optional[Tuple[float, float, float]] = None

            def _estimate_rel_T(self, src_boxes, dst_boxes, *, init):
                src_c, _, _, _ = bbox3d_to_state7(src_boxes[0])
                dst_c, _, _, _ = bbox3d_to_state7(dst_boxes[0])
                self.last_src_center = tuple(float(x) for x in src_c.tolist())
                self.last_dst_center = tuple(float(x) for x in dst_c.tolist())
                return ExtrinsicEstimate(T=np.eye(4, dtype=np.float64), success=True, method="dummy")

        corr = _DummyCorrector(compare_with_current=False, use_prior=False, freeze_ego=True)
        updated = corr.apply(sample_idx=0, cav_id_list=["0", "1"], base_data_dict=base_data_dict, stage1_result=stage1)
        self.assertTrue(updated)
        self.assertIsNotNone(corr.last_src_center)
        self.assertIsNotNone(corr.last_dst_center)
        self.assertAlmostEqual(corr.last_src_center[0], float(cav_center[0]), places=5)
        self.assertAlmostEqual(corr.last_dst_center[0], float(ego_center[0]), places=5)


if __name__ == "__main__":
    unittest.main()
