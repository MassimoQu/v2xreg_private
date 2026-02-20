#!/usr/bin/env python3
import argparse
import os
import shlex
from datetime import datetime
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]
PYTHON_BIN = ROOT / ".micromamba" / "envs" / "py39" / "bin" / "python"
SCRIPT = ROOT / "HEAL" / "opencood" / "tools" / "inference_w_noise.py"

CAMERA_MODEL = ROOT / "HEAL" / "opencood" / "logs" / "HeterBaseline_DAIR_camera_v2xvit_2023_09_09_11_27_38"
LIDAR_MODEL = ROOT / "HEAL" / "opencood" / "logs" / "HeterBaseline_DAIR_lidar_v2xvit_2023_09_09_11_19_26"

CAMERA_STAGE1 = ROOT / "data" / "DAIR-V2X" / "detected" / "camera_v2xvit_stage1" / "stage1_boxes.json"
LIDAR_STAGE1 = ROOT / "data" / "DAIR-V2X" / "detected" / "veh_rsu_dual_bevpeaks_occscore" / "stage1_boxes.json"

CAMERA_SINGLE_MODEL = ROOT / "HEAL" / "opencood" / "logs" / "Pyramid_DAIR_m2_lssresnet_single_2025_11_24_23_53_08"
LIDAR_SINGLE_MODEL = ROOT / "HEAL" / "opencood" / "logs" / "Pyramid_DAIR_m1_pointpillars_single_2025_11_24_18_47_23"

V2XREGPP_CONFIG = ROOT / "configs" / "pipeline_midfusion_detection_occ.yaml"


METHODS = {
    "v2xregpp": {
        "initfree": "v2xregpp_initfree",
        "stable": "v2xregpp_stable",
        "needs_stage1": True,
        "extra_args": [f"--v2xregpp-config {V2XREGPP_CONFIG}"],
    },
    "freealign": {
        "initfree": "freealign_paper",
        "stable": "freealign_paper_stable",
        "needs_stage1": True,
        "extra_args": [],
    },
    "vips": {
        "initfree": "vips_initfree",
        "stable": "vips_stable",
        "needs_stage1": True,
        "extra_args": [],
    },
    "cbm": {
        "initfree": "cbm_initfree",
        "stable": "cbm_stable",
        "needs_stage1": True,
        "extra_args": [],
    },
}


def build_jobs(
    run_id: str,
    noise_list: str,
    rot_list: str,
    dropout_prob: float,
    include_dropout: bool,
    *,
    camera_model: Path,
    lidar_model: Path,
    camera_stage1: Path,
    lidar_stage1: Path,
    camera_single_model: Optional[Path],
    lidar_single_model: Optional[Path],
    single_from_coop: bool,
):
    jobs = []
    for modality, model_dir, stage1, single_model in (
        ("camera", camera_model, camera_stage1, camera_single_model),
        ("lidar", lidar_model, lidar_stage1, lidar_single_model),
    ):
        effective_single = single_model
        if effective_single is None and single_from_coop:
            effective_single = model_dir
        # noise sweep
        jobs.extend(
            _build_sweep_jobs(
                run_id=run_id,
                modality=modality,
                model_dir=model_dir,
                stage1=stage1,
                sweep_tag="noise10",
                noise_list=noise_list,
                rot_list=rot_list,
                dropout_prob=0.0,
                include_single=False,
            )
        )
        if effective_single is not None:
            jobs.extend(
                _build_single_jobs(
                    run_id=run_id,
                    modality=modality,
                    model_dir=effective_single,
                    sweep_tag="noise10",
                    noise_list=noise_list,
                    rot_list=rot_list,
                    dropout_prob=0.0,
                )
            )
        if include_dropout:
            jobs.extend(
                _build_sweep_jobs(
                    run_id=run_id,
                    modality=modality,
                    model_dir=model_dir,
                    stage1=stage1,
                    sweep_tag="drop20",
                    noise_list=noise_list,
                    rot_list=rot_list,
                    dropout_prob=dropout_prob,
                    include_single=False,
                )
            )
            if effective_single is not None:
                jobs.extend(
                    _build_single_jobs(
                        run_id=run_id,
                        modality=modality,
                        model_dir=effective_single,
                        sweep_tag="drop20",
                        noise_list=noise_list,
                        rot_list=rot_list,
                        dropout_prob=dropout_prob,
                    )
                )
    return jobs


