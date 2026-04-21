#!/usr/bin/env python3
"""
Evidence helper: compare merged GT counts produced by OpenCOOD dataset pipeline
under different `comm_range` settings.

This mirrors the user's requested measurement:
  - Use OPV2V LiDAR config from a model_dir/config.yaml
  - Build test split (validate_dir <- test_dir)
  - batch_size=1, num_workers=0
  - Count GT objects via `batch['ego']['object_bbx_mask'].sum()` after
    `collate_batch_test`

We keep pose noise deterministic by disabling it (add_noise=False) and forcing
std=0 (belt-and-suspenders).
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import random
from typing import Any, Dict, List, Tuple

import numpy as np
import torch
from torch.utils.data import DataLoader

# spconv CPU voxelizers can crash (SIGFPE) on some environments. We only need
# labels for this evidence script, so force the safe numpy fallback by default.
os.environ.setdefault("OPENCOOD_DISABLE_SPCONV", "1")

from opencood.data_utils.datasets import build_dataset
from opencood.hypes_yaml import yaml_utils


def _set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def _as_int_mask_sum(mask: Any) -> int:
    """
    Handle slight representation differences across dataset collate fns:
      - torch.Tensor
      - np.ndarray
      - list (batch dimension) of either of the above
    """
    if isinstance(mask, list):
        if len(mask) == 0:
            return 0
        # batch_size=1 => take the first.
        mask = mask[0]
    if torch.is_tensor(mask):
        return int(mask.sum().item())
    return int(np.asarray(mask).sum())


def _stats(counts: List[int]) -> Dict[str, float]:
    arr = np.asarray(counts, dtype=np.float64)
    if arr.size == 0:
        return {"mean": float("nan"), "p50": float("nan"), "p90": float("nan")}
    return {
        "mean": float(np.mean(arr)),
        "p50": float(np.percentile(arr, 50)),
        "p90": float(np.percentile(arr, 90)),
    }


def _collect_counts(
    hypes: Dict[str, Any],
    *,
    comm_range: float,
    max_samples: int,
    num_workers: int,
) -> Tuple[List[int], List[Any]]:
    h = copy.deepcopy(hypes)
    h["comm_range"] = float(comm_range)

    # Make sure "test" split is used (OPV2VBaseDataset uses validate_dir when train=False).
    if "test_dir" in h:
        h["validate_dir"] = h["test_dir"]

    # Deterministic: disable synthetic pose noise.
    noise = dict(h.get("noise_setting") or {})
    noise["add_noise"] = False
    args = dict(noise.get("args") or {})
    args.setdefault("pos_std", 0.0)
    args.setdefault("rot_std", 0.0)
    args.setdefault("pos_mean", 0.0)
    args.setdefault("rot_mean", 0.0)
    # Keep default target, but it doesn't matter when add_noise=False.
    noise["args"] = args
    h["noise_setting"] = noise

    ds = build_dataset(h, visualize=False, train=False)
    loader = DataLoader(
        ds,
        batch_size=1,
        shuffle=False,
        num_workers=int(num_workers),
        collate_fn=ds.collate_batch_test,
    )

    counts: List[int] = []
    sample_indices: List[Any] = []
    for batch in loader:
        if batch is None:
            continue
        ego = batch.get("ego") if isinstance(batch, dict) else None
        if not isinstance(ego, dict):
            continue
        counts.append(_as_int_mask_sum(ego.get("object_bbx_mask")))
        sample_indices.append(ego.get("sample_idx"))
        if len(counts) >= int(max_samples):
            break

    return counts, sample_indices


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--model-dir",
        type=str,
        required=True,
        help="Model directory that contains config.yaml (loaded via yaml_utils).",
    )
    ap.add_argument("--max-samples", type=int, default=200)
    ap.add_argument("--num-workers", type=int, default=0)
    ap.add_argument(
        "--comm-ranges",
        type=str,
        default="70,0",
        help="Comma-separated comm_range values to compare (e.g. '70,0').",
    )
    ap.add_argument(
        "--out",
        type=str,
        required=True,
        help="Output JSON path to write counts + summary stats.",
    )
    ap.add_argument("--seed", type=int, default=303)
    args = ap.parse_args()

    _set_seed(int(args.seed))

    model_dir = os.path.abspath(args.model_dir)
    hypes = yaml_utils.load_yaml(os.path.join(model_dir, "config.yaml"))

    comm_ranges = []
    for part in str(args.comm_ranges).split(","):
        part = part.strip()
        if not part:
            continue
        comm_ranges.append(float(part))
    if len(comm_ranges) < 1:
        raise SystemExit("No comm ranges provided")

    runs: Dict[str, Any] = {}
    sample_idx_ref: List[Any] | None = None
    for cr in comm_ranges:
        counts, sample_indices = _collect_counts(
            hypes,
            comm_range=cr,
            max_samples=int(args.max_samples),
            num_workers=int(args.num_workers),
        )
        key = f"comm_range_{int(cr) if float(cr).is_integer() else cr}"
        runs[key] = {
            "comm_range": float(cr),
            "n": int(len(counts)),
            "stats": _stats(counts),
            "counts": counts,
            "sample_idx": sample_indices,
        }
        if sample_idx_ref is None:
            sample_idx_ref = sample_indices
        else:
            # Keep a quick parity check for evidence-grade runs.
            runs[key]["sample_idx_matches_first_run"] = bool(sample_indices == sample_idx_ref)

    out = {
        "model_dir": model_dir,
        "config_yaml": os.path.join(model_dir, "config.yaml"),
        "split": "test (validate_dir <- test_dir)",
        "max_samples": int(args.max_samples),
        "seed": int(args.seed),
        "runs": runs,
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2, sort_keys=True)

    # Print a compact summary to stdout for logs.
    print(json.dumps({k: v["stats"] for k, v in runs.items()}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
