import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))
from ..utils import (
    get_extrinsic_from_two_3dbox_object,
    get_extrinsic_from_two_mixed_3dbox_object_list,
    get_extrinsic_from_two_mixed_3dbox_object_list_svd_without_match,
    get_extrinsic_from_two_points_weighted,
    implement_T_points_n_3,
    convert_T_to_6DOF,
)  # , optimize_extrinsic_from_two_mixed_3dbox_object_list

class Matches2Extrinsics:
    
    def __init__(self, infra_boxes_object_list, vehicle_boxes_object_list, true_T_6DOF = None, matches_score_list = [], verbose = False, svd_strategy = 'svd_with_match'):
        
        self.matches_score_list = matches_score_list
        self.infra_boxes_object_list = infra_boxes_object_list
        self.vehicle_boxes_object_list = vehicle_boxes_object_list
        self.svd_strategy = svd_strategy
        self.threshold = max(matches_score_list[0][1] * 0.8, matches_score_list[0][1] - 1) if len(matches_score_list) >= 1 else 0

        self.true_T_6DOF_format = true_T_6DOF

        if verbose:
            
            if self.true_T_6DOF_format is not None:
                print('true_T_6DOF: ', true_T_6DOF)
            
            print('self.threshold: ', self.threshold)

            adequate_num = len([match[0] for match in self.matches_score_list if match[1] >= self.threshold])
            print('len(adequete_matches): ', adequate_num)

            cnt = 0

            for match, score in self.matches_score_list:
                print(cnt)
                infra_box_object = self.infra_boxes_object_list[match[0]]
                vehicle_box_object = self.vehicle_boxes_object_list[match[1]]
                extrinsic = get_extrinsic_from_two_3dbox_object(infra_box_object, vehicle_box_object)
                print('- score: ', score)
                print('- extrinsic: ', extrinsic)
                cnt += 1
                if score < self.threshold:
                    print('below threshold')


    def get_combined_extrinsic(self, matches2extrinsic_strategies = 'weightedSVD'):

        infra_boxes_object_list = [self.infra_boxes_object_list[match[0]] for match, _ in self.matches_score_list]
        vehicle_boxes_object_list = [self.vehicle_boxes_object_list[match[1]] for match, _ in self.matches_score_list]
        weights = [score for _, score in self.matches_score_list]

        def _is_detected(boxes):
            for box in boxes:
                try:
                    if str(box.get_bbox_type()).lower() == 'detected':
                        return True
                except Exception:
                    continue
            return False

        # Dihedral permutations for 4-vertex rectangles (bottom plane), extended to 8 corners.
        _dihedral_4 = [
            (0, 1, 2, 3),
            (1, 2, 3, 0),
            (2, 3, 0, 1),
            (3, 0, 1, 2),
            (0, 3, 2, 1),
            (3, 2, 1, 0),
            (2, 1, 0, 3),
            (1, 0, 3, 2),
        ]
        _dihedral_8 = [tuple(p) + tuple(i + 4 for i in p) for p in _dihedral_4]

        def _select_perm(points_src_trans, points_tgt):
            import numpy as np

            best_err = None
            best_perm = _dihedral_8[0]
            for perm in _dihedral_8:
                diff = points_src_trans[list(perm)] - points_tgt
                err = float(np.mean(np.sum(diff * diff, axis=1)))
                if best_err is None or err < best_err:
                    best_err = err
                    best_perm = perm
            return best_perm
        
        if self.svd_strategy == 'svd_with_match':
            if matches2extrinsic_strategies == 'evenSVD':
                resultT = get_extrinsic_from_two_mixed_3dbox_object_list(infra_boxes_object_list, vehicle_boxes_object_list)
            elif matches2extrinsic_strategies == 'weightedSVD':
                if _is_detected(infra_boxes_object_list) or _is_detected(vehicle_boxes_object_list):
                    import numpy as np

                    if len(infra_boxes_object_list) == 0:
                        resultT = np.eye(4, dtype=np.float64)
                    else:
                        centers_infra = np.stack(
                            [np.asarray(b.get_bbox3d_8_3(), dtype=np.float64).mean(axis=0) for b in infra_boxes_object_list],
                            axis=0,
                        )
                        centers_veh = np.stack(
                            [np.asarray(b.get_bbox3d_8_3(), dtype=np.float64).mean(axis=0) for b in vehicle_boxes_object_list],
                            axis=0,
                        )
                        w_centers = np.asarray(weights, dtype=np.float64)
                        T_est = get_extrinsic_from_two_points_weighted(centers_infra, centers_veh, w_centers)

                        infra_pts = [np.asarray(b.get_bbox3d_8_3(), dtype=np.float64) for b in infra_boxes_object_list]
                        veh_pts = [np.asarray(b.get_bbox3d_8_3(), dtype=np.float64) for b in vehicle_boxes_object_list]

                        # EM-style refinement: pick per-box vertex permutation under current T_est,
                        # then solve a weighted Kabsch on the permuted corners.
                        for _ in range(2):
                            permuted_infra = []
                            permuted_veh = []
                            perm_weights = []
                            for pts_infra, pts_veh, w in zip(infra_pts, veh_pts, weights):
                                pts_infra_trans = implement_T_points_n_3(T_est, pts_infra)
                                perm = _select_perm(pts_infra_trans, pts_veh)
                                permuted_infra.append(pts_infra[list(perm)])
                                permuted_veh.append(pts_veh)
                                perm_weights.extend([float(w)] * 8)
                            P1 = np.concatenate(permuted_infra, axis=0)
                            P2 = np.concatenate(permuted_veh, axis=0)
                            W = np.asarray(perm_weights, dtype=np.float64)
                            T_est = get_extrinsic_from_two_points_weighted(P1, P2, W)

                        resultT = T_est
                else:
                    resultT = get_extrinsic_from_two_mixed_3dbox_object_list(infra_boxes_object_list, vehicle_boxes_object_list, weights)
            # elif matches2extrinsic_strategies == 'ndt':
            #     resultT = optimize_extrinsic_from_two_mixed_3dbox_object_list(infra_boxes_object_list, vehicle_boxes_object_list)
            else:
                raise ValueError(f'matches2extrinsic_strategies={matches2extrinsic_strategies}, matches2extrinsic_strategies should be svd8point or ndt')
        elif self.svd_strategy == 'svd_without_match':
            if matches2extrinsic_strategies == 'evenSVD':
                resultT = get_extrinsic_from_two_mixed_3dbox_object_list_svd_without_match(infra_boxes_object_list, vehicle_boxes_object_list)
            elif matches2extrinsic_strategies == 'weightedSVD':
                resultT = get_extrinsic_from_two_mixed_3dbox_object_list_svd_without_match(infra_boxes_object_list, vehicle_boxes_object_list, weights)
            else:
                raise ValueError(f'matches2extrinsic_strategies={matches2extrinsic_strategies}, matches2extrinsic_strategies should be svd8point or ndt')
        else:
            raise ValueError(f'svd_strategy={self.svd_strategy}, svd_strategy should be svd_with_match or svd_without_match')

        return convert_T_to_6DOF(resultT)
    
    