def _build_sweep_jobs(*, run_id, modality, model_dir, stage1, sweep_tag, noise_list, rot_list, dropout_prob, include_single):
    jobs = []
    common = [
        f"--model_dir {model_dir}",
        "--fusion_method intermediate",
        f"--pos-std-list {noise_list}",
        f"--rot-std-list {rot_list}",
        "--sweep-mode paired",
        "--noise-target non-ego",
        "--num-workers 0",
        "--log-interval 200",
        "--pose-timing",
        "--pose-device cuda",
    ]
    if dropout_prob and dropout_prob > 0:
        common.append(f"--pose-dropout-prob {dropout_prob}")

    if include_single:
        note = f"_{run_id}_{modality}_{sweep_tag}_single"
        cmd = _build_cmd(common, f"--fusion_method single --pose-correction none --note {note}")
        jobs.append((f"{modality}_{sweep_tag}_single", cmd))

    # coop baseline (no correction)
    note = f"_{run_id}_{modality}_{sweep_tag}_baseline"
    cmd = _build_cmd(common, f"--pose-correction none --note {note}")
    jobs.append((f"{modality}_{sweep_tag}_baseline", cmd))

    # oracle GT
    note = f"_{run_id}_{modality}_{sweep_tag}_oracle"
    cmd = _build_cmd(common, f"--pose-correction oracle_gt --note {note}")
    jobs.append((f"{modality}_{sweep_tag}_oracle", cmd))

    for method_name, meta in METHODS.items():
        # best-of (compare current)
        initfree = meta["initfree"]
        note = f"_{run_id}_{modality}_{sweep_tag}_{method_name}_best"
        args = [f"--pose-correction {initfree}", "--pose-compare-current", f"--note {note}"]
        if meta["needs_stage1"]:
            args.append(f"--stage1-result {stage1}")
        args.extend(meta.get("extra_args", []))
        cmd = _build_cmd(common, " ".join(args))
        jobs.append((f"{modality}_{sweep_tag}_{method_name}_best", cmd))

        # stable
        stable = meta["stable"]
        note = f"_{run_id}_{modality}_{sweep_tag}_{method_name}_stable"
        args = [f"--pose-correction {stable}", f"--note {note}"]
        if meta["needs_stage1"]:
            args.append(f"--stage1-result {stage1}")
        args.extend(meta.get("extra_args", []))
        cmd = _build_cmd(common, " ".join(args))
        jobs.append((f"{modality}_{sweep_tag}_{method_name}_stable", cmd))

    return jobs


def _build_single_jobs(*, run_id, modality, model_dir, sweep_tag, noise_list, rot_list, dropout_prob):
    jobs = []
    common = [
        f"--model_dir {model_dir}",
        "--fusion_method intermediate",
        "--comm-range-override 0",
        "--pos-std-list 0",
        "--rot-std-list 0",
        "--sweep-mode paired",
        "--noise-target non-ego",
        "--num-workers 0",
        "--log-interval 200",
        "--pose-timing",
        "--pose-device cuda",
    ]
    if dropout_prob and dropout_prob > 0:
        common.append(f"--pose-dropout-prob {dropout_prob}")

    note = f"_{run_id}_{modality}_{sweep_tag}_single"
    cmd = _build_cmd(common, f"--pose-correction none --note {note}")
    jobs.append((f"{modality}_{sweep_tag}_single", cmd))
    return jobs


def _build_cmd(common_args, extra_args):
    base = [
        f"PYTHONPATH={ROOT / 'HEAL'}",
        str(PYTHON_BIN),
        str(SCRIPT),
    ]
    cmd = " ".join(base + common_args + [extra_args])
    return cmd


