# Modal Runbook — Glasses → 3D Twin

Operational guide for the three Modal web endpoints that drive the inference + segmentation pipeline. Spec: [`plans/modules/09_deployment.md`](modules/09_deployment.md). Source: [`inference/modal_app.py`](../inference/modal_app.py).

## Topology

| Resource                                      | Type           | Purpose                                                                    |
| --------------------------------------------- | -------------- | -------------------------------------------------------------------------- |
| `glasses-twin-inference`                      | Modal App      | Hosts the three endpoints below.                                           |
| `glasses-twin-artifacts`                      | Modal Volume   | Per-scene I/O. `/agent` (Render) writes frames + reads results from here.  |
| `glasses-twin-weights`                        | Modal Volume   | VGGT + SAM 3.1 weights. Persistent so cold starts skip downloads.          |
| `https://harrishayy21--prepare-scene.modal.run`   | Web endpoint   | Lightweight: seed `manifest.json` for a new scene.                         |
| `https://harrishayy21--run-inference.modal.run`   | Web endpoint   | A100-80GB. VGGT depth + camera + per-pixel surfel synthesis. ~5–15 s.       |
| `https://harrishayy21--run-segmentation.modal.run` | Web endpoint   | A100-80GB. SAM 3.1 masks + Claude Haiku VLM labels. ~3–8 min.              |

The endpoint URLs are the deployed names — they print after `modal deploy`. Format: `https://<workspace>--<label>.modal.run`. Workspace here is `harrishayy21`.

## Required secrets (one-time)

```bash
uv run modal secret create logfire LOGFIRE_TOKEN=pylf_v...
uv run modal secret create pydantic-gateway \
    PYDANTIC_GATEWAY_KEY=pylf_v... \
    PYDANTIC_GATEWAY_URL=https://gateway-eu.pydantic.dev/proxy/anthropic/
uv run modal secret create huggingface HF_TOKEN=hf_...
```

## Required weights (one-time per weight)

```bash
uv run modal volume put glasses-twin-weights ./bundle/weights/vggt.pt vggt.pt
# SAM 3.1 weights are downloaded at runtime from HF (gated repo) into
# /weights/sam3-snapshot/ — no manual upload required.
```

## Standard workflow for a new scene

```bash
SCENE=demo_scene_v3

# 1. Frames go to local artifacts/scenes/<SCENE>/frames/  (run capture locally first)
just capture-real scene_id=$SCENE video=samples/capture.mp4 fps=2.0

# 2. Push the local scene dir into the Modal volume (frames + capture.yaml).
just modal-upload-scene scene_id=$SCENE

# 3. Seed the manifest on Modal (idempotent — returns "exists" if already there).
curl -sS -X POST https://harrishayy21--prepare-scene.modal.run \
  -H 'content-type: application/json' \
  -d "{\"scene_id\":\"$SCENE\"}"

# 4. Run inference. Wait for completion.
curl -sS -X POST https://harrishayy21--run-inference.modal.run \
  -H 'content-type: application/json' \
  -d "{\"scene_id\":\"$SCENE\"}" \
  --max-time 300

# 5. Run segmentation (optional but writes annotations.json).
curl -sS -X POST https://harrishayy21--run-segmentation.modal.run \
  -H 'content-type: application/json' \
  -d "{\"scene_id\":\"$SCENE\",\"keyframes\":5}" \
  --max-time 900

# 6. Pull artifacts back down for local viewing in /web.
mkdir -p web/public/artifacts/scenes/$SCENE
uv run modal volume get glasses-twin-artifacts \
  scenes/$SCENE/manifest.json     web/public/artifacts/scenes/$SCENE/
uv run modal volume get glasses-twin-artifacts \
  scenes/$SCENE/splat.ply         web/public/artifacts/scenes/$SCENE/
uv run modal volume get glasses-twin-artifacts \
  scenes/$SCENE/annotations.json  web/public/artifacts/scenes/$SCENE/  # optional
uv run modal volume get glasses-twin-artifacts \
  scenes/$SCENE/cameras.json      web/public/artifacts/scenes/$SCENE/  # optional
```

