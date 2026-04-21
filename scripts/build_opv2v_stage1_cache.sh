#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

PYTHON_BIN=${PYTHON_BIN:-""}
if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$ROOT_DIR/.micromamba/envs/py39/bin/python" ]]; then
    PYTHON_BIN="$ROOT_DIR/.micromamba/envs/py39/bin/python"
  else
    PYTHON_BIN="$(command -v python3 || command -v python || true)"
  fi
fi
if [[ -z "$PYTHON_BIN" ]]; then
  echo "ERROR: python not found. Set PYTHON_BIN to your python executable." >&2
  exit 1
fi

OPV2V_CAMERA_MODEL_DIR=${OPV2V_CAMERA_MODEL_DIR:-"$ROOT_DIR/HEAL/opencood/logs/opv2v_camera_v2xvit_full_prope"}
OPV2V_CAMERA_CKPT=${OPV2V_CAMERA_CKPT:-"$OPV2V_CAMERA_MODEL_DIR/net_epoch_bestval_at21.pth"}
# NOTE: OPV2V camera stage1 must be multi-agent (len(cav_id_list)==len(pred_*_list)).
# The legacy pose_graph_pre_calc export only produced a single-agent list for camera
# (breaking pose solvers). Default to per-CAV exporter output dir to avoid that footgun.
OPV2V_CAMERA_OUT=${OPV2V_CAMERA_OUT:-"$ROOT_DIR/data/OPV2V/detected/opv2v_camera_v2xvit_stage1_percav"}
OPV2V_CAMERA_SHARDS=${OPV2V_CAMERA_SHARDS:-"1"}
OPV2V_CAMERA_SHARD_GPUS=${OPV2V_CAMERA_SHARD_GPUS:-"0,1,2,3,4,5,6,7,8,9"}
# Optional: dump dense occ maps for V2X-Reg++ occ-hint/occ-pose.
# Prefer *_PATH to avoid exploding stage1_boxes.json size.
OPV2V_CAMERA_DUMP_OCC=${OPV2V_CAMERA_DUMP_OCC:-"0"}          # inline occ_map_level0 (very large)
OPV2V_CAMERA_DUMP_OCC_PATH=${OPV2V_CAMERA_DUMP_OCC_PATH:-"0"} # save .npz and store occ_map_level0_path

OPV2V_LIDAR_MODEL_DIR=${OPV2V_LIDAR_MODEL_DIR:-"$ROOT_DIR/HEAL/opencood/logs/freealign_repro_opv2v_baseline"}
OPV2V_LIDAR_CKPT=${OPV2V_LIDAR_CKPT:-"$OPV2V_LIDAR_MODEL_DIR/net_epoch_bestval_at27.pth"}
OPV2V_LIDAR_OUT=${OPV2V_LIDAR_OUT:-"$ROOT_DIR/data/OPV2V/detected/opv2v_lidar_v2xvit_stage1"}

OPV2V_SPLITS=${OPV2V_SPLITS:-"test"}
FORCE=${FORCE:-0}

run_export() {
  local hypes="$1"
  local model_dir="$2"
  local ckpt="$3"
  local out_dir="$4"
  local split="$5"

  local out_file="$out_dir/$split/stage1_boxes.json"
  if [[ -f "$out_file" && "$FORCE" != "1" ]]; then
    echo "[SKIP] stage1 exists: $out_file"
    return 0
  fi

  mkdir -p "$out_dir"
  echo "[RUN] Export stage1 -> $out_file"
  PYTHONPATH="$ROOT_DIR/HEAL" "$PYTHON_BIN" "$ROOT_DIR/HEAL/opencood/tools/pose_graph_pre_calc.py" \
    --hypes_yaml "$hypes" \
    --model_dir "$model_dir" \
    --stage1_checkpoint "$ckpt" \
    --output_dir "$out_dir" \
    --splits "$split"
}

