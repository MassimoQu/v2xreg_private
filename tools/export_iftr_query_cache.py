#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path
import glob
import re

import numpy as np
import torch
from torch.utils.data import DataLoader
from typing import Tuple


def _add_iftr_paths(iftr_root: Path) -> None:
    sys.path.insert(0, str(iftr_root))
    sys.path.insert(0, str(iftr_root / "opencood" / "mmdet3d"))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export IFTR query features as V2XReg++ detection cache.")
    parser.add_argument("--iftr-root", type=str, default="external/IFTR", help="Path to IFTR repo root.")
    parser.add_argument("--model-dir", type=str, required=True, help="IFTR log dir containing checkpoints.")
    parser.add_argument("--checkpoint", type=str, default=None, help="Explicit checkpoint path to load.")
    parser.add_argument("--hypes", type=str, default=None, help="IFTR hypes yaml. Defaults to model_dir/config.yaml.")
    parser.add_argument("--model-config", type=str, default=None, help="IFTR model config .py (override).")
    parser.add_argument("--data-dir", type=str, default=None, help="DAIR-V2X cooperative data dir.")
    parser.add_argument("--split-json", type=str, default=None, help="Split json path (val/test).")
    parser.add_argument("--output", type=str, required=True, help="Output cache JSON path.")
    parser.add_argument("--max-samples", type=int, default=None, help="Limit number of samples to export.")
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--num-workers", type=int, default=4)
    parser.add_argument("--device", type=str, default="cuda")
    parser.add_argument("--normalize-desc", action="store_true", help="L2 normalize query descriptors.")
    parser.add_argument("--score-threshold", type=float, default=None, help="Override bbox score threshold.")
    parser.add_argument("--max-num", type=int, default=None, help="Override max number of boxes per frame.")
    return parser.parse_args()


def _build_img_metas(image_inputs: dict, cav_content: dict) -> dict:
    img = image_inputs["imgs"]
    return {
        "rots": image_inputs["rots"],
        "trans": image_inputs["trans"],
        "post_rots": image_inputs["post_rots"],
        "post_trans": image_inputs["post_trans"],
        "intrins": image_inputs["intrins"],
        "focal": image_inputs["focal"].view(-1, 1),
        "pairwise_t_matrix": cav_content["pairwise_t_matrix"],
        "record_len": cav_content["record_len"],
        "img_shape": img.size()[3:],
    }


def _decode_with_queries(outs, bbox_coder, num_classes: int):
    cls_scores = outs["all_cls_scores"][-1][0]
    bbox_preds = outs["all_bbox_preds"][-1][0]
    query_feats = outs.get("query_feats")
    if query_feats is not None:
        query_feats = query_feats[0]

    scores = cls_scores.sigmoid()
    scores_flat = scores.reshape(-1)
    max_num = int(getattr(bbox_coder, "max_num", scores_flat.numel()))
    topk = min(max_num, scores_flat.numel())
    topk_scores, topk_indices = scores_flat.topk(topk)
    labels = topk_indices % num_classes
    bbox_index = topk_indices // num_classes
    bbox_preds = bbox_preds[bbox_index]
    boxes = denormalize_bbox(bbox_preds, bbox_coder.pc_range)
    if query_feats is not None:
        query_feats = query_feats[bbox_index]

    score_threshold = getattr(bbox_coder, "score_threshold", None)
    thresh_mask = None
    if score_threshold is not None:
        thresh_mask = topk_scores > score_threshold
        tmp_score = float(score_threshold)
        while thresh_mask.sum() == 0:
            tmp_score *= 0.9
            if tmp_score < 0.01:
                thresh_mask = topk_scores > -1
                break
            thresh_mask = topk_scores >= tmp_score

    post_center_range = getattr(bbox_coder, "post_center_range", None)
    if post_center_range is not None:
        range_tensor = torch.tensor(post_center_range, device=boxes.device)
        mask = (boxes[:, :3] >= range_tensor[:3]).all(1)
        mask &= (boxes[:, :3] <= range_tensor[3:]).all(1)
        if thresh_mask is not None:
            mask &= thresh_mask
        boxes = boxes[mask]
        topk_scores = topk_scores[mask]
        labels = labels[mask]
        if query_feats is not None:
            query_feats = query_feats[mask]
    else:
        if thresh_mask is not None:
            boxes = boxes[thresh_mask]
            topk_scores = topk_scores[thresh_mask]
            labels = labels[thresh_mask]
            if query_feats is not None:
                query_feats = query_feats[thresh_mask]

    return boxes, topk_scores, labels, query_feats


