import sys
import unittest
from pathlib import Path

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


class Stage1FreeAlignCompareDirectionTest(unittest.TestCase):
    def test_freealign_compare_uses_cav_to_ego_src_dst_order(self):
        """
        Regression: compare_with_current should evaluate match stats for T_rel that maps
        (cav -> ego), i.e. implement_T(T_rel, cav_boxes) compared against ego_boxes.
        """
        from opencood.extrinsics.bbox_utils import bbox3d_to_state7
        from opencood.extrinsics.pose_correction.stage1_freealign import Stage1FreeAlignPoseCorrector
        from opencood.pose.freealign_paper import FreeAlignPaperConfig
        import opencood.extrinsics.pose_correction.stage1_freealign as stage1_freealign

        ego_center = (5.0, 0.0, 0.0)
        cav_center = (-7.0, 0.0, 0.0)
        stage1 = {
            "0": {
                "cav_id_list": ["0", "1"],
                "pred_corner3d_np_list": [
                    [_cube_corners(ego_center).tolist()],
                    [_cube_corners(cav_center).tolist()],
                ],
                "pred_score_np_list": [[0.9], [0.9]],
            }
        }
        base_data_dict = {
            "0": {"ego": True, "params": {"lidar_pose": [0, 0, 0, 0, 0, 0]}},
            "1": {"ego": False, "params": {"lidar_pose": [10, 0, 0, 0, 0, 0]}},
        }

        calls = []
        orig = stage1_freealign._compute_match_stats

        def _spy_match_stats(src_boxes, dst_boxes, T_rel, *, bbox_type: str, distance_threshold_m: float):
            src_c, _, _, _ = bbox3d_to_state7(src_boxes[0])
            dst_c, _, _, _ = bbox3d_to_state7(dst_boxes[0])
            calls.append((float(src_c[0]), float(dst_c[0])))
            # Return a stable, non-rejecting pair so compare gate doesn't drop rel_T_est.
            return 0.5, 1

        try:
            stage1_freealign._compute_match_stats = _spy_match_stats  # type: ignore[assignment]
            cfg = FreeAlignPaperConfig(compare_with_current=True, compare_distance_threshold_m=3.0)
            corr = Stage1FreeAlignPoseCorrector(cfg=cfg, bbox_type="detected")
            # Bypass estimator so the test is deterministic and fast.
            corr._rel_T_est_cache[(0, "1")] = np.eye(4, dtype=np.float64)
            updated = corr.apply(sample_idx=0, cav_id_list=["0", "1"], base_data_dict=base_data_dict, stage1_result=stage1)
        finally:
            stage1_freealign._compute_match_stats = orig  # type: ignore[assignment]

        self.assertTrue(updated)
        self.assertGreaterEqual(len(calls), 2)
        for src_x, dst_x in calls[:2]:
            self.assertAlmostEqual(src_x, float(cav_center[0]), places=5)
            self.assertAlmostEqual(dst_x, float(ego_center[0]), places=5)


if __name__ == "__main__":
    unittest.main()

