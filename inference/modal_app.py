"""Modal app — inference + segmentation on A100s.

Spec: plans/modules/09_deployment.md.

Topology:
- Two persistent Modal Volumes: `glasses-twin-artifacts` (per-scene I/O,
  shared with /agent on Render) and `glasses-twin-weights` (model weights —
  VGGT, SAM 3.1, persistent so we don't redownload per cold start).
- Two web endpoints: `/run-inference` and `/run-segmentation`. Both take
  {scene_id, ...} and update manifest.json on the artifacts Volume.
- /agent (Render) is responsible for: capture (ffmpeg), writing the initial
  manifest, uploading frames into the Volume via `Volume.put`, then POSTing
  to these endpoints. /agent polls manifest.json afterwards.

Deploy:
  uv run modal deploy inference/modal_app.py
  # First deploy: ~20-30 min (3DGRUT tiny-cuda-nn compile). Subsequent: <2 min.

Required Modal Secrets (one-time setup):
  modal secret create logfire LOGFIRE_TOKEN=pylf_v...
  modal secret create pydantic-gateway PYDANTIC_GATEWAY_KEY=pylf_v... \\
      PYDANTIC_GATEWAY_URL=https://gateway-eu.pydantic.dev/proxy/anthropic/

Weight upload (one-time, per weight file):
  modal volume put glasses-twin-weights ./bundle/weights/vggt.pt vggt.pt
  modal volume put glasses-twin-weights /path/to/sam3.pt sam3.pt
"""

from __future__ import annotations

import modal

app = modal.App("glasses-twin-inference")

# ── Volumes ────────────────────────────────────────────────────────────────
artifacts_volume = modal.Volume.from_name("glasses-twin-artifacts", create_if_missing=True)
weights_volume = modal.Volume.from_name("glasses-twin-weights", create_if_missing=True)

# ── Image ──────────────────────────────────────────────────────────────────
# Heavy: clones VGGT + 3DGRUT, compiles tiny-cuda-nn (~20 min first deploy).
# Local repo packages are added last so source edits don't bust the CUDA cache.
image = (
    # CUDA 12.4 devel base — has nvcc + CUDA toolkit so fused-ssim and 3DGRUT
    # tiny-cuda-nn can compile their kernels at build time. debian_slim doesn't.
    modal.Image.from_registry("nvidia/cuda:12.4.1-devel-ubuntu22.04", add_python="3.11")
    .env({"CUDA_HOME": "/usr/local/cuda", "TORCH_CUDA_ARCH_LIST": "8.0;8.6;8.9;9.0"})
    .apt_install("git", "build-essential", "ffmpeg", "libgl1", "libglib2.0-0", "wget", "clang")
    .pip_install(
        # Build helpers — needed for --no-build-isolation installs of fused-ssim,
        # sam3, and 3DGRUT (their setup.py invokes bdist_wheel which needs `wheel`).
        "wheel",
        "setuptools",
        # GPU stack — pin to the 3DGRUT-known-good torch.
        "torch==2.4.0",
        "torchvision==0.19.0",
        "numpy<2",
        "opencv-python-headless<4.12",  # 3DGRUT pin (numpy<2)
        "pillow",
        "scipy",
        "scikit-image",
        # VGGT
        "einops",
        "huggingface-hub",
        "safetensors",
        "imageio",
        "imageio-ffmpeg",
        # 3DGRUT runtime deps — full set from bundle/src/3dgrut/requirements.txt
        # so the import path doesn't fail at runtime. Skip kaolin (NVIDIA find-links,
        # fragile) — 3DGRUT only needs it for some dataset loaders we don't use.
        "ninja",
        "plyfile",
        "trimesh",
        "hydra-core",
        "omegaconf",
        "torchmetrics",
        "tensorboard",
        "fire",
        "addict",
        "rich",
        "slangtorch==1.3.18",
        "piexif",
        "kornia",
        "msgpack",
        "dataclasses-json",
        "tqdm",
        "libigl",
        "pygltflib",
        "wandb",
        # Pipeline plumbing
        "pydantic>=2.7",
        "pyyaml>=6",
        "logfire>=0.50",
        # Modal web endpoints need FastAPI in the image as of recent Modal versions.
        "fastapi[standard]",
        # Segmentation
        "anthropic>=0.39",
        "scikit-learn>=1.5",
    )
    # fused-ssim and sam3 both have setup.py that imports torch — use --no-build-isolation
    # so they see the torch we installed in the previous layer (PEP 517's isolated venv
    # is otherwise a fresh env where `import torch` fails). pip_install() doesn't
    # expose this flag, so we use run_commands() with explicit pip install.
    .run_commands(
        "pip install --no-build-isolation 'fused-ssim @ git+https://github.com/rahul-goel/fused-ssim@1272e21a282342e89537159e4bad508b19b34157'",
    )
    # SAM 3.1 — sole segmentation backend (per plans/modules/03_segmentation.md).
    # Public Python package on GitHub; weights are gated and pulled from HF at
    # runtime by segmentation/sam.py (see SAM3_HF_REPO + HF_SECRET).
    # Requires CUDA + torch at build time.
    .run_commands(
        "pip install --no-build-isolation 'sam3 @ git+https://github.com/facebookresearch/sam3.git'",
    )
    .run_commands(
        "git clone --depth 1 https://github.com/facebookresearch/vggt.git /opt/vggt",
        "pip install --no-build-isolation --no-deps -e /opt/vggt",
        "git clone --depth 1 --recursive https://github.com/nv-tlabs/3dgrut.git /opt/3dgrut",
        # 3DGRUT compile — tiny-cuda-nn + cutlass. Slow (~15-20 min first time).
        "pip install --no-build-isolation --no-deps -e /opt/3dgrut",
    )
    # Repo packages last so editing them only rebuilds these final layers.
    .add_local_dir("./shared", remote_path="/repo/shared", copy=True)
    .add_local_dir("./capture", remote_path="/repo/capture", copy=True)
    .add_local_dir("./inference", remote_path="/repo/inference", copy=True)
    .add_local_dir("./segmentation", remote_path="/repo/segmentation", copy=True)
    .run_commands(
        "pip install -e /repo/shared",
        "pip install --no-deps -e /repo/capture",
        "pip install --no-deps -e /repo/inference",
        "pip install --no-deps -e /repo/segmentation",
    )
)

