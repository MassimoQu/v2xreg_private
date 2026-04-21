import json
import tempfile
import unittest
from pathlib import Path

from tools.validate_stage1_cache import resolve_stage1_path, validate_stage1_dict


class ValidateStage1CacheTest(unittest.TestCase):
    def test_resolve_stage1_dir(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            self.assertEqual(resolve_stage1_path(p), p / "stage1_boxes.json")
            self.assertEqual(resolve_stage1_path(p / "stage1_boxes.json"), p / "stage1_boxes.json")

    def test_validate_stage1_ok(self):
        obj = {
            "0": {
                "cav_id_list": ["1", "2"],
                "pred_corner3d_np_list": [[], []],
                "lidar_pose_clean_np": [[0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0]],
            },
            "1": {
                "cav_id_list": ["3"],
                "pred_corner3d_np_list": [[]],
                "lidar_pose_clean_np": [[0, 0, 0, 0, 0, 0]],
            },
        }
        errors = validate_stage1_dict(
            obj,
            expected_samples=2,
            require_fields=["pred_corner3d_np_list", "cav_id_list", "lidar_pose_clean_np"],
            require_contiguous_keys=True,
        )
        self.assertEqual(errors, [])

    def test_validate_stage1_len_mismatch(self):
        obj = {
            "0": {
                "cav_id_list": ["1", "2"],
                "pred_corner3d_np_list": [[]],
                "lidar_pose_clean_np": [[0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0]],
            }
        }
        errors = validate_stage1_dict(
            obj,
            expected_samples=1,
            require_fields=["pred_corner3d_np_list", "cav_id_list", "lidar_pose_clean_np"],
        )
        self.assertTrue(any("len(cav_id_list)" in e for e in errors))

    def test_validate_stage1_missing_field(self):
        obj = {
            "0": {
                "cav_id_list": ["1"],
                "pred_corner3d_np_list": [[]],
            }
        }
        errors = validate_stage1_dict(
            obj,
            expected_samples=1,
            require_fields=["pred_corner3d_np_list", "cav_id_list", "lidar_pose_clean_np"],
        )
        self.assertTrue(any("missing field lidar_pose_clean_np" in e for e in errors))


if __name__ == "__main__":
    unittest.main()

