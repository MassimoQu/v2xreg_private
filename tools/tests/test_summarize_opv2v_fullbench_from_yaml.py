import tempfile
import unittest
from pathlib import Path

import yaml

from tools.summarize_opv2v_fullbench_from_yaml import build_series, collect_entries


class SummarizeFromYamlTest(unittest.TestCase):
    def test_collect_entries_baseline_and_pose_solver(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            # Baseline YAML (no pose_solver).
            baseline_path = tmp / "AP030507_none_rid_lidar_noise10_baseline_n1.0.yaml"
            baseline_obj = {
                "ap30": [0.1],
                "ap50": [0.2],
                "ap70": [0.3],
                "pos_std_list": [1.0],
                "timing_stats": [
                    {
                        "infer_fps": 1.0,
                        "infer_sec": 2.0,
                        "pose_fps": 3.0,
                        "pose_sec": 0.0,
                        "samples": 10,
                    }
                ],
            }
            baseline_path.write_text(yaml.safe_dump(baseline_obj), encoding="utf-8")

            # Pose-correction YAML (has pose_solver).
            corr_path = tmp / "AP030507_v2xregpp_initfree_rid_lidar_noise10_v2xregpp_best_n1.0.yaml"
            corr_obj = {
                "ap50": [0.5],
                "pos_std_list": [1.0],
                "timing_stats": [
                    {
                        "infer_fps": 1.0,
                        "pose_solver": {"applied": 5, "avg_time_sec": 0.01, "samples": 10},
                        "samples": 10,
                    }
                ],
            }
            corr_path.write_text(yaml.safe_dump(corr_obj), encoding="utf-8")

            data = collect_entries(run_id="rid", camera_model_dir=tmp / "empty", lidar_model_dir=tmp)
            baseline_key = ("lidar", "noise10", "baseline", "bounds", "1.0")
            corr_key = ("lidar", "noise10", "v2xregpp", "best", "1.0")

            self.assertIn(baseline_key, data)
            self.assertIn(corr_key, data)

            self.assertAlmostEqual(data[baseline_key]["ap50"], 0.2, places=6)
            self.assertTrue("pose_solver_applied" not in data[baseline_key])

            self.assertEqual(data[corr_key]["pose_solver_applied"], 5)
            self.assertAlmostEqual(data[corr_key]["pose_solver_avg_time_sec"], 0.01, places=6)

            series = build_series(data, modality="lidar", sweep="noise10", field="ap50")
            self.assertAlmostEqual(series[("baseline", "bounds")]["1.0"], 0.2, places=6)
            self.assertAlmostEqual(series[("v2xregpp", "best")]["1.0"], 0.5, places=6)


if __name__ == "__main__":
    unittest.main()