run_export_per_cav() {
  local hypes="$1"
  local ckpt="$2"
  local out_dir="$3"
  local split="$4"

  local out_file="$out_dir/$split/stage1_boxes.json"
  if [[ -f "$out_file" && "$FORCE" != "1" ]]; then
    echo "[SKIP] stage1 exists: $out_file"
    return 0
  fi

  mkdir -p "$out_dir"
  local shards="$OPV2V_CAMERA_SHARDS"
  if [[ -z "$shards" ]]; then
    shards="1"
  fi
  if [[ "$shards" == "1" ]]; then
    echo "[RUN] Export per-CAV stage1 -> $out_file"
    PYTHONPATH="$ROOT_DIR/HEAL" "$PYTHON_BIN" "$ROOT_DIR/HEAL/opencood/tools/export_stage1_boxes_per_cav.py" \
      --hypes_yaml "$hypes" \
      --stage1_checkpoint "$ckpt" \
      --output_dir "$out_dir" \
      --split "$split" \
      $( [[ "$OPV2V_CAMERA_DUMP_OCC" == "1" ]] && echo "--dump_occ_map" ) \
      $( [[ "$OPV2V_CAMERA_DUMP_OCC_PATH" == "1" ]] && echo "--dump_occ_map_path" )
    return 0
  fi

  echo "[RUN] Export per-CAV stage1 (sharded x${shards}) -> $out_file"
  local split_dir="$out_dir/$split"
  mkdir -p "$split_dir"
  local -a gpus
  IFS=',' read -r -a gpus <<<"$OPV2V_CAMERA_SHARD_GPUS"
  if [[ "${#gpus[@]}" -eq 0 ]]; then
    gpus=("0")
  fi

  local -a pids
  for ((i = 0; i < shards; i++)); do
    local gpu="${gpus[$((i % ${#gpus[@]}))]}"
    local shard_log="$split_dir/stage1_export_shard$(printf '%02d' "$i").log"
    echo "  - shard $i/$shards on GPU=$gpu log=$shard_log"
    (
      set -euo pipefail
      export CUDA_VISIBLE_DEVICES="$gpu"
      export PYTHONPATH="$ROOT_DIR/HEAL"
      "$PYTHON_BIN" "$ROOT_DIR/HEAL/opencood/tools/export_stage1_boxes_per_cav.py" \
        --hypes_yaml "$hypes" \
        --stage1_checkpoint "$ckpt" \
        --output_dir "$out_dir" \
        --split "$split" \
        --shard-index "$i" \
        --num-shards "$shards" \
        --log-interval 20 \
        $( [[ "$OPV2V_CAMERA_DUMP_OCC" == "1" ]] && echo "--dump_occ_map" ) \
        $( [[ "$OPV2V_CAMERA_DUMP_OCC_PATH" == "1" ]] && echo "--dump_occ_map_path" )
    ) >"$shard_log" 2>&1 &
    pids+=("$!")
  done

  local failed=0
  for pid in "${pids[@]}"; do
    if ! wait "$pid"; then
      failed=1
    fi
  done
  if [[ "$failed" == "1" ]]; then
    echo "[ERROR] One or more stage1 shards failed; check logs under $split_dir" >&2
    exit 1
  fi

  local expected_samples=0
  if [[ "$split" == "test" ]]; then
    expected_samples=2170
  fi

  "$PYTHON_BIN" "$ROOT_DIR/tools/merge_stage1_shards.py" \
    --shard-dir "$split_dir" \
    --num-shards "$shards" \
    --out "$out_file" \
    --expected-samples "$expected_samples" \
    --require-contiguous-keys
}

validate_stage1() {
  local stage1_path="$1"
  local split="$2"
  local expected="$3"

  # Validate structure (and sample count for test split when expected is provided).
  if [[ -n "$expected" ]]; then
    "$PYTHON_BIN" "$ROOT_DIR/tools/validate_stage1_cache.py" \
      --stage1 "$stage1_path" \
      --expected-samples "$expected" \
      --require-contiguous-keys
  else
    "$PYTHON_BIN" "$ROOT_DIR/tools/validate_stage1_cache.py" \
      --stage1 "$stage1_path"
  fi
}

for split in ${OPV2V_SPLITS//,/ }; do
  # Camera: must be per-CAV export for multi-agent pose solvers.
  run_export_per_cav "$OPV2V_CAMERA_MODEL_DIR/config.yaml" "$OPV2V_CAMERA_CKPT" "$OPV2V_CAMERA_OUT" "$split"
  # LiDAR: pose_graph_pre_calc exporter produces a valid multi-agent cache.
  run_export "$OPV2V_LIDAR_MODEL_DIR/config.yaml" "$OPV2V_LIDAR_MODEL_DIR" "$OPV2V_LIDAR_CKPT" "$OPV2V_LIDAR_OUT" "$split"

  # Hard gate: fail fast if stage1 cache is structurally invalid.
  expected=""
  if [[ "$split" == "test" ]]; then
    expected="2170"
  fi
  validate_stage1 "$OPV2V_CAMERA_OUT/$split/stage1_boxes.json" "$split" "$expected"
  validate_stage1 "$OPV2V_LIDAR_OUT/$split/stage1_boxes.json" "$split" "$expected"
done
