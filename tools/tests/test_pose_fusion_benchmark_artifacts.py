import json
import tempfile
import unittest
from pathlib import Path

from tools.pose_fusion_benchmark_artifacts import (
    build_manifest,
    consolidate_results,
    evaluate_gates,
)


class PoseFusionBenchmarkArtifactsTest(unittest.TestCase):
    def test_build_manifest_contains_hashes(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cfg = tmp / "config.yaml"
            ckpt = tmp / "model.pth"
            script = tmp / "run.py"
            stage1 = tmp / "stage1.json"
            result = tmp / "result.jsonl"

            cfg.write_text("a: 1\n", encoding="utf-8")
            ckpt.write_text("weights", encoding="utf-8")
            script.write_text("print('x')\n", encoding="utf-8")
            stage1.write_text("{}\n", encoding="utf-8")
            result.write_text(json.dumps({"mean_ap50": 0.2}) + "\n", encoding="utf-8")

            manifest = build_manifest(
                run_id="utest",
                dataset_split="val",
                runtime_mode="register_and_fuse",
                solver_backend="online_box",
                fusion_method="v2xvit",
                noise_schedule="1..10",
                dropout_schedule="0.0,0.2",
                model_dirs=[str(tmp)],
                config_files=[str(cfg)],
                checkpoint_files=[str(ckpt)],
                script_files=[str(script)],
                stage1_files=[str(stage1)],
                result_sources=[str(result)],
                extras={"seed": "0"},
            )

            self.assertEqual(manifest["run_id"], "utest")
            config_entry = manifest["artifacts"]["config_files"][0]
            self.assertTrue(config_entry["exists"])
            self.assertIn("sha256", config_entry)
            self.assertEqual(manifest["extras"]["seed"], "0")

    def test_gate_eval_pass_then_leak_fail(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            manifest = tmp / "manifest.json"
            manifest.write_text(
                json.dumps({"run_id": "ut", "protocol": {}, "artifacts": {}}),
                encoding="utf-8",
            )

            t02_base = tmp / "t02_base.json"
            t02_prov = tmp / "t02_prov.json"
            t03_off = tmp / "t03_off.json"
            t03_on = tmp / "t03_on.json"

            t02_base.write_text(
                json.dumps({"mean_ap30": 0.3, "mean_ap50": 0.2, "mean_ap70": 0.1}),
                encoding="utf-8",
            )
            t02_prov.write_text(
                json.dumps({"mean_ap30": 0.30001, "mean_ap50": 0.20001, "mean_ap70": 0.10001}),
                encoding="utf-8",
            )
            t03_off.write_text(
                json.dumps(
                    {
                        "mean_ap30": 0.4,
                        "mean_ap50": 0.3,
                        "mean_ap70": 0.2,
                        "mean_rel_trans_m": 1.0,
                        "mean_rel_yaw_deg": 2.0,
                    }
                ),
                encoding="utf-8",
            )
            t03_on.write_text(
                json.dumps(
                    {
                        "mean_ap30": 0.40001,
                        "mean_ap50": 0.30001,
                        "mean_ap70": 0.20001,
                        "mean_rel_trans_m": 1.0005,
                        "mean_rel_yaw_deg": 2.0005,
                    }
                ),
                encoding="utf-8",
            )

            safe_file = tmp / "run_normal.jsonl"
            oracle_file = tmp / "run_oracle.jsonl"
            safe_file.write_text('{"pose_source": "pred"}\n', encoding="utf-8")
            oracle_file.write_text('{"pose_source": "gt", "note": "oracle"}\n', encoding="utf-8")

            gates = evaluate_gates(
                run_id="ut",
                manifest_path=manifest,
                t01_command="true",
                t01_timeout_sec=30,
                run_t01=False,
                t02_baseline=t02_base,
                t02_provider=t02_prov,
                t03_offline=t03_off,
                t03_online=t03_on,
                t02_ap_threshold=1e-3,
                t03_ap_threshold=1e-3,
                t03_pose_threshold=1e-3,
                audit_patterns=[str(tmp / "run_*.jsonl")],
                leak_patterns=[r'pose_source"?\s*[:=]\s*[\'"]?gt'],
                oracle_allow_pattern=r"oracle",
                strict=True,
            )
            status = {g.gate_id: g.status for g in gates}
            self.assertEqual(status["T00"], "PASS")
            self.assertEqual(status["T02"], "PASS")
            self.assertEqual(status["T03"], "PASS")
            self.assertEqual(status["T04"], "PASS")

            bad_file = tmp / "run_non_oracle_bad.jsonl"
            bad_file.write_text('{"pose_source": "gt", "note": "bad"}\n', encoding="utf-8")
            gates_bad = evaluate_gates(
                run_id="ut",
                manifest_path=manifest,
                t01_command="true",
                t01_timeout_sec=30,
                run_t01=False,
                t02_baseline=t02_base,
                t02_provider=t02_prov,
                t03_offline=t03_off,
                t03_online=t03_on,
                t02_ap_threshold=1e-3,
                t03_ap_threshold=1e-3,
                t03_pose_threshold=1e-3,
                audit_patterns=[str(tmp / "run_*.jsonl")],
                leak_patterns=[r'pose_source"?\s*[:=]\s*[\'"]?gt'],
                oracle_allow_pattern=r"(^|/)run_oracle",
                strict=True,
            )
            bad_status = {g.gate_id: g.status for g in gates_bad}
            self.assertEqual(bad_status["T04"], "FAIL")

    def test_extended_gates_pass(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            manifest = tmp / "manifest.json"
            manifest_payload = {
                "run_id": "ut",
                "created_at_utc": "x",
                "protocol": {
                    "dataset_split": "test",
                    "runtime_mode": "register_and_fuse",
                    "solver_backend": "online_box",
                    "fusion_method": "v2xvit",
                },
                "artifacts": {},
                "extras": {},
            }
            manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")
            manifest_ref = tmp / "manifest_ref.json"
            manifest_ref.write_text(json.dumps(manifest_payload), encoding="utf-8")

            metric = tmp / "metric.json"
            metric.write_text(
                json.dumps(
                    {
                        "mean_ap30": 0.1,
                        "mean_ap50": 0.2,
                        "mean_ap70": 0.3,
                        "mean_rel_trans_m": 1.0,
                        "mean_rel_yaw_deg": 2.0,
                        "mean_infer_fps": 1.0,
                    }
                ),
                encoding="utf-8",
            )

            audit = tmp / "audit_oracle.jsonl"
            audit.write_text('{"pose_source":"gt","note":"oracle"}\n', encoding="utf-8")

            t06 = tmp / "t06.jsonl"
            t06.write_text(
                json.dumps({"pose_timing": {"cpu_fallback_count": 0, "match_sec": 0.1, "solver_sec": 0.2}})
                + "\n",
                encoding="utf-8",
            )

            metric_fast = tmp / "metric_fast.json"
            metric_fast.write_text(
                json.dumps(
                    {
                        "mean_ap30": 0.1,
                        "mean_ap50": 0.2,
                        "mean_ap70": 0.3,
                        "mean_rel_trans_m": 1.0,
                        "mean_rel_yaw_deg": 2.0,
                        "mean_infer_fps": 1.5,
                    }
                ),
                encoding="utf-8",
            )

            t08_ref = tmp / "t08_ref.jsonl"
            t08_ref.write_text(
                "\n".join(
                    [
                        json.dumps({"method": "v2xregpp", "strategy": "best", "mean_ap50": 0.5}),
                        json.dumps({"method": "freealign", "strategy": "best", "mean_ap50": 0.4}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            t08_cand = tmp / "t08_cand.jsonl"
            t08_cand.write_text(t08_ref.read_text(encoding="utf-8"), encoding="utf-8")

            t09 = tmp / "t09.jsonl"
            t09.write_text(
                "\n".join(
                    [
                        json.dumps({"runtime_mode": "single_only"}),
                        json.dumps({"runtime_mode": "fusion_only", "pose_source": "identity"}),
                        json.dumps({"runtime_mode": "fusion_only", "pose_source": "gt"}),
                        json.dumps({"runtime_mode": "register_and_fuse", "method": "v2xregpp"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            gates = evaluate_gates(
                run_id="ut",
                manifest_path=manifest,
                t01_command="true",
                t01_timeout_sec=30,
                run_t01=False,
                t02_baseline=metric,
                t02_provider=metric,
                t03_offline=metric,
                t03_online=metric,
                t02_ap_threshold=1e-4,
                t03_ap_threshold=1e-4,
                t03_pose_threshold=1e-3,
                audit_patterns=[str(audit)],
                leak_patterns=[r'pose_source"?\s*[:=]\s*[\'"]?gt'],
                oracle_allow_pattern=r"oracle",
                strict=True,
                t05_reference_manifest=manifest_ref,
                t05_whitelist=["run_id", "created_at_utc", "extras"],
                t06_results=t06,
                t07_reference_results=metric,
                t07_candidate_results=metric_fast,
                t07_min_gain=1.0,
                t08_reference_results=t08_ref,
                t08_candidate_results=t08_cand,
                t09_results=t09,
                t10_rollback_command="true",
                t10_timeout_sec=30,
            )
            status = {g.gate_id: g.status for g in gates}
            for key in ["T00", "T02", "T03", "T04", "T05", "T06", "T07", "T08", "T09", "T10"]:
                self.assertEqual(status[key], "PASS", msg="{} should pass".format(key))


if __name__ == "__main__":
    unittest.main()