# ── Shared env baked into every function ───────────────────────────────────
COMMON_ENV = {
    "ARTIFACTS_PATH": "/artifacts",
    "VGGT_LOCAL_WEIGHTS": "/weights/vggt.pt",
    "THREEDGRUT_ROOT": "/opt/3dgrut",
    # SAM 3.1 — sole segmentation backend. Weights live in a gated HF repo;
    # segmentation/sam.py snapshot-downloads them to SAM3_SNAPSHOT_DIR on first
    # call (HF_TOKEN secret required, attached to the segmentation function).
    "SAM3_CONFIG": "sam3_hiera_l.yaml",
    "SAM3_HF_REPO": "facebook/sam3.1",
    "SAM3_SNAPSHOT_DIR": "/weights/sam3-snapshot",
    # Inference quality knobs — higher values mean denser splats / more frames.
    "VGGT_POINTS_MAX": "500000",
    "VGGT_POINTS_CONF_MIN": "0.4",
}

LOGFIRE_SECRET = modal.Secret.from_name("logfire", required_keys=["LOGFIRE_TOKEN"])
GATEWAY_SECRET = modal.Secret.from_name(
    "pydantic-gateway", required_keys=["PYDANTIC_GATEWAY_KEY", "PYDANTIC_GATEWAY_URL"]
)
HF_SECRET = modal.Secret.from_name("huggingface", required_keys=["HF_TOKEN"])


@app.function(
    image=image,
    gpu="A100-80GB",
    timeout=900,
    volumes={"/artifacts": artifacts_volume, "/weights": weights_volume},
    secrets=[LOGFIRE_SECRET],
    cpu=4.0,
    memory=16384,
)
@modal.fastapi_endpoint(method="POST", label="run-inference")
def run_inference(payload: dict) -> dict:
    """VGGT poses + 3DGRUT splat for a scene whose frames are already in the artifacts volume.

    POST body:
      {"scene_id": "...", "iterations": 7000}
    """
    import os
    import subprocess

    scene_id = payload["scene_id"]
    iterations = int(payload.get("iterations", 7000))

    env = os.environ.copy()
    env.update(COMMON_ENV)

    # Volume.reload() makes sure we see whatever /agent just uploaded.
    artifacts_volume.reload()

    cmd = [
        "python", "-m", "inference",
        "--scene-id", scene_id,
        "--real",
        "--iterations", str(iterations),
    ]
    try:
        subprocess.run(cmd, check=True, env=env)
    except subprocess.CalledProcessError as exc:
        _finalize_manifest(scene_id, failed=("poses", "splat"), error=str(exc))
        artifacts_volume.commit()
        raise

    # Frames present + inference succeeded → capture/poses/splat all complete.
    _finalize_manifest(scene_id, completed=("capture", "poses", "splat"))
    # Persist outputs back to the volume so /agent can download them.
    artifacts_volume.commit()
    return {"status": "ok", "scene_id": scene_id, "iterations": iterations}


