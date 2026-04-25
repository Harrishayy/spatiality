#!/usr/bin/env bash
# Pre-demo bake — run the full pipeline on the chosen demo scene end-to-end,
# then open the Logfire saved view so the on-stage "evidence tab" is ready.
#
# Spec: plans/ORCHESTRATOR.md "Pre-demo bake" + plans/modules/08_observability.md.
#
# Usage:
#   bash scripts/demo_bake.sh /path/to/capture.mp4 [scene_id] [iterations]
#
# Defaults:
#   scene_id    = demo_scene_v1
#   iterations  = 7000
#
# What it does:
#   1. Verifies env (LOGFIRE_TOKEN, PYDANTIC_GATEWAY_KEY, ffmpeg, GPU)
#   2. Wipes any prior scene_id directory (clean slate)
#   3. Seeds the manifest
#   4. capture -> inference --real -> segmentation --real
#   5. Validates annotations.json against the schema
#   6. Computes a thumbnail from the first frame
#   7. Prints the Logfire scene filter URL to bookmark as the evidence tab
#   8. Prints a checklist of what to verify before closing the laptop
set -euo pipefail

VIDEO="${1:?path to capture.mp4 required (arg 1)}"
SCENE_ID="${2:-demo_scene_v1}"
ITERATIONS="${3:-7000}"
LOGFIRE_PROJECT="${LOGFIRE_PROJECT:-glasses-twin-hackathon}"
ARTIFACTS_PATH="${ARTIFACTS_PATH:-$(pwd)/artifacts}"
SCENE_DIR="$ARTIFACTS_PATH/scenes/$SCENE_ID"

# ── Pre-flight ─────────────────────────────────────────────────────────────
echo "==> Pre-flight"
command -v ffmpeg >/dev/null || { echo "ffmpeg missing"; exit 1; }
[ -f "$VIDEO" ] || { echo "video not found: $VIDEO"; exit 1; }
: "${LOGFIRE_TOKEN:?LOGFIRE_TOKEN required for demo bake (this is THE evidence layer)}"
: "${PYDANTIC_GATEWAY_KEY:?PYDANTIC_GATEWAY_KEY required for VLM segmentation}"

# Confirm gateway URL ends with trailing slash (most common bug).
case "${PYDANTIC_GATEWAY_URL:-}" in
  */) ;;
  "") echo "warning: PYDANTIC_GATEWAY_URL unset; will default to EU";;
  *) echo "warning: PYDANTIC_GATEWAY_URL must end with /, got '$PYDANTIC_GATEWAY_URL'"; exit 1;;
esac

# GPU sanity (skip if no torch — local dev box may not have GPU)
python -c "import torch; assert torch.cuda.is_available(), 'no CUDA'" 2>/dev/null \
  && echo "    GPU: $(python -c 'import torch; print(torch.cuda.get_device_name(0))')" \
  || echo "    no local GPU — pipeline will run on CPU (very slow) or fail. Continue? (Ctrl-C to abort, Enter to proceed)" \
  && read -r _

# ── Clean slate ────────────────────────────────────────────────────────────
echo "==> Wiping prior $SCENE_DIR"
rm -rf "$SCENE_DIR"
mkdir -p "$SCENE_DIR/frames"

# ── Seed manifest ──────────────────────────────────────────────────────────
echo "==> Seeding initial manifest"
ARTIFACTS_PATH="$ARTIFACTS_PATH" python <<PY
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

# ── Pipeline ───────────────────────────────────────────────────────────────
echo "==> [1/3] capture (ffmpeg)"
ARTIFACTS_PATH="$ARTIFACTS_PATH" python -m capture \
  --scene-id "$SCENE_ID" --video "$VIDEO" --fps 2.0

echo "==> [2/3] inference (VGGT + 3DGRUT, $ITERATIONS iter)"
ARTIFACTS_PATH="$ARTIFACTS_PATH" python -m inference \
  --scene-id "$SCENE_ID" --real --iterations "$ITERATIONS"

echo "==> [3/3] segmentation (SAM + VLM via Pydantic Gateway)"
ARTIFACTS_PATH="$ARTIFACTS_PATH" python -m segmentation \
  --scene-id "$SCENE_ID" --real --keyframes 5

# ── Thumbnail ──────────────────────────────────────────────────────────────
echo "==> Thumbnail from first frame"
FIRST_FRAME=$(ls "$SCENE_DIR/frames"/*.png 2>/dev/null | head -1 || true)
if [ -n "$FIRST_FRAME" ]; then
  ffmpeg -y -i "$FIRST_FRAME" -vf "scale=512:-1" -q:v 2 "$SCENE_DIR/thumbnail.jpg" \
    >/dev/null 2>&1
fi

# ── Validate ───────────────────────────────────────────────────────────────
echo "==> Validating artifacts against schema"
ARTIFACTS_PATH="$ARTIFACTS_PATH" python shared/scripts/validate.py "$SCENE_DIR"

# ── Final manifest summary ─────────────────────────────────────────────────
echo ""
echo "==> Manifest"
python -c "
import json
m = json.load(open('$SCENE_DIR/manifest.json'))
print(f\"  scene_id: {m['scene_id']}\")
print(f\"  status:   {m['status']}\")
print(f\"  stats:    {m['stats']}\")
for stage, info in m['stages'].items():
    dur = info.get('duration_s')
    extra = {k: v for k, v in info.items() if k not in ('status', 'duration_s')}
    print(f\"    {stage:13s} {info['status']:10s} {dur if dur is not None else '-':>8} s  {extra}\")
"

# ── Logfire evidence tab ───────────────────────────────────────────────────
echo ""
echo "==> Logfire evidence tab"
echo "    Open and bookmark this filter:"
echo "      https://logfire.pydantic.dev/$LOGFIRE_PROJECT?filter=scene_id%3D%22$SCENE_ID%22"
echo "    All 6 demo span names should appear in the waterfall:"
echo "      capture.extract_frames"
echo "      inference.vggt"
echo "      inference.3dgrut"
echo "      segmentation.sam3"
echo "      segmentation.vlm_label"
echo "      agent.locate         (will appear after first /web Where-am-I tap)"

# ── Pre-demo checklist ─────────────────────────────────────────────────────
cat <<EOF

==> Pre-demo checklist (verify before closing this terminal):

  [ ] Logfire dashboard shows all 5 pipeline spans for scene_id=$SCENE_ID
  [ ] No error spans, no warnings
  [ ] Spend dashboard shows total cost < \$5 cap
  [ ] Open finished twin URL on demo phone, splat loads, "Where am I?" works
  [ ] Backup pre-recorded capture video queued in browser tab 3
  [ ] Render /agent + /web both 200, disk usage < 80%
  [ ] Modal warm (one ping in last 10 min)
  [ ] Brev workspace running and ready as fallback (per deploy/brev/README.md)

Next on stage:
  1. Tab 1: $SCENE_DIR-served-via-/web    (the finished twin)
  2. Tab 2: Logfire filter (above)         (the evidence)
  3. Tab 3: backup video                   (insurance)
EOF
