#!/usr/bin/env python3
"""Visualize DAIR frames grouped by Reg++ performance tier.

For each tier (T1_EXCELLENT, T4_POOR, etc.) pick representative frames
and draw a side-by-side panel: infra image | vehicle image, with
key metrics overlaid.

Usage:
    python tools/visualize_tier_frames.py \
        --run-dir outputs/full6617_dair_v2xregpp_gt25 \
        --data-root data/DAIR-V2X/cooperative-vehicle-infrastructure \
        --samples-per-tier 6
"""
import argparse
import json
import math
import random
from pathlib import Path
from collections import defaultdict

from PIL import Image, ImageDraw, ImageFont


def _load_records(run_dir: Path):
    lines = (run_dir / "matches.jsonl").read_text().strip().split("\n")
    return [json.loads(l) for l in lines]


def _load_data_info(data_root: Path):
    return json.loads((data_root / "cooperative" / "data_info.json").read_text())


def _tier(rec):
    te, re = rec["TE"], rec["RE"]
    if te == float("inf") or re == float("inf"):
        return "T0_FAIL"
    if te < 0.5 and re < 1.0:
        return "T1_EXCELLENT"
    if te < 2.0 and re < 2.0:
        return "T2_GOOD"
    if te < 5.0 and re < 5.0:
        return "T3_MODERATE"
    return "T4_POOR"


def _dist(rec):
    tx, ty, tz = rec["T6"][0], rec["T6"][1], rec["T6"][2]
    return math.sqrt(tx * tx + ty * ty + tz * tz)


def _pick_representative(records, tier_name, n):
    indices = [i for i, r in enumerate(records) if _tier(r) == tier_name]
    if not indices:
        return []
    if tier_name == "T1_EXCELLENT":
        indices.sort(key=lambda i: records[i]["TE"])
    elif tier_name == "T4_POOR":
        indices.sort(key=lambda i: -records[i]["TE"] if records[i]["TE"] != float("inf") else -1e9)
    elif tier_name == "T0_FAIL":
        random.seed(42)
        random.shuffle(indices)
    else:
        indices.sort(key=lambda i: records[i]["TE"])
    step = max(1, len(indices) // n)
    picked = indices[::step][:n]
    return picked


def _draw_panel(infra_img, veh_img, rec, idx, tier_name):
    """Create a single panel with infra (left) and vehicle (right) images."""
    w, h = infra_img.size
    scale = 640 / w
    new_w, new_h = 640, int(h * scale)
    infra_small = infra_img.resize((new_w, new_h), Image.LANCZOS)
    veh_small = veh_img.resize((new_w, new_h), Image.LANCZOS)

    panel = Image.new("RGB", (new_w * 2 + 4, new_h + 40), color=(30, 30, 30))
    panel.paste(infra_small, (0, 40))
    panel.paste(veh_small, (new_w + 4, 40))

    draw = ImageDraw.Draw(panel)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 14)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 11)
    except Exception:
        font = ImageFont.load_default()
        font_small = font

    te = rec["TE"]
    re = rec["RE"]
    te_s = f"{te:.2f}m" if te != float("inf") else "inf"
    re_s = f"{re:.2f}°" if re != float("inf") else "inf"
    dist = _dist(rec)
    n_match = len(rec["matches"])
    stab = rec["stability"]

    tier_colors = {
        "T1_EXCELLENT": (0, 200, 0),
        "T2_GOOD": (100, 200, 100),
        "T3_MODERATE": (200, 200, 0),
        "T4_POOR": (255, 60, 60),
        "T0_FAIL": (160, 160, 160),
    }
    color = tier_colors.get(tier_name, (200, 200, 200))

    header = f"[{tier_name}] idx={idx}  TE={te_s}  RE={re_s}  dist={dist:.0f}m  match={n_match}  stab={stab:.0f}"
    draw.text((6, 4), header, fill=color, font=font)

    draw.text((6, 22), "Infrastructure", fill=(180, 180, 255), font=font_small)
    draw.text((new_w + 10, 22), "Vehicle", fill=(255, 200, 150), font=font_small)

    return panel


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", default="outputs/full6617_dair_v2xregpp_gt25")
    parser.add_argument("--data-root", default="data/DAIR-V2X/cooperative-vehicle-infrastructure")
    parser.add_argument("--samples-per-tier", type=int, default=6)
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    data_root = Path(args.data_root)
    out_dir = Path(args.out_dir) if args.out_dir else run_dir / "vis_tiers"
    out_dir.mkdir(parents=True, exist_ok=True)

    records = _load_records(run_dir)
    data_info = _load_data_info(data_root)
    n = args.samples_per_tier

    for tier_name in ["T1_EXCELLENT", "T2_GOOD", "T3_MODERATE", "T4_POOR", "T0_FAIL"]:
        picked = _pick_representative(records, tier_name, n)
        if not picked:
            continue

        panels = []
        for idx in picked:
            rec = records[idx]
            info = data_info[idx]
            infra_path = data_root / info["infrastructure_image_path"]
            veh_path = data_root / info["vehicle_image_path"]
            if not infra_path.exists() or not veh_path.exists():
                continue
            infra_img = Image.open(infra_path)
            veh_img = Image.open(veh_path)
            panel = _draw_panel(infra_img, veh_img, rec, idx, tier_name)
            panels.append(panel)

        if not panels:
            print(f"[{tier_name}] no panels generated (images missing?)")
            continue

        pw, ph = panels[0].size
        canvas = Image.new("RGB", (pw, ph * len(panels) + 2 * (len(panels) - 1)), color=(20, 20, 20))
        for j, p in enumerate(panels):
            canvas.paste(p, (0, j * (ph + 2)))

        out_path = out_dir / f"{tier_name.lower()}.png"
        canvas.save(out_path, quality=92)
        print(f"[{tier_name}] saved {len(panels)} panels -> {out_path}")

    print(f"\nAll visualizations saved to {out_dir}/")


if __name__ == "__main__":
    main()