@app.function(
    image=image,
    gpu="A100-80GB",
    timeout=600,
    volumes={"/artifacts": artifacts_volume, "/weights": weights_volume},
    secrets=[LOGFIRE_SECRET, GATEWAY_SECRET, HF_SECRET],
    cpu=4.0,
    memory=16384,
)
@modal.fastapi_endpoint(method="POST", label="run-segmentation")
def run_segmentation(payload: dict) -> dict:
    """SAM 3.1 masks + Claude Haiku VLM labels via Pydantic AI Gateway.

    POST body:
      {"scene_id": "...", "keyframes": 5}
    Requires inference outputs (splat.ply, cameras.json, frames/) in the volume.
    """
    import os
    import subprocess

    scene_id = payload["scene_id"]
    keyframes = int(payload.get("keyframes", 5))

    env = os.environ.copy()
    env.update(COMMON_ENV)

    artifacts_volume.reload()

    cmd = [
        "python", "-m", "segmentation",
        "--scene-id", scene_id,
        "--real",
        "--keyframes", str(keyframes),
    ]
    try:
        subprocess.run(cmd, check=True, env=env)
    except subprocess.CalledProcessError as exc:
        _finalize_manifest(scene_id, failed=("segmentation",), error=str(exc))
        artifacts_volume.commit()
        raise

    _finalize_manifest(scene_id, completed=("segmentation",))
    artifacts_volume.commit()
    return {"status": "ok", "scene_id": scene_id, "keyframes": keyframes}


def _finalize_manifest(
    scene_id: str,
    *,
    completed: tuple[str, ...] = (),
    failed: tuple[str, ...] = (),
    error: str | None = None,
) -> None:
    """Mark stages and roll up the top-level manifest status.

    Without this, manifest.status is left at "queued" forever even after the
    splat is on disk, and the web viewer polls indefinitely. The per-stage
    code in inference/segmentation modules updates its own stage entry, but
    nothing was rolling that up to the top-level status — that's this helper.

    Roll-up: top-level "ready" once both poses and splat are complete.
    Segmentation is optional for the demo. Any "failed" stage → "failed".
    """
    import os

    # Late import — runs inside the Modal container, where /repo/shared is on sys.path.
    from shared.schemas import Manifest

    manifest_path = f"/artifacts/scenes/{scene_id}/manifest.json"
    if not os.path.exists(manifest_path):
        return

    m = Manifest.read(manifest_path)
    for name in completed:
        getattr(m.stages, name).status = "complete"
    for name in failed:
        getattr(m.stages, name).status = "failed"
    if error:
        m.errors.append(error)

    if any(getattr(m.stages, n).status == "failed" for n in ("capture", "poses", "splat", "segmentation")):
        m.status = "failed"
    elif m.stages.poses.status == "complete" and m.stages.splat.status == "complete":
        m.status = "ready"
    elif any(getattr(m.stages, n).status == "running" for n in ("capture", "poses", "splat", "segmentation")):
        m.status = "processing"

    m.write_atomic(manifest_path)


@app.function(
    image=image,
    timeout=300,
    volumes={"/artifacts": artifacts_volume},
    cpu=2.0,
    memory=4096,
)
@modal.fastapi_endpoint(method="POST", label="prepare-scene")
def prepare_scene(payload: dict) -> dict:
    """Lightweight scene init — write the initial manifest if it doesn't exist.

    Useful when /agent uploads frames + capture.yaml directly to the volume
    and just needs the manifest seeded. POST body:
      {"scene_id": "..."}
    """
    import json
    import os
    from datetime import datetime, timezone

    os.environ.update(COMMON_ENV)
    from shared.schemas import Manifest, Stages, Stage, Artifacts, Stats

    scene_id = payload["scene_id"]
    artifacts_volume.reload()
    scene_dir = f"/artifacts/scenes/{scene_id}"
    os.makedirs(f"{scene_dir}/frames", exist_ok=True)
    manifest_path = f"{scene_dir}/manifest.json"

    if os.path.exists(manifest_path):
        return {"status": "exists", "manifest": json.loads(open(manifest_path).read())}

    base = f"/artifacts/scenes/{scene_id}"
    Manifest(
        scene_id=scene_id,
        created_at=datetime.now(timezone.utc),
        status="queued",
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
    ).write_atomic(manifest_path)

    artifacts_volume.commit()
    return {"status": "created", "scene_id": scene_id}


@app.local_entrypoint()
def smoke(scene_id: str = "modal_smoke") -> None:
    """Local smoke from your laptop: `modal run inference/modal_app.py::smoke --scene-id foo`."""
    print("prepare:", prepare_scene.remote({"scene_id": scene_id}))
    # NOTE: this assumes you've already uploaded frames into the volume:
    #   modal volume put glasses-twin-artifacts ./local_scene scenes/<scene_id>
    print("inference:", run_inference.remote({"scene_id": scene_id, "iterations": 3000}))
    print("segmentation:", run_segmentation.remote({"scene_id": scene_id, "keyframes": 5}))
