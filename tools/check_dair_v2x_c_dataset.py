#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def _looks_like_dair_root(root: Path) -> Path | None:
    """
    Accept either:
      - DAIR-V2X-C_DATASET_ROOT (contains cooperative-vehicle-infrastructure/)
      - cooperative-vehicle-infrastructure itself
    Returns the cooperative-vehicle-infrastructure path if valid.
    """
    root = root.expanduser().resolve()
    if (root / "cooperative").is_dir() and (root / "infrastructure-side").is_dir():
        return root
    candidate = root / "cooperative-vehicle-infrastructure"
    if (candidate / "cooperative").is_dir() and (candidate / "infrastructure-side").is_dir():
        return candidate
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate DAIR-V2X-C dataset layout for this repo.")
    parser.add_argument(
        "--dataset-root",
        type=str,
        default=None,
        help="Optional DAIR-V2X-C root (either the folder containing cooperative-vehicle-infrastructure/ or that folder).",
    )
    parser.add_argument(
        "--repo-link",
        type=str,
        default="data/DAIR-V2X/cooperative-vehicle-infrastructure",
        help="Where the repo expects cooperative-vehicle-infrastructure to live (symlink or directory).",
    )
    args = parser.parse_args()

    repo_link = Path(args.repo_link).expanduser()
    if not repo_link.is_absolute():
        repo_link = (Path(__file__).resolve().parents[1] / repo_link).resolve()

    print(f"[check] repo link: {repo_link}")
    if repo_link.exists():
        try:
            resolved = repo_link.resolve()
        except OSError:
            resolved = repo_link
        print(f"[check] repo link resolves to: {resolved}")
    else:
        print("[check] repo link is missing.")

    data_info = repo_link / "cooperative" / "data_info.json"
    ok = True
    if data_info.exists():
        print(f"[ok] found: {data_info}")
    else:
        print(f"[miss] missing: {data_info}")
        ok = False

    required_dirs = [
        repo_link / "infrastructure-side" / "calib" / "virtuallidar_to_world",
        repo_link / "vehicle-side" / "calib" / "novatel_to_world",
        repo_link / "vehicle-side" / "calib" / "lidar_to_novatel",
    ]
    for d in required_dirs:
        if d.is_dir():
            print(f"[ok] dir: {d}")
        else:
            print(f"[miss] dir: {d}")
            ok = False

    if args.dataset_root:
        provided = _looks_like_dair_root(Path(args.dataset_root))
        if provided is None:
            print(f"[error] --dataset-root does not look like DAIR-V2X-C: {args.dataset_root}")
            ok = False
        else:
            print(f"[check] provided cooperative-vehicle-infrastructure: {provided}")
            expect_info = provided / "cooperative" / "data_info.json"
            if expect_info.exists():
                print(f"[ok] provided has: {expect_info}")
            else:
                print(f"[miss] provided missing: {expect_info}")
                ok = False

            if not repo_link.exists():
                print("\n[next] To link it into the repo:")
                print(f"  ln -s {provided} {repo_link}")
            else:
                print("\n[next] Repo link already exists; adjust it if needed.")

    if ok:
        print("\n[result] OK")
        return 0
    print("\n[result] FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

