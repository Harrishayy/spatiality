#!/usr/bin/env bash
# Run the full pipeline on a Brev workspace. Assumes setup.sh has run.
# Usage: bash run.sh /path/to/capture.mp4 [scene_id] [iterations]
set -euo pipefail

VIDEO="${1:?path to capture.mp4 required}"
SCENE_ID="${2:-brev_$(date +%Y%m%d_%H%M%S)}"
ITERATIONS="${3:-7000}"

: "${ARTIFACTS_PATH:?run setup.sh first to set env}"
: "${VGGT_LOCAL_WEIGHTS:?run setup.sh first to set env}"
: "${THREEDGRUT_ROOT:?run setup.sh first to set env}"

SCENE_DIR="$ARTIFACTS_PATH/scenes/$SCENE_ID"
mkdir -p "$SCENE_DIR/frames"

echo "==> Seeding initial manifest"
python <<PY
from datetime import datetime, timezone
from shared.schemas import Manifest, Stages, Stage, Artifacts, Stats
base = "/artifacts/scenes/$SCENE_ID"
Manifest(
    scene_id="$SCENE_ID",
    created_at=datetime.now(timezone.utc),
    status="processing",
    stages=Stages(
        capture=Stage(status="pending"),
        poses=Stage(status="pending"),
        splat=Stage(status="pending"),
        segmentation=Stage(status="pending"),
    ),
    artifacts=Artifacts(
        splat_ply=f"{base}/splat.ply",
        annotations_json=f"{base}/annotations.json",
        thumbnail_jpg=f"{base}/thumbnail.jpg",
        cameras_json=f"{base}/cameras.json",
    ),
    stats=Stats(frame_count=0, object_count=0, splat_size_mb=0.0),
).write_atomic("$SCENE_DIR/manifest.json")
print("manifest seeded")
PY

echo "==> Capture (ffmpeg)"
python -m capture --scene-id "$SCENE_ID" --video "$VIDEO" --fps 2.0

echo "==> Inference (VGGT + 3DGRUT, $ITERATIONS iter)"
python -m inference --scene-id "$SCENE_ID" --real --iterations "$ITERATIONS"

if [ -n "${PYDANTIC_GATEWAY_KEY:-}" ]; then
  echo "==> Segmentation (SAM + VLM via Pydantic Gateway)"
  python -m segmentation --scene-id "$SCENE_ID" --real --keyframes 5
else
  echo "==> Skipping segmentation (PYDANTIC_GATEWAY_KEY unset)"
fi

echo "==> Done. Outputs:"
ls -la "$SCENE_DIR"
echo ""
echo "Pull to laptop:  scp -r brev:$SCENE_DIR ./output/"
