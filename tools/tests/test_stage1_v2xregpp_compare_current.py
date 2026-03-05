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


class Stage1V2XRegPPCompareCurrentTest(unittest.TestCase):
    def test_initfree_only_receives_T_current_when_compare_with_current_enabled(self):
        from opencood.extrinsics.pose_correction.stage1_v2xregpp import Stage1V2XRegPPPoseCorrector

        stage1 = {
            "0": {
                "cav_id_list": ["0", "1"],
                "pred_corner3d_np_list": [
                    [_cube_corners((0.0, 0.0, 0.0)).tolist()],
                    [_cube_corners((5.0, 0.0, 0.0)).tolist()],
                ],
                "pred_score_np_list": [[0.9], [0.9]],
            }
        }
        base_data_dict = {
            "0": {"ego": True, "params": {"lidar_pose": [0, 0, 0, 0, 0, 0]}},
            "1": {"ego": False, "params": {"lidar_pose": [10, 0, 0, 0, 0, 0]}},
        }

        def _run(compare_with_current: bool):
            corr = Stage1V2XRegPPPoseCorrector(
                config_path="configs/dair/midfusion/pipeline_midfusion_detection_occ.yaml",
                mode="initfree",
                compare_with_current=bool(compare_with_current),
                min_matches=1,
                min_stability=0.0,
            )
            seen = []

            def _fake_estimate(src_boxes, dst_boxes, occ_src, occ_dst, bev_range, *, T_current=None):
                seen.append(T_current is not None)
                return {
                    "source": "late",
                    "T": np.eye(4, dtype=np.float64),
                    "matches": [],
                    "matched": 3,
                    "stability": 3.0,
                    "precision": 1.0,
                }

            corr._estimate_rel_T = _fake_estimate  # type: ignore[assignment]
            updated = corr.apply(
                sample_idx=0,
                cav_id_list=["0", "1"],
                base_data_dict=base_data_dict,
                stage1_result=stage1,
            )
            self.assertTrue(updated)
            self.assertEqual(len(seen), 1)
            return bool(seen[0])

        self.assertFalse(_run(False))
        self.assertTrue(_run(True))


if __name__ == "__main__":
    unittest.main()

