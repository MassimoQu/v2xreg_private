import unittest

import numpy as np

from tools.validate_stage1_semantics import check_stage1_semantics_dict


def _cube_corners(center_xyz, *, size=2.0):
    cx, cy, cz = [float(x) for x in center_xyz]
    d = float(size) / 2.0
    # Consistent corner ordering across boxes matters for vertex distance;
    # any consistent ordering works for this test.
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


class ValidateStage1SemanticsTest(unittest.TestCase):
    def test_semantics_passes_for_per_cav_local_frame(self):
        # Agent0 at x=0 sees an object at x=5 (local).
        # Agent1 at x=10 sees the same object at x=-5 (local).
        stage1 = {
            "0": {
                "cav_id_list": ["0", "1"],
                "pred_corner3d_np_list": [
                    [_cube_corners((5.0, 0.0, 0.0)).tolist()],
                    [_cube_corners((-5.0, 0.0, 0.0)).tolist()],
                ],
                "lidar_pose_clean_np": [
                    [0, 0, 0, 0, 0, 0],
                    [10, 0, 0, 0, 0, 0],
                ],
            }
        }
        summary = check_stage1_semantics_dict(stage1, keys=["0"], min_valid_samples=1)
        self.assertTrue(summary.ok)
        self.assertGreaterEqual(summary.total_matched_rel_clean, summary.total_matched_identity)

    def test_semantics_fails_for_common_frame_cache(self):
        # Both agents' boxes are already in the same frame (incorrect for per-CAV).
        stage1 = {
            "0": {
                "cav_id_list": ["0", "1"],
                "pred_corner3d_np_list": [
                    [_cube_corners((5.0, 0.0, 0.0)).tolist()],
                    [_cube_corners((5.0, 0.0, 0.0)).tolist()],
                ],
                "lidar_pose_clean_np": [
                    [0, 0, 0, 0, 0, 0],
                    [10, 0, 0, 0, 0, 0],
                ],
            }
        }
        summary = check_stage1_semantics_dict(stage1, keys=["0"], min_valid_samples=1)
        self.assertFalse(summary.ok)


if __name__ == "__main__":
    unittest.main()