def _infer_single(model, cav_content, bbox_coder, normalize_desc: bool):
    image_inputs = cav_content["image_inputs"]
    img = image_inputs["imgs"]
    single_label_dict = cav_content["label_dict_single"]
    img_metas = _build_img_metas(image_inputs, cav_content)

    img_feats, feats_mask, obj_feats, obj_feats_cone_coding, _ = model.extract_feat(
        img=img, single_label_dict=single_label_dict, img_metas=img_metas
    )
    outs = model.pts_bbox_head(
        img_feats,
        img_metas,
        prev_bev=None,
        feats_mask=feats_mask,
        obj_feats=obj_feats,
        obj_feats_cone_coding=obj_feats_cone_coding,
    )

    num_classes = int(getattr(bbox_coder, "num_classes", outs["all_cls_scores"].shape[-1]))
    boxes, scores, _, query_feats = _decode_with_queries(outs, bbox_coder, num_classes)
    if boxes.numel() == 0:
        return []

    boxes_lwh = boxes[:, [0, 1, 2, 4, 3, 5, 6]]
    corners = box_utils.boxes_to_corners_3d(boxes_lwh, order="lwh").detach().cpu().numpy()
    scores_np = scores.detach().cpu().numpy().astype(np.float32, copy=False)
    if query_feats is not None:
        feats_np = query_feats.detach().cpu().numpy().astype(np.float32, copy=False)
        if normalize_desc:
            denom = np.linalg.norm(feats_np, axis=1, keepdims=True)
            feats_np = feats_np / (denom + 1e-12)
    else:
        feats_np = None

    entries = []
    for i in range(corners.shape[0]):
        entry = {
            "corners": corners[i].tolist(),
            "score": float(scores_np[i]),
        }
        if feats_np is not None:
            entry["descriptor"] = feats_np[i].tolist()
        entries.append(entry)
    return entries


def _resolve_ids(dataset, sample_idx: int) -> Tuple[str, str]:
    veh_id = dataset.split_info[sample_idx]
    frame_info = dataset.co_data[veh_id]
    infra_id = frame_info["infrastructure_image_path"].split("/")[-1].replace(".jpg", "")
    return str(infra_id), str(veh_id)


def main() -> None:
    args = _parse_args()
    iftr_root = Path(args.iftr_root).resolve()
    _add_iftr_paths(iftr_root)

    import opencood.hypes_yaml.yaml_utils as yaml_utils
    from opencood.tools import train_utils
    from opencood.data_utils.datasets import build_dataset
    from projects.mmdet3d_plugin.core.bbox.util import denormalize_bbox
    from opencood.utils import box_utils

    globals()["denormalize_bbox"] = denormalize_bbox
    globals()["box_utils"] = box_utils

    hypes_path = args.hypes
    if hypes_path is None:
        hypes_path = os.path.join(args.model_dir, "config.yaml")
    hypes = yaml_utils.load_yaml(hypes_path)

    if args.data_dir:
        hypes["data_dir"] = args.data_dir
    if args.split_json:
        hypes["validate_dir"] = args.split_json
        hypes["test_dir"] = args.split_json
    if args.model_config:
        hypes.setdefault("model", {})["config"] = args.model_config

    print("Building dataset...")
    dataset = build_dataset(hypes, visualize=True, train=False)
    if args.batch_size != 1:
        raise ValueError("Batch size > 1 is not supported for cache export.")
    loader = DataLoader(
        dataset,
        batch_size=args.batch_size,
        num_workers=args.num_workers,
        collate_fn=dataset.collate_batch_test,
        shuffle=False,
        pin_memory=False,
        drop_last=False,
    )

    print("Loading model...")
    model = train_utils.create_model(hypes)
    if args.checkpoint:
        state = torch.load(args.checkpoint, map_location="cpu")
        model.load_state_dict(state, strict=False)
    else:
        try:
            _, model = train_utils.load_saved_model(args.model_dir, model)
        except AssertionError:
            best_list = glob.glob(os.path.join(args.model_dir, "net_epoch_bestval_at*.pth"))
            if not best_list:
                raise
            def _epoch(p: str) -> int:
                match = re.search(r"bestval_at(\\d+)", p)
                return int(match.group(1)) if match else -1
            checkpoint = max(best_list, key=_epoch)
            print(f"Multiple bestval checkpoints found; using {checkpoint}")
            state = torch.load(checkpoint, map_location="cpu")
            model.load_state_dict(state, strict=False)
    device = torch.device(args.device if torch.cuda.is_available() else "cpu")
    model.to(device)
    model.eval()

    bbox_coder = model.pts_bbox_head.bbox_coder
    if args.score_threshold is not None:
        bbox_coder.score_threshold = float(args.score_threshold)
    if args.max_num is not None:
        bbox_coder.max_num = int(args.max_num)

    output = {}
    with torch.no_grad():
        for i, batch_data in enumerate(loader):
            if args.max_samples is not None and i >= args.max_samples:
                break
            if batch_data is None:
                continue
            batch_data = train_utils.to_device(batch_data, device)

            infra_id, veh_id = _resolve_ids(dataset, i)
            veh_content = batch_data.get("ego")
            infra_content = None
            for key, value in batch_data.items():
                if key == "ego":
                    continue
                infra_content = value
                break

            veh_preds = _infer_single(model, veh_content, bbox_coder, args.normalize_desc) if veh_content else []
            infra_preds = _infer_single(model, infra_content, bbox_coder, args.normalize_desc) if infra_content else []

            record = {
                "infra_frame_id": infra_id,
                "veh_frame_id": veh_id,
                "cav_id_list": ["infrastructure", "vehicle"],
                "pred_corner3d_np_list": [infra_preds, veh_preds],
            }
            output[str(i)] = record

            if (i + 1) % 50 == 0:
                print(f"[{i + 1}/{len(dataset)}] exported")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(output, f)
    print(f"Saved cache: {output_path}")


if __name__ == "__main__":
    main()