## Endpoint reference

### `POST /prepare-scene`

```jsonc
// Request
{ "scene_id": "demo_scene_v3" }

// Response (new)
{ "status": "created", "scene_id": "demo_scene_v3" }

// Response (already exists)
{ "status": "exists", "manifest": { ... } }
```

Lightweight (no GPU). Creates `/artifacts/scenes/<id>/frames/` and writes a `manifest.json` with all stages `pending` and top-level `status: "queued"`. Idempotent — call freely.

### `POST /run-inference`

```jsonc
// Request
{ "scene_id": "demo_scene_v3" }     // optional: "keyframes": 5, "segment": true

// Response
{ "status": "ok", "scene_id": "demo_scene_v3", "segmentation_spawned": true }
```

A100-80GB, 5-min timeout. Runs `python -m inference --scene-id … --real --stage poses` then `… --stage splat`. Stage 1 emits `cameras.json`, binary `points.ply`, and an internal `surfels.npz`; stage 2 voxel-downsamples the surfels and emits `splat.ply`. After success the top-level `status` rolls to `ready` (segmentation is optional). On `CalledProcessError` → marks `poses/splat` failed, top-level `failed`, appends the exception to `manifest.errors`.

### `POST /run-segmentation`

```jsonc
// Request
{ "scene_id": "demo_scene_v3", "keyframes": 5 }  // keyframes defaults to 5

// Response
{ "status": "ok", "scene_id": "demo_scene_v3", "keyframes": 5 }
```

A100-80GB, 10-min timeout. Requires inference outputs already on the volume. Runs `python -m segmentation --scene-id … --real --keyframes …`. Writes `annotations.json`. After success, `_finalize_manifest` flips `segmentation` complete; doesn't change `status` since `ready` already implies splat is viewable.

## Deploy

```bash
just modal-deploy           # i.e. uv run modal deploy inference/modal_app.py
```

First deploy: ~3-5 min (SAM 3.1 CUDA kernels + VGGT clone). Subsequent deploys: ~60-90 s when only `modal_app.py` or `/repo/*` source changes (image layers cached).

After deploy, Modal prints the three endpoint URLs — copy them into env vars used by `/agent`:

```bash
export MODAL_INFERENCE_URL=https://harrishayy21--run-inference.modal.run
export MODAL_SEGMENTATION_URL=https://harrishayy21--run-segmentation.modal.run
```

(`just modal-inference` and `just modal-segment` read these.)

## Volume operations

```bash
# List a scene
uv run modal volume ls glasses-twin-artifacts scenes/<id>/

# Pull a single file
uv run modal volume get glasses-twin-artifacts scenes/<id>/splat.ply ./local/path/

# Push a directory (whole scene from local dev)
uv run modal volume put glasses-twin-artifacts ./artifacts/scenes/<id> scenes/<id>

# Wipe a scene (only when you really mean it)
uv run modal volume rm -r glasses-twin-artifacts scenes/<id>
```

## Long-running endpoints + Modal's 150 s HTTP timeout

`run-inference` and `run-segmentation` regularly exceed Modal's web-endpoint HTTP timeout (~150 s). When that happens, Modal returns a `303 See Other` to a result-polling URL — `curl --post303 -L` re-issues a POST to that URL and Modal answers `400 modal-http: bad redirect method` because the polling URL is GET-only.

**The function is still running on Modal regardless** — check the volume + `modal app logs`, don't trust the HTTP error. Practical pattern:

```bash
# Fire (HTTP will likely timeout at ~150 s; ignore the 400/303).
/usr/bin/curl -sS -X POST https://harrishayy21--run-segmentation.modal.run \
  -H 'content-type: application/json' \
  -d '{"scene_id":"<id>","keyframes":5}' --max-time 200 || true

# Then poll the volume until the artifact appears.
until uv run modal volume ls glasses-twin-artifacts scenes/<id>/ \
  | grep -q annotations.json; do sleep 15; done
```