def write_runlists(run_id: str, jobs, gpus):
    out_dir = ROOT / "outputs" / f"full_bench_{run_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = out_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    master_log = out_dir / "master.log"

    runlists = {gpu: [] for gpu in gpus}
    for idx, (name, cmd) in enumerate(jobs):
        gpu = gpus[idx % len(gpus)]
        log_path = logs_dir / f"{name}.log"
        runlists[gpu].append((name, cmd, log_path))

    for gpu, entries in runlists.items():
        script_path = out_dir / f"runlist_gpu{gpu}.sh"
        with script_path.open("w", encoding="utf-8") as fh:
            fh.write("#!/usr/bin/env bash\nset -euo pipefail\n")
            fh.write(f"export CUDA_VISIBLE_DEVICES={gpu}\n")
            fh.write(f"cd {ROOT}\n")
            fh.write(f"export PYTHONPATH={ROOT / 'HEAL'}\n")
            fh.write("export OPENCOOD_VOXEL_GPU=1\n")
            for name, cmd, log_path in entries:
                fh.write(f"echo '[{name}] '$(date -Iseconds) | tee -a {master_log}\n")
                safe_cmd = shlex.quote(f"{cmd} > {log_path} 2>&1")
                fh.write(f"bash -lc {safe_cmd}\n")
        script_path.chmod(0o755)
    return out_dir


def launch_runlists(out_dir, gpus):
    for gpu in gpus:
        script_path = out_dir / f"runlist_gpu{gpu}.sh"
        if not script_path.exists():
            continue
        log_path = out_dir / f"runner_gpu{gpu}.log"
        cmd = f"nohup bash {script_path} > {log_path} 2>&1 &"
        os.system(cmd)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--gpus", type=str, default="0,1,2,3,4,5,6,7,8,9")
    parser.add_argument("--noise-list", type=str, default="1,2,3,4,5,6,7,8,9,10")
    parser.add_argument("--rot-list", type=str, default="1,2,3,4,5,6,7,8,9,10")
    parser.add_argument("--dropout", type=float, default=0.2)
    parser.add_argument("--no-dropout", action="store_true")
    parser.add_argument("--camera-model", type=str, default=str(CAMERA_MODEL))
    parser.add_argument("--lidar-model", type=str, default=str(LIDAR_MODEL))
    parser.add_argument("--camera-stage1", type=str, default=str(CAMERA_STAGE1))
    parser.add_argument("--lidar-stage1", type=str, default=str(LIDAR_STAGE1))
    parser.add_argument("--camera-single-model", type=str, default=str(CAMERA_SINGLE_MODEL))
    parser.add_argument("--lidar-single-model", type=str, default=str(LIDAR_SINGLE_MODEL))
    parser.add_argument(
        "--single-from-coop",
        action="store_true",
        help="Use coop model for single baseline if single model path is empty.",
    )
    parser.add_argument("--launch", action="store_true")
    args = parser.parse_args()

    run_id = args.run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    gpus = [int(x) for x in args.gpus.split(",") if x.strip()]
    jobs = build_jobs(
        run_id=run_id,
        noise_list=args.noise_list,
        rot_list=args.rot_list,
        dropout_prob=float(args.dropout),
        include_dropout=not args.no_dropout,
        camera_model=Path(args.camera_model),
        lidar_model=Path(args.lidar_model),
        camera_stage1=Path(args.camera_stage1),
        lidar_stage1=Path(args.lidar_stage1),
        camera_single_model=Path(args.camera_single_model) if args.camera_single_model else None,
        lidar_single_model=Path(args.lidar_single_model) if args.lidar_single_model else None,
        single_from_coop=bool(args.single_from_coop),
    )
    out_dir = write_runlists(run_id, jobs, gpus)
    print(f"Runlists written to: {out_dir}")
    if args.launch:
        launch_runlists(out_dir, gpus)
        print("Launched runlists.")


if __name__ == "__main__":
    main()
