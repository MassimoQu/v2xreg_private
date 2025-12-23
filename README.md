# V2I-Calib / V2X-Reg++: Object-Level Online Point Cloud Registration for V2I/V2X

<h3 align="center">
  <a href="https://ieeexplore.ieee.org/abstract/document/10802098"><img src="https://img.shields.io/badge/IROS24-Paper-blue?logo=paper"/> </a>
  <a href="https://arxiv.org/abs/2410.11008"><img src="https://img.shields.io/badge/TITS-arXiv_2410.11008-b31b1b?logo=arxiv" alt="arXiv" /></a>
</h3>

<div align="center">
  <img src="./static/images/V2I-CALIB++_workflow_v2.png" alt="V2I-CALIB++ workflow" width="88%">
</div>

## Status (public)

- 实验数据正在整理（本仓库提供复现实验脚本；论文中的表格/数字以论文为准）。
- This public tree is curated to stay aligned with the paper narrative; additional exploratory notes/results are intentionally not published here.

## Highlights

- Initialization-free online calibration for vehicle–infrastructure / multi-terminal sensing using perception objects.
- Two variants are supported:
  - **V2I-Calib**: oIoU-based association (IROS 2024).
  - **V2X-Reg++**: distance-based association (arXiv/TITS).

## Installation

```bash
conda create -n v2xreg python=3.10 -y
conda activate v2xreg
pip install -r requirements.txt
```

Optional (only for baseline scripts under `benchmarks/`):
```bash
git submodule update --init --recursive
pip install open3d==0.17.* torch==2.3.*
```

## Data: DAIR-V2X

The object-level pipeline expects the official DAIR-V2X cooperative split under:
- `data/DAIR-V2X/cooperative-vehicle-infrastructure/`

If you keep the dataset elsewhere, symlink it:
```bash
ln -s /path/to/cooperative-vehicle-infrastructure data/DAIR-V2X/cooperative-vehicle-infrastructure
```

## Run (DAIR-V2X)

- Single run (GT boxes):
  ```bash
  python tools/run_calibration.py --config configs/pipeline.yaml --print
  ```

- Table III GT sweeps (Top-3000 subset):
  ```bash
  python tools/run_dair_pipeline_experiments.py --config configs/pipeline_top3000.yaml
  ```

Outputs are written to `outputs/<tag>/` (`metrics.json`, `matches.jsonl`).

## Detector boxes (optional)

Detector caches are not tracked by git (see `.gitignore`). Use:
- `configs/pipeline_detection.yaml`
- `configs/pipeline_detection_pp.yaml`
- `configs/pipeline_detection_sc.yaml`

HEAL stage-1 exports can be converted into the expected cache schema via:
```bash
python tools/heal_stage1_to_detection_cache.py --help
```

## Docs

- Minimal entrypoint: `docs/operations/experiment_progress_public.md`
- Reproduction guide: `docs/operations/experiment_reproduction.md`

## Acknowledgment

This project is not possible without the following codebases:
- [DAIR-V2X](https://github.com/AIR-THU/DAIR-V2X)
- [LiDAR-Registration-Benchmark](https://github.com/HKUST-Aerial-Robotics/LiDAR-Registration-Benchmark)

## Citation

If you find our work or this repo useful, please cite:
```
@inproceedings{qu2024v2i,
  title={V2I-Calib: A novel calibration approach for collaborative vehicle and infrastructure lidar systems},
  author={Qu, Qianxin and Xiong, Yijin and Zhang, Guipeng and Wu, Xin and Gao, Xiaohan and Gao, Xin and Li, Hanyu and Guo, Shichun and Zhang, Guoying},
  booktitle={2024 IEEE/RSJ International Conference on Intelligent Robots and Systems (IROS)},
  pages={892--897},
  year={2024},
  organization={IEEE}
}
```
```
@article{qu2024v2iplus,
  title={V2X-Reg++: A Multi-terminal Spatial Calibration Approach in Urban Intersections for Collaborative Perception},
  author={Qu, Qianxin and Zhang, Xinyu and Xiong, Yijin and Guo, Shichun and Song, Ziqiang and Li, Jun},
  journal={arXiv preprint arXiv:2410.11008},
  year={2024}
}
```
