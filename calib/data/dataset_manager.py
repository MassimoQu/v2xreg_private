from __future__ import annotations

from typing import Any, Generator, List, Optional, Tuple

import numpy as np

from v2x_calib.reader import CooperativeBatchingReader
from v2x_calib.utils import convert_6DOF_to_T, implement_T_3dbox_object_list
from legacy.v2x_calib.reader import noise_utils

from calib.config import DataConfig
from .interfaces import CalibrationSample
from .detection_adapter import DetectionAdapter


class DatasetManager:
    def __init__(self, config: DataConfig) -> None:
        self.config = config
        self.reader = CooperativeBatchingReader(
            path_data_info=config.data_info_path,
            path_data_folder=config.data_root,
        )
        self.detection_adapter = DetectionAdapter(config.detection_cache)
        self.feature_adapter = DetectionAdapter(config.feature_cache)
        self._detection_vehicle_flip_y: Optional[bool] = None
        self._shuffle_flags = {
            key.lower(): bool(value) for key, value in (config.shuffle_box_vertices or {}).items()
        }
        self._vertex_perm = np.array([7, 6, 5, 4, 3, 2, 1, 0], dtype=int)
        self._noise_cfg = dict(config.noise or {})

    def _should_shuffle(self, agent: str) -> bool:
        if not self._shuffle_flags:
            return False
        agent_key = agent.lower()
        if agent_key in self._shuffle_flags:
            return self._shuffle_flags[agent_key]
        return self._shuffle_flags.get('both', False)

    def _shuffle_boxes(self, boxes, agent: str):
        if not boxes or not self._should_shuffle(agent):
            return boxes
        shuffled = []
        for box in boxes:
            copied = box.copy()
            corners = np.asarray(copied.get_bbox3d_8_3())
            copied.bbox3d_8_3 = np.asarray(corners[self._vertex_perm])
            shuffled.append(copied)
        return shuffled

    def _apply_noise(self, boxes, agent: str):
        if not boxes or not self._noise_cfg:
            return boxes
        target = str(self._noise_cfg.get('target', 'vehicle')).lower()
        if target not in {'infra', 'vehicle', 'both'}:
            target = 'vehicle'
        if target != 'both' and agent.lower() != target:
            return boxes
        pos_std = float(self._noise_cfg.get('pos_std', 0.0))
        rot_std = float(self._noise_cfg.get('rot_std', 0.0))
        pos_mean = float(self._noise_cfg.get('pos_mean', 0.0))
        rot_mean = float(self._noise_cfg.get('rot_mean', 0.0))
        offset = self._noise_cfg.get('offset')
        has_gaussian = any(val != 0.0 for val in (pos_std, rot_std, pos_mean, rot_mean))
        if not has_gaussian and offset is None:
            return boxes
        if has_gaussian:
            noise_vec = noise_utils.generate_noise(pos_std, rot_std, pos_mean, rot_mean)
        else:
            noise_vec = np.zeros(6, dtype=float)
        if offset is not None:
            extra = np.zeros(6, dtype=float)
            values = list(offset) if isinstance(offset, (list, tuple, np.ndarray)) else [offset]
            for idx, val in enumerate(values[:6]):
                extra[idx] = float(val)
            noise_vec = noise_vec + extra
        if np.allclose(noise_vec, 0.0):
            return boxes
        delta_T = convert_6DOF_to_T(noise_vec)
        return implement_T_3dbox_object_list(delta_T, boxes)

    def _maybe_get_detections(
        self, idx: int, infra_id: str, veh_id: str
    ) -> Tuple[Optional[list], Optional[list], Optional[Any], Optional[List[float]]]:
        if not self.config.use_detection:
            return None, None, None, None
        record = self.detection_adapter.get_record(idx=idx, infra_id=infra_id, veh_id=veh_id)
        if record is None:
            # Strict behavior: when detection mode is enabled but the cache does not contain
            # this sample, treat it as a detection failure (empty boxes) instead of silently
            # falling back to ground-truth boxes.
            return [], [], None, None
        infra_boxes, veh_boxes = self.detection_adapter.convert_record(
            record, field='pred_corner3d_np_list', default_type='detected'
        )
        occ_map = record.get('occ_map_level0')
        bev_range = record.get('bev_range')
        return infra_boxes, veh_boxes, occ_map, bev_range

    def _maybe_configure_detection_vehicle_flip(self, gt_vehicle_boxes, detections_vehicle) -> None:
        if self._detection_vehicle_flip_y is not None:
            return
        if not gt_vehicle_boxes or not detections_vehicle:
            self._detection_vehicle_flip_y = False
            return

        def _centers_xy(boxes):
            centers = []
            for box in boxes:
                pts = np.asarray(box.get_bbox3d_8_3(), dtype=np.float32)
                if pts.size == 0:
                    continue
                centers.append(pts.mean(axis=0)[:2])
            if not centers:
                return np.zeros((0, 2), dtype=np.float32)
            return np.stack(centers, axis=0)

        def _median_nn(a: np.ndarray, b: np.ndarray) -> float:
            if a.size == 0 or b.size == 0:
                return float('inf')
            # a: (N,2), b: (M,2)
            diff = a[:, None, :] - b[None, :, :]
            dists = np.linalg.norm(diff, axis=2)
            return float(np.median(dists.min(axis=1)))

        gt_xy = _centers_xy(gt_vehicle_boxes)
        det_xy = _centers_xy(detections_vehicle)
        if gt_xy.size == 0 or det_xy.size == 0:
            self._detection_vehicle_flip_y = False
            return
        det_xy_flip = det_xy.copy()
        det_xy_flip[:, 1] *= -1
        med_raw = _median_nn(gt_xy, det_xy)
        med_flip = _median_nn(gt_xy, det_xy_flip)
        # Enable flip only when the improvement is obvious and stable.
        self._detection_vehicle_flip_y = bool(med_flip + 1e-6 < med_raw * 0.6 and med_flip + 1e-6 < med_raw - 1.0)

    def _apply_flip_y(self, boxes):
        flipped = []
        for box in boxes:
            copied = box.copy()
            pts = np.asarray(copied.get_bbox3d_8_3(), dtype=np.float32).copy()
            pts[:, 1] *= -1
            copied.bbox3d_8_3 = pts
            flipped.append(copied)
        return flipped

    def _maybe_get_features(
        self, idx: int, infra_id: str, veh_id: str
    ) -> Tuple[Optional[list], Optional[list]]:
        if not self.config.use_features:
            return None, None
        return self.feature_adapter.get(
            idx=idx,
            infra_id=infra_id,
            veh_id=veh_id,
            field=self.config.feature_field,
            default_type='feature',
        )

    def samples(self) -> Generator[CalibrationSample, None, None]:
        wrapper = self.reader.generate_infra_vehicle_bboxes_object_list()
        for idx, (inf_id, veh_id, infra_boxes, veh_boxes, T_true) in enumerate(wrapper):
            if self.config.max_samples is not None and idx >= self.config.max_samples:
                break
            detections_infra, detections_vehicle, occ_map_level0, bev_range = self._maybe_get_detections(
                idx, inf_id, veh_id
            )
            feature_infra, feature_vehicle = self._maybe_get_features(
                idx, inf_id, veh_id
            )
            if detections_vehicle:
                self._maybe_configure_detection_vehicle_flip(veh_boxes, detections_vehicle)
                if self._detection_vehicle_flip_y:
                    detections_vehicle = self._apply_flip_y(detections_vehicle)
            infra_boxes = self._shuffle_boxes(infra_boxes, 'infra')
            veh_boxes = self._shuffle_boxes(veh_boxes, 'vehicle')
            infra_boxes = self._apply_noise(infra_boxes, 'infra')
            veh_boxes = self._apply_noise(veh_boxes, 'vehicle')
            if detections_infra:
                detections_infra = self._shuffle_boxes(detections_infra, 'infra')
            if detections_vehicle:
                detections_vehicle = self._shuffle_boxes(detections_vehicle, 'vehicle')
            if feature_infra:
                feature_infra = self._shuffle_boxes(feature_infra, 'infra')
            if feature_vehicle:
                feature_vehicle = self._shuffle_boxes(feature_vehicle, 'vehicle')
            yield CalibrationSample(
                index=idx,
                infra_id=inf_id,
                veh_id=veh_id,
                infra_boxes=infra_boxes,
                veh_boxes=veh_boxes,
                T_true=T_true,
                detections_infra=detections_infra,
                detections_vehicle=detections_vehicle,
                features_infra=feature_infra,
                features_vehicle=feature_vehicle,
                occ_maps=occ_map_level0,
                bev_range=bev_range,
            )


__all__ = ['DatasetManager']
