# Module 09 — Deployment

## Targets

| Component | Host | Why |
|-----------|------|-----|
| `/web` | Render Static Site | Free, fast, HTTPS, easy domain |
| `/agent` | Render Web Service | Free tier OK; persistent disk for `/artifacts` |
| `/artifacts/` | Render Persistent Disk attached to `/agent` | Single source of truth |
| `/inference` | Modal (primary) | A100s on demand, web endpoint trigger |
| `/inference` (backup) | Brev | Same image runnable if Modal flakes |
| `/segmentation` | Modal (same image) | A100, same deploy as inference |

Render does not have GPUs sufficient for splat training, so inference must live elsewhere.

## `render.yaml` (commit at repo root)

```yaml
services:
  - type: web
    name: glasses-twin-agent
    runtime: node
    plan: starter   # $7/mo so the service doesn't sleep mid-demo
    buildCommand: pnpm install && pnpm --filter agent build
    startCommand: pnpm --filter agent start
    rootDir: .
    envVars:
      - key: NODE_VERSION
        value: 20
      - key: PYDANTIC_GATEWAY_URL
        sync: false
      - key: PYDANTIC_GATEWAY_KEY
        sync: false
      - key: LOGFIRE_TOKEN
        sync: false
      - key: MODAL_INFERENCE_URL
        sync: false
      - key: ARTIFACTS_PATH
        value: /var/data/artifacts
    disk:
      name: artifacts
      mountPath: /var/data/artifacts
      sizeGB: 10

  - type: web
    name: glasses-twin-web
    runtime: static
    buildCommand: pnpm install && pnpm --filter web build
    staticPublishPath: ./web/dist
    pullRequestPreviewsEnabled: true
    envVars:
      - key: VITE_AGENT_URL
        sync: false
    routes:
      - type: rewrite
        source: /*
        destination: /index.html
```

## Modal app — `inference/modal_app.py`

```python
import modal

app = modal.App("glasses-twin-inference")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "build-essential", "ffmpeg")
    .pip_install(
        "torch==2.4.0",
        "numpy",
        "opencv-python-headless",
        "logfire",
        # ... + 3DGRUT and VGGT installed from git
    )
    .run_commands(
        "git clone https://github.com/facebookresearch/vggt /opt/vggt && pip install -e /opt/vggt",
        "git clone https://github.com/nv-tlabs/3dgrut /opt/3dgrut && pip install --no-build-isolation -e /opt/3dgrut",
    )
)

artifacts_volume = modal.Volume.from_name("glasses-twin-artifacts", create_if_missing=True)

@app.function(
    image=image,
    gpu="A100",
    timeout=600,
    volumes={"/artifacts": artifacts_volume},
    secrets=[modal.Secret.from_name("logfire")],
)
@modal.web_endpoint(method="POST")
def run_inference(payload: dict):
    scene_id = payload["scene_id"]
    # ... pipeline:
    # 1. read /artifacts/scenes/<scene_id>/frames/
    # 2. run VGGT for poses
    # 3. run 3DGRUT for splat
    # 4. write outputs back to /artifacts/scenes/<scene_id>/
    # 5. update manifest.json after each stage
    return {"status": "ok", "scene_id": scene_id}
```

Deploy: `modal deploy inference/modal_app.py`. Endpoint URL is logged on deploy — set as `MODAL_INFERENCE_URL` in Render env.

## Render Persistent Disk ↔ Modal Volume sync

This is the trickiest piece. The `/agent` service writes to `/var/data/artifacts` on Render's disk; Modal reads/writes the same logical structure on a Modal Volume.

**Two options:**

### Option A — Modal Volume with periodic commit/reload (recommended)
- Both Render and Modal mount the same logical paths but on separate storage.
- `/agent` writes input frames to its disk → uploads them to a Modal Volume via Modal SDK before triggering inference.
- Modal job writes outputs to its Volume → `/agent` polls and downloads results.
- Eventually consistent. Adds ~10s latency for upload/download but simple to reason about.

### Option B — S3 as shared backing store
- Both Render and Modal point at an S3 bucket via `boto3`.
- More moving parts but truly shared.
- Skip for hackathon — Option A is fine.

## Brev backup
- Provision an L40 or A100 workspace, install the same dependencies via the bundle from [`02_inference.md`](./02_inference.md).
- SSH from laptop, run `python inference/train.py` directly.
- Manual trigger only — no API integration. Used only if Modal fails on demo day.

## Pre-demo checklist (T-1 hour before pitch)

- [ ] Render `/agent` and `/web` both responding 200.
- [ ] Render disk usage < 80%.
- [ ] Modal function deployed; warm a request to ensure container is hot.
- [ ] Logfire dashboard open in a tab — visible spend confirmed under cap.
- [ ] Test scene `bedroom_v1` already uploaded and `manifest.status === "ready"`.
- [ ] Phone has the URL bookmarked, has tested loading once.
- [ ] Backup demo video recorded and queued in another browser tab.
- [ ] Brev workspace running with model weights, ready as fallback.

## Domain
Use the Render-issued `*.onrender.com` URL for both web and agent in v1. Custom domain only if you have spare time on day 2.

## Cost summary
- Render Starter agent: $7/mo (prorated <$1 for hackathon).
- Render Static Site: free.
- Render Disk 10GB: ~$0.25/day.
- Modal A100 hours: ~$3/hr; budget $30 = ~10 hours of compute. Plenty.
- Brev backup: pay-as-you-go, only used if Modal fails.
- **Expected total compute spend:** $5–15 across the hackathon.
