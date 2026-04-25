default:
    @just --list

# One-shot env setup (uv workspace: shared, capture, inference, segmentation)
setup:
    uv sync

# Generate the stub scene Devin builds against
stub-scene:
    uv run python scripts/make_stub_scene.py

# Module entrypoints
capture scene_id="test_scene_v0":
    uv run python -m capture --scene-id {{scene_id}} --no-extract

# Real ffmpeg-driven capture; pass video=path/to.mp4
capture-real scene_id="demo_scene_v1" video="samples/capture.mp4" fps="4.0":
    uv run python -m capture --scene-id {{scene_id}} --video {{video}} --fps {{fps}}

infer scene_id="test_scene_v0":
    uv run python -m inference --scene-id {{scene_id}}

# Real VGGT depth + per-pixel surfel synthesis (requires bundled deps + weights)
infer-real scene_id="demo_scene_v1":
    uv run python -m inference --scene-id {{scene_id}} --real

# FastVGGT path (token-merging fork; same weights, much higher frame budget)
infer-fastvggt scene_id="demo_scene_v1":
    uv run python -m inference --scene-id {{scene_id}} --real --backend fastvggt

segment scene_id="test_scene_v0":
    uv run python -m segmentation --scene-id {{scene_id}}

# Real SAM + VLM pipeline (requires SAM weights + PYDANTIC_GATEWAY_KEY)
segment-real scene_id="test_scene_v0" keyframes="12":
    uv run python -m segmentation --scene-id {{scene_id}} --real --keyframes {{keyframes}}

# Round-trip every JSON/YAML artifact through pydantic
check scene_id="test_scene_v0":
    uv run python shared/scripts/validate.py artifacts/scenes/{{scene_id}}

# End-to-end smoke (all stubs back-to-back)
smoke: stub-scene capture infer segment check

# ─── Modal workflow ──────────────────────────────────────────────────────
# Deploy the Modal app (inference + segmentation endpoints). First deploy ~25 min.
modal-deploy:
    uv run modal deploy inference/modal_app.py

# Trigger inference via the deployed web endpoint. Set MODAL_INFERENCE_URL first.
modal-inference scene_id="demo_scene_v1":
    @test -n "$MODAL_INFERENCE_URL" || (echo "MODAL_INFERENCE_URL not set"; exit 1)
    curl -fsS -X POST "$MODAL_INFERENCE_URL" \
      -H 'content-type: application/json' \
      -d '{"scene_id": "{{scene_id}}"}'

# Same endpoint, FastVGGT backend (700-frame budget @ 10 fps).
modal-inference-fast scene_id="demo_scene_v1":
    @test -n "$MODAL_INFERENCE_URL" || (echo "MODAL_INFERENCE_URL not set"; exit 1)
    curl -fsS -X POST "$MODAL_INFERENCE_URL" \
      -H 'content-type: application/json' \
      -d '{"scene_id": "{{scene_id}}", "backend": "fastvggt"}'

modal-segment scene_id="demo_scene_v1" keyframes="12":
    @test -n "$MODAL_SEGMENTATION_URL" || (echo "MODAL_SEGMENTATION_URL not set"; exit 1)
    curl -fsS -X POST "$MODAL_SEGMENTATION_URL" \
      -H 'content-type: application/json' \
      -d '{"scene_id": "{{scene_id}}", "keyframes": {{keyframes}}}'

# Upload local frames to the artifacts Modal Volume so the endpoints can read them.
modal-upload-scene scene_id="demo_scene_v1":
    uv run modal volume put glasses-twin-artifacts artifacts/scenes/{{scene_id}} scenes/{{scene_id}}

# Upload model weights to the weights Modal Volume (one-time per weight).
modal-upload-weight name path:
    uv run modal volume put glasses-twin-weights {{path}} {{name}}

# ─── Demo bake (T-30 minutes) ────────────────────────────────────────────
demo-bake video="samples/capture.mp4" scene_id="demo_scene_v1":
    bash scripts/demo_bake.sh {{video}} {{scene_id}}

# Kaggle workflow lived here — moved to old/kaggle/ on 2026-04-25 after switching to Modal.
