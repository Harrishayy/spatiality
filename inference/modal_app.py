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
    # Late-layered tail-pip deps. Adding here keeps the heavy CUDA-compile
    # layers above (fused-ssim / sam3 / 3DGRUT) cached across rebuilds.
    #
    # SAM 3.1's `pip install --no-build-isolation 'sam3 @ git+...'` doesn't
    # pull declared runtime deps, and its module-load chain ALSO crosses
    # into `sam3.train.*` (via sam3.model.sam1_task_predictor → tracker_base
    # → train.data.collator). Determined by walking the import tree of the
    # entry chain (sam3/__init__ → model_builder → model/* → train/data/*).
    # Without any one of these, `import sam3` 500s before our code runs.
    .pip_install(
        "pycocotools",       # sam3.train.data.coco_json_loaders
        "psutil",            # sam3.model.sam3_video_predictor
        "iopath>=0.1.10",    # sam3.model.* path I/O
        "submitit",          # sam3.train.* job launcher
        "timm>=1.0.17",      # sam3 model zoo wrappers
        "ftfy==6.1.1",       # sam3.model.tokenizer_ve text normalization
        "regex",             # sam3.model.tokenizer_ve
        "open_clip_torch",   # sam3.model.text_encoder_ve / tokenizer_ve
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
    """VGGT poses → 3DGRUT splat, with a volume commit between each stage so
    the web sees cameras.json the moment poses finishes and splat.ply the
    moment training finishes — without waiting for segmentation.

    Auto-spawns run_segmentation as fire-and-forget once splat is on disk
    (controlled by payload.segment, default true).

    POST body:
      {"scene_id": "...", "iterations": 7000, "keyframes": 5, "segment": true}
    """
    import os
    import subprocess

    scene_id = payload["scene_id"]
    iterations = int(payload.get("iterations", 7000))
    keyframes = int(payload.get("keyframes", 5))
    segment = bool(payload.get("segment", True))

    env = os.environ.copy()
    env.update(COMMON_ENV)

    # Volume.reload() makes sure we see whatever /agent just uploaded.
    artifacts_volume.reload()

    # Capture frames are uploaded by /agent before we run; mark complete so
    # the web's PipelineProgress shows it as done from t=0.
    _stage_complete(scene_id, "capture")
    _set_top_status(scene_id, "processing")
    artifacts_volume.commit()

    # ── Stage 1: poses (VGGT) ───────────────────────────────────────────
    poses_cmd = [
        "python", "-m", "inference",
        "--scene-id", scene_id,
        "--real",
        "--stage", "poses",
        "--iterations", str(iterations),
    ]
    try:
        subprocess.run(poses_cmd, check=True, env=env)
    except subprocess.CalledProcessError as exc:
        _stage_failed(scene_id, "poses", str(exc))
        _set_top_status(scene_id, "failed")
        artifacts_volume.commit()
        raise
    # cli.py already wrote stages.poses.status=complete + cameras.json.
    artifacts_volume.commit()

    # ── Stage 2: splat (3DGRUT) ─────────────────────────────────────────
    splat_cmd = [
        "python", "-m", "inference",
        "--scene-id", scene_id,
        "--real",
        "--stage", "splat",
        "--iterations", str(iterations),
    ]
    try:
        subprocess.run(splat_cmd, check=True, env=env)
    except subprocess.CalledProcessError as exc:
        _stage_failed(scene_id, "splat", str(exc))
        _set_top_status(scene_id, "failed")
        artifacts_volume.commit()
        raise
    # cli.py already wrote stages.splat.status=complete + flipped status=ready.
    artifacts_volume.commit()

    # ── Stage 3: segmentation, fire-and-forget ──────────────────────────
    spawned = False
    if segment:
        try:
            # _segment_async is a plain @app.function — fastapi_endpoint
            # wrappers can't be invoked via .spawn(); the runbook calls this
            # out at MODAL_RUNBOOK.md:160. The first run hit that and 500'd
            # at the end despite splat being on disk.
            _segment_async.spawn(scene_id, keyframes)
            spawned = True
        except Exception as exc:
            print(f"segmentation spawn failed: {exc!r}", flush=True)

    return {
        "status": "ok",
        "scene_id": scene_id,
        "iterations": iterations,
        "segmentation_spawned": spawned,
    }


@app.function(
    image=image,
    gpu="A100-80GB",
    timeout=600,
    volumes={"/artifacts": artifacts_volume, "/weights": weights_volume},
    secrets=[LOGFIRE_SECRET, GATEWAY_SECRET, HF_SECRET],
    cpu=4.0,
    memory=16384,
)
def _segment_async(scene_id: str, keyframes: int) -> dict:
    """Plain (non-fastapi) entrypoint for fire-and-forget segmentation.

    Bodies of `run_segmentation` (web) and this function are identical and
    delegate to the same in-container subprocess; the split only exists
    because @modal.fastapi_endpoint functions can't be invoked via .spawn().
    """
    return _segment_impl(scene_id, keyframes)


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
    """SAM 3.1 masks + lift_masks projection + Claude Haiku VLM labels.

    POST body:
      {"scene_id": "...", "keyframes": 5}
    Requires inference outputs (splat.ply, cameras.json, frames/) in the volume.
    """
    scene_id = payload["scene_id"]
    keyframes = int(payload.get("keyframes", 5))
    return _segment_impl(scene_id, keyframes)


def _segment_impl(scene_id: str, keyframes: int) -> dict:
    """Shared body for the web endpoint AND the spawn-able plain function.

    Commits the volume once before (so the web flips to segmentation=running
    immediately) and once after (so annotations.json appears atomically).
    """
    import os
    import subprocess

    env = os.environ.copy()
    env.update(COMMON_ENV)

    artifacts_volume.reload()

    _stage_running(scene_id, "segmentation")
    artifacts_volume.commit()

    cmd = [
        "python", "-m", "segmentation",
        "--scene-id", scene_id,
        "--real",
        "--keyframes", str(keyframes),
    ]
    try:
        subprocess.run(cmd, check=True, env=env)
    except subprocess.CalledProcessError as exc:
        _stage_failed(scene_id, "segmentation", str(exc))
        artifacts_volume.commit()
        raise

    artifacts_volume.commit()
    return {"status": "ok", "scene_id": scene_id, "keyframes": keyframes}


def _manifest_path(scene_id: str) -> str:
    return f"/artifacts/scenes/{scene_id}/manifest.json"


def _read_manifest(scene_id: str):
    """Late import so this module can be imported without /repo on sys.path."""
    import os
    from shared.schemas import Manifest

    path = _manifest_path(scene_id)
    if not os.path.exists(path):
        return None
    return Manifest.read(path)


def _stage_running(scene_id: str, stage: str) -> None:
    m = _read_manifest(scene_id)
    if m is None:
        return
    getattr(m.stages, stage).status = "running"
    m.status = "processing"
    m.write_atomic(_manifest_path(scene_id))


def _stage_complete(scene_id: str, stage: str) -> None:
    m = _read_manifest(scene_id)
    if m is None:
        return
    getattr(m.stages, stage).status = "complete"
    m.write_atomic(_manifest_path(scene_id))


def _stage_failed(scene_id: str, stage: str, error: str) -> None:
    m = _read_manifest(scene_id)
    if m is None:
        return
    getattr(m.stages, stage).status = "failed"
    m.errors.append(f"{stage}: {error}")
    m.write_atomic(_manifest_path(scene_id))


def _set_top_status(scene_id: str, status: str) -> None:
    m = _read_manifest(scene_id)
    if m is None:
        return
    m.status = status
    m.write_atomic(_manifest_path(scene_id))


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