For a cleaner long-job pattern, see `Function.spawn(...)` in Modal's docs — eventually we should split the GPU work out of the `@modal.fastapi_endpoint` and have the endpoint just spawn + return a job id.

## SAM 3.1 dep set (for future image edits)

SAM 3.1's `pip install --no-build-isolation 'sam3 @ git+...'` does **not** pull declared runtime deps. Its module-load chain (sam3/__init__ → model_builder → model/* → train/data/*) needs the following on top of the base CUDA/torch image — these live in the late `.pip_install(...)` layer in `modal_app.py`:

| Package          | Imported by                          |
| ---------------- | ------------------------------------ |
| `pycocotools`    | `sam3.train.data.coco_json_loaders`  |
| `psutil`         | `sam3.model.sam3_video_predictor`    |
| `iopath>=0.1.10` | `sam3.model.*` path I/O              |
| `submitit`       | `sam3.train.*` job launcher          |
| `timm>=1.0.17`   | `sam3` model zoo wrappers            |
| `ftfy==6.1.1`    | `sam3.model.tokenizer_ve`            |
| `regex`          | `sam3.model.tokenizer_ve`            |
| `open_clip_torch`| `sam3.model.text_encoder_ve`         |

If you hit a fresh `ModuleNotFoundError` from sam3, walk the chain again: `git clone --depth 1 https://github.com/facebookresearch/sam3 /tmp/sam3 && grep -rhE '^(from|import) [a-zA-Z0-9_]+' /tmp/sam3/sam3/ | sed 's/^from //; s/^import //' | cut -d. -f1 | sort -u` — then diff against the image.

## SAM 3.1 inference contract

- **No AutomaticMaskGenerator.** SAM 3.1 is text-grounded. Our `segmentation/segmentation/sam.py` prompts with a generic phrase (`SAM3_TEXT_PROMPT`, default `"object"`) and reads boxes/masks from the processor state.
- **bfloat16 autocast required** on CUDA — model weights load in bf16. Inputs from PIL are fp32; without `torch.autocast("cuda", dtype=torch.bfloat16)` you get `mat1 and mat2 must have the same dtype`.
- **HF auto-fetch** — no manual snapshot pre-download. `build_sam3_image_model(load_from_HF=True)` handles the gated-repo download (HF_TOKEN secret required).

## Troubleshooting

**Manifest stuck on `queued` even after splat.ply lands.** Pre-2026-04-25 deploys lacked `_finalize_manifest`. Redeploy `inference/modal_app.py` and re-run the stage. Manual one-off fix: edit `web/public/artifacts/scenes/<id>/manifest.json` and set `status: "ready"`.

**`/run-segmentation` 500s.** Almost always missing inference outputs. Check `uv run modal volume ls glasses-twin-artifacts scenes/<id>/` includes `splat.ply` + `cameras.json`. If not, run inference first.

**Splat fails to load in the browser.** Most common cause: PLY format mismatch — the inference splat stage writes binary little-endian INRIA layout. `web/app/components/SplatViewer.tsx:75–77` rejects anything else. Check the browser console.

**Modal CLI says `command not found`.** Use `uv run modal …` — the package is in the project venv, not the global PATH.

**Webhook can't be invoked via `.remote()`.** All three endpoints are `@modal.fastapi_endpoint`-decorated. They are HTTP-only — POST to the printed URL. Use `Function.from_name(...).remote(...)` only on plain `@app.function`s.

## Cost notes (rough, A100-80GB)

| Operation             | Wall time | Approx cost |
| --------------------- | --------- | ----------- |
| Cold start (image pull + GPU acquire) | 30–90 s   | included in next call |
| `prepare-scene`       | 1–3 s     | ~$0.001     |
| `run-inference` (VGGT + surfel synth) | 5–15 s    | ~$0.013     |
| `run-segmentation` (5 keyframes) | 3–8 min   | $0.30–0.80  |

Always use `--max-time` on curl to avoid hung clients holding GPU slots open beyond the function timeout.
