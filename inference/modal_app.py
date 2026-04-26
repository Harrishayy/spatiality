"""Modal app — inference + segmentation on A100s.

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
  # First deploy: ~3-5 min (SAM 3.1 CUDA kernels + VGGT clone). Subsequent: <2 min.

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
# Clones VGGT + installs SAM 3.1 (~3-5 min first deploy). gsplat / fused-ssim
# are gone — VGGT's depth+camera heads feed a NumPy-only surfel synthesiser,
# no CUDA training kernels needed for the splat stage. Local repo packages
# are added last so source edits don't bust the CUDA cache.
image = (
    # CUDA 12.4 devel base — has nvcc + CUDA toolkit so SAM 3.1 can compile
    # its kernels at build time. debian_slim doesn't.
    modal.Image.from_registry("nvidia/cuda:12.4.1-devel-ubuntu22.04", add_python="3.11")
    .env({"CUDA_HOME": "/usr/local/cuda", "TORCH_CUDA_ARCH_LIST": "8.0;8.6;8.9;9.0"})
    .apt_install("git", "build-essential", "ffmpeg", "libgl1", "libglib2.0-0", "wget", "clang")
    .pip_install(
        # Build helpers — needed for --no-build-isolation install of sam3
        # (its setup.py invokes bdist_wheel which needs `wheel`).
        "wheel",
        "setuptools",
        # GPU stack — torch 2.4.0 + cu124 matches the SAM 3.1 build target.
        "torch==2.4.0",
        "torchvision==0.19.0",
        "numpy<2",
        "opencv-python-headless<4.12",
        "pillow",
        "scipy",
        "scikit-image",
        # VGGT
        "einops",
        "huggingface-hub",
        "safetensors",
        "imageio",
        "imageio-ffmpeg",
        # PLY I/O — segmentation/splat_io.py reads gaussian centers from splat.ply.
        "plyfile",
        # Pipeline plumbing
        "pydantic>=2.7",
        "pyyaml>=6",
        "logfire>=0.50",
        # Modal web endpoints need FastAPI in the image as of recent Modal versions.
        "fastapi[standard]",
        # Segmentation
        "anthropic>=0.39",
        "scikit-learn>=1.5",
        # R2 / S3 — used by process_video to pull uploaded videos and by
        # _mirror_to_r2 to push finished artifacts to the public bucket.
        "boto3>=1.34",
    )
    # SAM 3.1 — sole segmentation backend.
    # Public Python package on GitHub; weights are gated and pulled from HF at
    # runtime by segmentation/sam.py (see SAM3_HF_REPO + HF_SECRET).
    # Requires CUDA + torch at build time. --no-build-isolation so it sees the
    # torch we just installed (PEP 517's isolated venv would re-fetch it).
    .run_commands(
        "pip install --no-build-isolation 'sam3 @ git+https://github.com/facebookresearch/sam3.git'",
    )
    .run_commands(
        "git clone --depth 1 https://github.com/facebookresearch/vggt.git /opt/vggt",
        "pip install --no-build-isolation --no-deps -e /opt/vggt",
    )
    # FastVGGT (mystorm16/FastVGGT) — token-merging fork of vanilla VGGT.
    # Cloned, NOT pip-installed: it shares the `vggt` package name so a pip
    # install would clobber the vanilla install above. fastvggt.py adds
    # /opt/fastvggt to sys.path at import time so `import vggt` resolves to
    # the fork only inside the FastVGGT-backed subprocess.
    .run_commands(
        "git clone --depth 1 https://github.com/mystorm16/FastVGGT.git /opt/fastvggt",
    )
    # Late-layered tail-pip deps. Adding here keeps the heavy CUDA-compile
    # layer above (sam3) cached across rebuilds.
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
    # SAM 3.1 — sole segmentation backend. Weights live in a gated HF repo;
    # segmentation/sam.py snapshot-downloads them to SAM3_SNAPSHOT_DIR on first
    # call (HF_TOKEN secret required, attached to the segmentation function).
    "SAM3_CONFIG": "sam3_hiera_l.yaml",
    "SAM3_HF_REPO": "facebook/sam3.1",
    "SAM3_SNAPSHOT_DIR": "/weights/sam3-snapshot",
    # VGGT frame selection — VGGT is O(N²); per upstream README, 100 frames
    # ≈ 21 GB / ~3 s on H100, comfortably under H100-80GB. 100 frames is the
    # sweet spot: well past the 16-32 view quality saturation knee with
    # plenty of parallax diversity, while keeping forward + surfel-synthesis
    # CPU work bounded. Bump to 200 only if a specific scene has visible
    # holes at 100.
    "VGGT_FRAMES_MAX": "100",
    "VGGT_FRAMES_MIN": "8",
    "VGGT_FPS_TARGET": "4.0",
    "VGGT_BLUR_DROP_PCT": "0.20",
    # Per-pixel surfel gates.
    "VGGT_DEPTH_CONF_MIN": "0.2",
    "VGGT_DEPTH_GRAD_MAX": "0.04",
    # Surfel pixel footprint — how many source pixels each surfel covers.
    # Larger = more overlap between neighbours = surfaces look filled, not speckly.
    "VGGT_SURFEL_PIXEL_FOOTPRINT": "4.0",
    # Edge-preserving depth smoothing (bilateral filter; D=0 to disable).
    "VGGT_DEPTH_BILATERAL_D": "5",
    "VGGT_DEPTH_BILATERAL_SIGMA_S": "50.0",
    "VGGT_DEPTH_BILATERAL_SIGMA_R": "0.05",
    # Sky / distant-background cap — drop pixels above this percentile of
    # per-frame valid depths × the multiplier.
    "VGGT_DEPTH_FAR_PCT": "95.0",
    "VGGT_DEPTH_FAR_MULT": "1.5",
    # Voxel downsample as a fraction of scene diagonal — controls splat count.
    # 0.002 targets ~1-1.5M Gaussians, the visual sweet spot under the viewer's
    # 2M cap. (Was 0.005 → ~200k, too sparse.)
    "VGGT_VOXEL_SIZE_FRAC": "0.002",
    # ── FastVGGT path (token-merging fork; opt-in via backend=fastvggt) ──
    # Pushes the frame budget up by ~15× — the speedup is what makes large
    # frame counts tractable. All other surfel/depth knobs above (VGGT_DEPTH_*,
    # VGGT_SURFEL_*, VGGT_VOXEL_*) are reused by both backends; only
    # frame-selection + token-merge knobs are FastVGGT-specific.
    "FASTVGGT_FRAMES_MAX": "700",
    "FASTVGGT_FRAMES_MIN": "16",
    "FASTVGGT_FPS_TARGET": "10.0",
    "FASTVGGT_BLUR_DROP_PCT": "0.20",
    "FASTVGGT_MERGING": "0",
    "FASTVGGT_MERGE_RATIO": "0.9",
    "FASTVGGT_REPO_PATH": "/opt/fastvggt",
    # Default backend for run_inference / _inference_async. Per-request override
    # is via payload.backend.
    "INFERENCE_BACKEND": "vggt",
}

LOGFIRE_SECRET = modal.Secret.from_name("logfire", required_keys=["LOGFIRE_TOKEN"])
GATEWAY_SECRET = modal.Secret.from_name(
    "pydantic-gateway", required_keys=["PYDANTIC_GATEWAY_KEY", "PYDANTIC_GATEWAY_URL"]
)
HF_SECRET = modal.Secret.from_name("huggingface", required_keys=["HF_TOKEN"])
# R2 credentials. Optional — when bucket envs are unset the mirror helper is a
# no-op and process_video only accepts source.kind="local". Create with:
#   modal secret create r2-credentials \
#     R2_ACCOUNT_ID=... R2_ACCESS_KEY_ID=... R2_SECRET_ACCESS_KEY=... \
#     R2_UPLOADS_BUCKET=glasses-twin-uploads R2_ARTIFACTS_BUCKET=glasses-twin-artifacts
R2_SECRET = modal.Secret.from_name("r2-credentials")


@app.function(
    image=image,
    gpu="H100",
    timeout=1800,
    volumes={"/artifacts": artifacts_volume, "/weights": weights_volume},
    secrets=[LOGFIRE_SECRET, R2_SECRET],
    cpu=4.0,
    memory=16384,
)
@modal.fastapi_endpoint(method="POST", label="run-inference")
def run_inference(payload: dict) -> dict:
    """VGGT poses + per-pixel surfel synthesis. Two stages with a volume
    commit between them so the web sees cameras.json the moment poses
    finishes and splat.ply the moment surfel synthesis finishes — without
    waiting for segmentation.

    Auto-spawns run_segmentation as fire-and-forget once splat is on disk
    (controlled by payload.segment, default true).

    POST body:
      {"scene_id": "...", "keyframes": 5, "segment": true,
       "backend": "vggt" | "fastvggt"}
    """
    scene_id = payload["scene_id"]
    keyframes = int(payload.get("keyframes", 5))
    segment = bool(payload.get("segment", True))
    backend = payload.get("backend")
    vlm_model = payload.get("vlm_model")
    return _run_inference_impl(scene_id, keyframes, segment, backend, vlm_model)


@app.function(
    image=image,
    gpu="H100",
    timeout=1800,
    volumes={"/artifacts": artifacts_volume, "/weights": weights_volume},
    secrets=[LOGFIRE_SECRET, R2_SECRET],
    cpu=4.0,
    memory=16384,
)
def _inference_async(
    scene_id: str,
    keyframes: int = 5,
    segment: bool = True,
    backend: str | None = None,
    vlm_model: str | None = None,
) -> dict:
    """Plain (non-fastapi) entrypoint so process_video can `.spawn()` inference.

    Same body as run_inference; split because @modal.fastapi_endpoint functions
    can't be invoked via .spawn() (mirrors the run_segmentation / _segment_async
    pair below).
    """
    return _run_inference_impl(scene_id, keyframes, segment, backend, vlm_model)


def _run_inference_impl(
    scene_id: str,
    keyframes: int,
    segment: bool,
    backend: str | None = None,
    vlm_model: str | None = None,
) -> dict:
    import os
    import subprocess

    import logfire
    from shared.observability import (  # type: ignore
        SPAN_MODAL_RUN_INFERENCE,
        configure_logfire,
    )

    configure_logfire("modal-inference")

    env = os.environ.copy()
    env.update(COMMON_ENV)
    # Per-request override beats env default; falls back to COMMON_ENV's
    # INFERENCE_BACKEND ("vggt") when neither is set.
    resolved_backend = backend or env.get("INFERENCE_BACKEND", "vggt")
    if resolved_backend not in ("vggt", "fastvggt"):
        raise ValueError(f"unknown backend: {resolved_backend!r}")
    env["INFERENCE_BACKEND"] = resolved_backend

    with logfire.span(
        SPAN_MODAL_RUN_INFERENCE,
        scene_id=scene_id,
        backend=resolved_backend,
        keyframes=keyframes,
        segment=segment,
    ) as span:
        # Volume.reload() makes sure we see whatever /agent just uploaded.
        artifacts_volume.reload()

        # Capture frames are uploaded before we run; mark complete so the web's
        # PipelineProgress shows it as done from t=0. (process_video sets this
        # too, but run_inference's existing callers may not have.)
        _stage_complete(scene_id, "capture")
        _set_top_status(scene_id, "processing")
        artifacts_volume.commit()
        _mirror_manifest(scene_id)

        # ── Stage 1: poses (VGGT depth + camera + per-pixel surfel synth) ───
        _run_pipeline_subprocess(
            scene_id=scene_id,
            stage="poses",
            cmd=[
                "python", "-m", "inference",
                "--scene-id", scene_id,
                "--real",
                "--stage", "poses",
                "--backend", resolved_backend,
            ],
            env=env,
        )
        artifacts_volume.commit()
        _mirror_manifest(scene_id)
        _mirror_artifacts(scene_id, ["cameras.json", "points.ply"])

        # ── Stage 2: splat (voxel-downsample surfels.npz → splat.ply) ───────
        # splat stage doesn't read the model so backend choice is informational
        # (stamps the manifest with the matching method string).
        _run_pipeline_subprocess(
            scene_id=scene_id,
            stage="splat",
            cmd=[
                "python", "-m", "inference",
                "--scene-id", scene_id,
                "--real",
                "--stage", "splat",
                "--backend", resolved_backend,
            ],
            env=env,
        )
        artifacts_volume.commit()
        _mirror_manifest(scene_id)
        _mirror_artifacts(scene_id, ["splat.ply"])

        # ── Stage 3: segmentation, fire-and-forget ──────────────────────────
        spawned = False
        if segment:
            try:
                _segment_async.spawn(scene_id, keyframes, vlm_model)
                spawned = True
            except Exception as exc:
                print(f"segmentation spawn failed: {exc!r}", flush=True)
                span.set_attribute("segmentation_spawn_error", str(exc)[:200])

        span.set_attribute("segmentation_spawned", spawned)
        if vlm_model:
            span.set_attribute("vlm_model", vlm_model)
        return {
            "status": "ok",
            "scene_id": scene_id,
            "segmentation_spawned": spawned,
        }


def _run_pipeline_subprocess(
    *, scene_id: str, stage: str, cmd: list[str], env: dict
) -> None:
    """Run a pipeline subprocess inside a `modal.subprocess` span.

    Captures stderr on failure so the failing trace carries the exception
    text instead of just the exit code. The inference / segmentation
    Python CLIs emit their own pipeline spans (inference.vggt, segmentation.sam3,
    ...) which appear nested under the run.* parent in the trace UI.
    """
    import subprocess

    import logfire

    # Fixed span name with `stage` as an attribute — Logfire treats `{x}` in
    # msg_templates as placeholder syntax, which made earlier dynamic names
    # show up as the literal `modal.subprocess.{stage}` in traces. The UI
    # groups subprocess spans by attributes.stage instead of the name suffix.
    with logfire.span(
        "modal.subprocess",
        scene_id=scene_id,
        stage=stage,
        argv=" ".join(cmd),
    ) as span:
        try:
            proc = subprocess.run(
                cmd, check=True, env=env, capture_output=True, text=True
            )
        except subprocess.CalledProcessError as exc:
            span.set_attribute("returncode", exc.returncode)
            span.set_attribute("stderr_tail", (exc.stderr or "")[-2000:])
            span.set_attribute("stdout_tail", (exc.stdout or "")[-1000:])
            _stage_failed(scene_id, stage, f"exit {exc.returncode}: {(exc.stderr or '')[-300:]}")
            _set_top_status(scene_id, "failed")
            artifacts_volume.commit()
            _mirror_manifest(scene_id)
            raise
        span.set_attribute("returncode", proc.returncode)
        # Stdout tail is useful evidence ("vggt: 240 frames -> ..."); cap it.
        if proc.stdout:
            span.set_attribute("stdout_tail", proc.stdout[-1000:])


@app.function(
    image=image,
    gpu="A100-80GB",
    timeout=600,
    volumes={"/artifacts": artifacts_volume, "/weights": weights_volume},
    secrets=[LOGFIRE_SECRET, GATEWAY_SECRET, HF_SECRET, R2_SECRET],
    cpu=4.0,
    memory=16384,
)
def _segment_async(
    scene_id: str, keyframes: int, vlm_model: str | None = None
) -> dict:
    """Plain (non-fastapi) entrypoint for fire-and-forget segmentation.

    Bodies of `run_segmentation` (web) and this function are identical and
    delegate to the same in-container subprocess; the split only exists
    because @modal.fastapi_endpoint functions can't be invoked via .spawn().
    """
    return _segment_impl(scene_id, keyframes, vlm_model)


@app.function(
    image=image,
    gpu="A100-80GB",
    timeout=600,
    volumes={"/artifacts": artifacts_volume, "/weights": weights_volume},
    secrets=[LOGFIRE_SECRET, GATEWAY_SECRET, HF_SECRET, R2_SECRET],
    cpu=4.0,
    memory=16384,
)
@modal.fastapi_endpoint(method="POST", label="run-segmentation")
def run_segmentation(payload: dict) -> dict:
    """SAM 3.1 masks + lift_masks projection + Claude Haiku VLM labels.

    POST body:
      {"scene_id": "...", "keyframes": 5, "vlm_model": "claude-haiku-4-5"?}
    Requires inference outputs (splat.ply, cameras.json, frames/) in the volume.
    """
    scene_id = payload["scene_id"]
    keyframes = int(payload.get("keyframes", 5))
    vlm_model = payload.get("vlm_model")
    return _segment_impl(scene_id, keyframes, vlm_model)


def _segment_impl(
    scene_id: str, keyframes: int, vlm_model: str | None = None
) -> dict:
    """Shared body for the web endpoint AND the spawn-able plain function.

    Commits the volume once before (so the web flips to segmentation=running
    immediately) and once after (so annotations.json appears atomically).
    `vlm_model` overrides the default (Haiku 4.5) by setting VLM_MODEL on the
    subprocess env — segmentation/vlm.py reads it via os.environ.
    """
    import os

    import logfire
    from shared.observability import (  # type: ignore
        SPAN_MODAL_RUN_SEGMENTATION,
        configure_logfire,
    )

    configure_logfire("modal-segmentation")

    env = os.environ.copy()
    env.update(COMMON_ENV)
    if vlm_model:
        # Whitelist guards against payload injection landing in env.
        if vlm_model not in (
            "claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-7"
        ):
            raise ValueError(f"unknown vlm_model: {vlm_model!r}")
        env["VLM_MODEL"] = vlm_model

    with logfire.span(
        SPAN_MODAL_RUN_SEGMENTATION,
        scene_id=scene_id,
        keyframes=keyframes,
        vlm_model=vlm_model or env.get("VLM_MODEL", "claude-haiku-4-5"),
    ):
        artifacts_volume.reload()

        _stage_running(scene_id, "segmentation")
        artifacts_volume.commit()

        _run_pipeline_subprocess(
            scene_id=scene_id,
            stage="segmentation",
            cmd=[
                "python", "-m", "segmentation",
                "--scene-id", scene_id,
                "--real",
                "--keyframes", str(keyframes),
            ],
            env=env,
        )

        artifacts_volume.commit()
        _mirror_manifest(scene_id)
        _mirror_artifacts(scene_id, ["annotations.json", "thumbnail.jpg"])
        _mirror_segmentation_evidence(scene_id)
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
    import logfire
    from shared.observability import (  # type: ignore
        SPAN_MODAL_PREPARE_SCENE,
        configure_logfire,
    )
    from shared.schemas import Manifest, Stages, Stage, Artifacts, Stats

    configure_logfire("modal-prepare")

    scene_id = payload["scene_id"]
    with logfire.span(SPAN_MODAL_PREPARE_SCENE, scene_id=scene_id) as span:
        artifacts_volume.reload()
        scene_dir = f"/artifacts/scenes/{scene_id}"
        os.makedirs(f"{scene_dir}/frames", exist_ok=True)
        manifest_path = f"{scene_dir}/manifest.json"

        if os.path.exists(manifest_path):
            span.set_attribute("manifest_state", "exists")
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
        span.set_attribute("manifest_state", "created")
        return {"status": "created", "scene_id": scene_id}


# ── R2 mirror helpers ──────────────────────────────────────────────────────


def _r2_client():
    """boto3 S3 client pointed at R2. Returns None when creds aren't set."""
    import os

    account = os.environ.get("R2_ACCOUNT_ID")
    key = os.environ.get("R2_ACCESS_KEY_ID")
    secret = os.environ.get("R2_SECRET_ACCESS_KEY")
    if not (account and key and secret):
        return None
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
        aws_access_key_id=key,
        aws_secret_access_key=secret,
        region_name="auto",
    )


_ARTIFACT_CONTENT_TYPE = {
    "manifest.json": "application/json",
    "annotations.json": "application/json",
    "cameras.json": "application/json",
    "splat.ply": "application/octet-stream",
    "points.ply": "application/octet-stream",
    "thumbnail.jpg": "image/jpeg",
}


def _mirror_to_r2(scene_id: str, files: list[str]) -> None:
    """Push the given filenames from the Volume to R2_ARTIFACTS_BUCKET.

    No-op when R2 creds or bucket name are missing — that's how local mode
    skips R2 entirely.
    """
    import os
    from pathlib import Path

    bucket = os.environ.get("R2_ARTIFACTS_BUCKET")
    s3 = _r2_client()
    if not (bucket and s3):
        return
    for name in files:
        src = Path(f"/artifacts/scenes/{scene_id}/{name}")
        if not src.exists():
            continue
        cache = "no-cache" if name == "manifest.json" else "public, max-age=31536000, immutable"
        try:
            s3.put_object(
                Bucket=bucket,
                Key=f"scenes/{scene_id}/{name}",
                Body=src.read_bytes(),
                ContentType=_ARTIFACT_CONTENT_TYPE.get(name, "application/octet-stream"),
                CacheControl=cache,
            )
        except Exception as exc:
            print(f"r2 mirror {name} failed: {exc!r}", flush=True)


def _mirror_manifest(scene_id: str) -> None:
    _mirror_to_r2(scene_id, ["manifest.json"])


def _mirror_artifacts(scene_id: str, names: list[str]) -> None:
    _mirror_to_r2(scene_id, names)


def _mirror_segmentation_evidence(scene_id: str) -> None:
    """Mirror the per-object SAM masks AND their referenced keyframes to R2.

    Bounded by the same 6-frames-per-object cap that lift_masks emits, so the
    upload volume is ~ (n_objects × 6) frames + masks rather than the full
    capture (which can be ~1k 2 MB PNGs). Without this, the deployed web —
    which reads frames + masks from `NEXT_PUBLIC_R2_ARTIFACTS_PUBLIC_BASE` —
    sees a 404 for every overlay tile in the evidence panel.

    Idempotent: every PUT is keyed by deterministic path, so re-runs of
    segmentation on the same scene re-overwrite in place.
    """
    import json
    import os
    from pathlib import Path

    bucket = os.environ.get("R2_ARTIFACTS_BUCKET")
    s3 = _r2_client()
    if not (bucket and s3):
        return

    scene_root = Path(f"/artifacts/scenes/{scene_id}")
    masks_root = scene_root / "masks"
    frames_root = scene_root / "frames"
    annotations_path = scene_root / "annotations.json"

    # Frame stems we need: union of every annotation's frame_ids that has a
    # corresponding mask file on disk. Falls back to walking masks/ if
    # annotations.json is missing (shouldn't happen at this call site, but
    # cheap defense).
    frame_names: set[str] = set()
    if annotations_path.exists():
        try:
            anns = json.loads(annotations_path.read_text())
            for a in anns:
                for fname in a.get("frame_ids", []) or []:
                    frame_names.add(fname)
        except (OSError, json.JSONDecodeError):
            pass

    # Walk masks/ and upload everything we wrote, AND collect frame stems
    # from filenames so we still mirror keyframes when annotations.json
    # didn't list them (e.g. legacy scenes).
    if masks_root.is_dir():
        for ann_dir in masks_root.iterdir():
            if not ann_dir.is_dir():
                continue
            for mask_path in ann_dir.glob("*.png"):
                key = f"scenes/{scene_id}/masks/{ann_dir.name}/{mask_path.name}"
                try:
                    s3.put_object(
                        Bucket=bucket,
                        Key=key,
                        Body=mask_path.read_bytes(),
                        ContentType="image/png",
                        CacheControl="public, max-age=31536000, immutable",
                    )
                except Exception as exc:
                    print(f"r2 mirror {key} failed: {exc!r}", flush=True)
                    continue
                # If annotations.json didn't list this frame, find the
                # source frame by stem (extension may be .png or .jpg).
                if frames_root.is_dir() and not any(
                    f.startswith(mask_path.stem + ".") for f in frame_names
                ):
                    for cand in frames_root.glob(mask_path.stem + ".*"):
                        frame_names.add(cand.name)
                        break

    # Mirror only the keyframes we actually need for the evidence gallery.
    if frames_root.is_dir():
        for fname in frame_names:
            src = frames_root / fname
            if not src.exists():
                continue
            ext = src.suffix.lower()
            ctype = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
            try:
                s3.put_object(
                    Bucket=bucket,
                    Key=f"scenes/{scene_id}/frames/{fname}",
                    Body=src.read_bytes(),
                    ContentType=ctype,
                    CacheControl="public, max-age=31536000, immutable",
                )
            except Exception as exc:
                print(f"r2 mirror frames/{fname} failed: {exc!r}", flush=True)


# ── Patch stage helpers to mirror manifest on every transition ─────────────
# (kept as wrappers so the existing direct callers above also mirror.)
_orig_stage_running = _stage_running
_orig_stage_complete = _stage_complete
_orig_stage_failed = _stage_failed
_orig_set_top_status = _set_top_status


def _stage_running(scene_id: str, stage: str) -> None:  # type: ignore[no-redef]
    _orig_stage_running(scene_id, stage)
    _mirror_manifest(scene_id)


def _stage_complete(scene_id: str, stage: str) -> None:  # type: ignore[no-redef]
    _orig_stage_complete(scene_id, stage)
    _mirror_manifest(scene_id)


def _stage_failed(scene_id: str, stage: str, error: str) -> None:  # type: ignore[no-redef]
    _orig_stage_failed(scene_id, stage, error)
    _mirror_manifest(scene_id)


def _set_top_status(scene_id: str, status: str) -> None:  # type: ignore[no-redef]
    _orig_set_top_status(scene_id, status)
    _mirror_manifest(scene_id)


# ── process_video: video → frames → manifest → spawn inference ─────────────


@app.function(
    image=image,
    timeout=900,
    volumes={"/artifacts": artifacts_volume},
    secrets=[LOGFIRE_SECRET, R2_SECRET],
    cpu=4.0,
    memory=8192,
)
@modal.fastapi_endpoint(method="POST", label="process-video")
def process_video(payload: dict) -> dict:
    """Pull a video from R2 (or read it from the Volume in local mode),
    extract frames with ffmpeg, write capture.yaml + initial manifest, then
    fire-and-forget spawn inference.

    POST body:
      {
        "scene_id": "...",
        "source": {"kind": "r2", "r2_key": "uploads/<id>/<file.mp4>"}
                | {"kind": "local", "modal_path": "/scenes/<id>/_upload.mp4"},
        "settings": {
          "fps": 2.0, "max_frames": 400, "target_long_side": 1920,
          "segment": true, "keyframes": 5,
          "backend": "vggt" | "fastvggt"
        }
      }
    """
    import json
    import os
    import subprocess
    from datetime import datetime, timezone
    from pathlib import Path

    os.environ.update(COMMON_ENV)
    import logfire
    from shared.observability import (  # type: ignore
        SPAN_MODAL_PROCESS_VIDEO,
        configure_logfire,
    )
    from shared.schemas import (  # type: ignore
        Artifacts,
        CaptureYaml,
        Manifest,
        Stage,
        Stages,
        Stats,
    )

    configure_logfire("modal-process-video")

    scene_id = payload["scene_id"]
    source = payload["source"]
    settings = payload.get("settings") or {}

    with logfire.span(
        SPAN_MODAL_PROCESS_VIDEO,
        scene_id=scene_id,
        source_kind=source.get("kind"),
    ) as process_video_span:
        return _process_video_body(
            scene_id=scene_id,
            source=source,
            settings=settings,
            span=process_video_span,
        )


def _process_video_body(
    *, scene_id: str, source: dict, settings: dict, span
) -> dict:
    import json
    import os
    import subprocess
    from datetime import datetime, timezone
    from pathlib import Path

    import logfire
    from shared.schemas import (  # type: ignore
        Artifacts,
        CaptureYaml,
        Manifest,
        Stage,
        Stages,
        Stats,
    )

    # Backend choice changes the default frame budget — FastVGGT is the path
    # you take when you want lots of frames, so we feed ffmpeg 10 fps and
    # 700 frames by default. Explicit settings still win.
    backend = settings.get("backend") or os.environ.get("INFERENCE_BACKEND", "vggt")
    if backend not in ("vggt", "fastvggt"):
        raise ValueError(f"unknown backend: {backend!r}")
    if backend == "fastvggt":
        default_fps = 10.0
        default_max_frames = 700
    else:
        default_fps = 2.0
        default_max_frames = 400

    fps = float(settings.get("fps", default_fps))
    max_frames = int(settings.get("max_frames", default_max_frames))
    target_long_side = int(settings.get("target_long_side", 1920))
    keyframes = int(settings.get("keyframes", 5))
    segment = bool(settings.get("segment", True))
    vlm_model = settings.get("vlm_model")  # forwarded to segmentation env
    if vlm_model and vlm_model not in (
        "claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-7"
    ):
        raise ValueError(f"unknown vlm_model: {vlm_model!r}")

    artifacts_volume.reload()
    scene_dir = Path(f"/artifacts/scenes/{scene_id}")
    frames_dir = scene_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    # ── Seed initial manifest so polling doesn't 404 ────────────────────
    manifest_path = scene_dir / "manifest.json"
    if not manifest_path.exists():
        Manifest(
            scene_id=scene_id,
            created_at=datetime.now(timezone.utc),
            status="processing",
            stages=Stages(
                capture=Stage(status="running"),
                poses=Stage(status="pending"),
                splat=Stage(status="pending"),
                segmentation=Stage(status="pending"),
            ),
            artifacts=Artifacts(
                splat_ply=str(scene_dir / "splat.ply"),
                annotations_json=str(scene_dir / "annotations.json"),
                thumbnail_jpg=str(scene_dir / "thumbnail.jpg"),
                cameras_json=str(scene_dir / "cameras.json"),
            ),
            stats=Stats(frame_count=0, object_count=0, splat_size_mb=0.0),
        ).write_atomic(manifest_path)
    else:
        _stage_running(scene_id, "capture")
        _set_top_status(scene_id, "processing")
    artifacts_volume.commit()
    _mirror_manifest(scene_id)

    # ── Resolve the source video to a local filesystem path ────────────
    kind = source.get("kind")
    if kind == "r2":
        r2_key = source["r2_key"]
        bucket = os.environ.get("R2_UPLOADS_BUCKET")
        s3 = _r2_client()
        if not (bucket and s3):
            _stage_failed(scene_id, "capture", "R2 source requested but R2 creds/bucket unset")
            _set_top_status(scene_id, "failed")
            artifacts_volume.commit()
            raise RuntimeError("R2 not configured")
        video_path = Path(f"/tmp/{scene_id}.mp4")
        s3.download_file(bucket, r2_key, str(video_path))
    elif kind == "local":
        # `modal volume put glasses-twin-artifacts <file> /scenes/<id>/_upload.mp4`
        # writes under /artifacts/scenes/... via the volume mount.
        video_path = Path("/artifacts") / source["modal_path"].lstrip("/")
        if not video_path.exists():
            _stage_failed(scene_id, "capture", f"local source missing: {video_path}")
            _set_top_status(scene_id, "failed")
            artifacts_volume.commit()
            raise RuntimeError(f"local source missing: {video_path}")
    else:
        raise ValueError(f"unknown source.kind: {kind!r}")

    # ── ffprobe duration/resolution ────────────────────────────────────
    with logfire.span("modal.ffprobe", scene_id=scene_id) as probe_span:
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height,duration",
                "-show_entries", "format=duration",
                "-of", "json", str(video_path),
            ],
            check=True, capture_output=True, text=True,
        )
        pj = json.loads(probe.stdout)
        stream = (pj.get("streams") or [{}])[0]
        width = int(stream.get("width", 0))
        height = int(stream.get("height", 0))
        duration_s = float(stream.get("duration") or pj.get("format", {}).get("duration") or 0.0)
        probe_span.set_attribute("video_width", width)
        probe_span.set_attribute("video_height", height)
        probe_span.set_attribute("video_duration_s", duration_s)

    span.set_attribute("video_width", width)
    span.set_attribute("video_height", height)
    span.set_attribute("video_duration_s", duration_s)

    # ── ffmpeg extract — fps cap + long-side downscale + frame cap ─────
    # scale='min(LONG, max(iw,ih))':-2 with force_original_aspect_ratio=decrease
    # is the safest one-liner that handles both portrait and landscape.
    vf = (
        f"fps={fps},"
        f"scale='if(gt(iw,ih),min({target_long_side},iw),-2)':"
        f"'if(gt(iw,ih),-2,min({target_long_side},ih))'"
    )
    # Clear stale frames from a prior run if any
    for f in frames_dir.glob("*.jpg"):
        f.unlink()
    extract_cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vf", vf,
        "-vframes", str(max_frames),
        "-q:v", "3",
        str(frames_dir / "%06d.jpg"),
    ]
    with logfire.span(
        "modal.ffmpeg_extract",
        scene_id=scene_id,
        target_fps=fps,
        target_long_side=target_long_side,
        max_frames=max_frames,
    ) as extract_span:
        try:
            subprocess.run(extract_cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            extract_span.set_attribute("returncode", exc.returncode)
            extract_span.set_attribute("stderr_tail", (exc.stderr or "")[-2000:])
            _stage_failed(scene_id, "capture", f"ffmpeg: {exc.stderr[-500:] if exc.stderr else exc!r}")
            _set_top_status(scene_id, "failed")
            artifacts_volume.commit()
            raise

        frame_paths = sorted(frames_dir.glob("*.jpg"))
        frame_count = len(frame_paths)
        extract_span.set_attribute("frame_count", frame_count)
    if frame_count == 0:
        _stage_failed(scene_id, "capture", "ffmpeg produced 0 frames")
        _set_top_status(scene_id, "failed")
        artifacts_volume.commit()
        raise RuntimeError("0 frames extracted")
    span.set_attribute("frame_count", frame_count)

    # ── Write capture.yaml ─────────────────────────────────────────────
    CaptureYaml(
        scene_id=scene_id,
        source_video=str(video_path.name),
        duration_s=duration_s,
        fps=fps,
        frame_count=frame_count,
        resolution=(width or 1920, height or 1080),
        camera_model="generic",
        captured_at=datetime.now(timezone.utc),
    ).to_yaml(scene_dir / "capture.yaml")

    # ── Update manifest: capture complete, frame_count populated ───────
    m = _read_manifest(scene_id)
    if m is not None:
        m.stages.capture.status = "complete"
        m.status = "processing"
        m.stats.frame_count = frame_count
        m.write_atomic(manifest_path)

    artifacts_volume.commit()
    _mirror_manifest(scene_id)

    # ── Fire inference ─────────────────────────────────────────────────
    spawned = False
    try:
        _inference_async.spawn(scene_id, keyframes, segment, backend, vlm_model)
        spawned = True
    except Exception as exc:
        print(f"inference spawn failed: {exc!r}", flush=True)
        span.set_attribute("inference_spawn_error", str(exc)[:200])
        _stage_failed(scene_id, "poses", f"spawn: {exc!r}")
        _set_top_status(scene_id, "failed")
        artifacts_volume.commit()
        _mirror_manifest(scene_id)
    span.set_attribute("inference_spawned", spawned)
    span.set_attribute("backend", backend)

    return {
        "status": "ok",
        "scene_id": scene_id,
        "frame_count": frame_count,
        "backend": backend,
        "inference_spawned": spawned,
    }


# ── Volume read endpoints (for local mode, which skips the R2 mirror) ──────


@app.function(
    image=image,
    timeout=60,
    volumes={"/artifacts": artifacts_volume},
    cpu=1.0,
    memory=2048,
)
@modal.fastapi_endpoint(method="GET", label="get-manifest")
def get_manifest(scene_id: str):
    """Read manifest.json straight off the Volume. Used in local mode."""
    from pathlib import Path
    from fastapi import Response

    artifacts_volume.reload()
    p = Path(_manifest_path(scene_id))
    if not p.exists():
        return Response(status_code=404)
    return Response(
        content=p.read_bytes(),
        media_type="application/json",
        headers={
            "Cache-Control": "no-cache",
            "Access-Control-Allow-Origin": "*",
        },
    )


_ALLOWED_ARTIFACTS = {
    "splat.ply",
    "points.ply",
    "cameras.json",
    "annotations.json",
    "thumbnail.jpg",
    "manifest.json",
}


@app.function(
    image=image,
    timeout=600,
    volumes={"/artifacts": artifacts_volume},
    cpu=1.0,
    memory=2048,
)
@modal.fastapi_endpoint(method="GET", label="get-artifact")
def get_artifact(scene_id: str, file: str):
    """Stream an artifact file from the Volume. Used in local mode where the
    R2 mirror is intentionally disabled.

    Uses FileResponse rather than Response(content=read_bytes()) so the file
    streams from disk to wire as bytes are read. For large artifacts (notably
    the per-pixel `points.ply` at ~230 MB) this drops time-to-first-byte by
    1-2 s and avoids holding the full payload in container memory.

    Also allows `frames/<name>.{jpg,png}` so the pipeline drill-down UI can
    render keyframe thumbnails with VLM bboxes overlaid, and
    `masks/<annotation_id>/<name>.png` so the per-object evidence gallery
    can overlay SAM 3.1 masks on those keyframes. All path forms are
    validated against directory-traversal: no `..`, no leading dot, and
    each segment is a single allowed basename.
    """
    import re
    from pathlib import Path
    from fastapi import Response
    from fastapi.responses import FileResponse

    is_frame = file.startswith("frames/")
    is_mask = file.startswith("masks/")
    if is_frame:
        # frames/<basename>.<jpg|png|jpeg> only — no traversal, no nesting.
        rest = file[len("frames/") :]
        if (
            ".." in rest
            or "/" in rest
            or "\\" in rest
            or not rest
            or rest.startswith(".")
        ):
            return Response(status_code=400, content=f"file not allowed: {file}")
        ext = rest.rsplit(".", 1)[-1].lower() if "." in rest else ""
        if ext not in ("jpg", "jpeg", "png"):
            return Response(status_code=400, content=f"file not allowed: {file}")
    elif is_mask:
        # masks/<annotation_id>/<basename>.png — exactly two segments.
        # Annotation IDs are auto-generated as `obj_NNN` (segmentation/lift_masks),
        # so a strict alnum/underscore match keeps the surface tight.
        rest = file[len("masks/") :]
        parts = rest.split("/")
        if (
            len(parts) != 2
            or ".." in parts
            or any(not p or p.startswith(".") for p in parts)
            or "\\" in rest
        ):
            return Response(status_code=400, content=f"file not allowed: {file}")
        ann_id, basename = parts
        if not re.fullmatch(r"[A-Za-z0-9_]+", ann_id):
            return Response(status_code=400, content=f"file not allowed: {file}")
        if not basename.lower().endswith(".png"):
            return Response(status_code=400, content=f"file not allowed: {file}")
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+", basename):
            return Response(status_code=400, content=f"file not allowed: {file}")
    elif file not in _ALLOWED_ARTIFACTS:
        return Response(status_code=400, content=f"file not allowed: {file}")
    artifacts_volume.reload()
    p = Path(f"/artifacts/scenes/{scene_id}/{file}")
    if not p.exists():
        return Response(status_code=404)
    if is_frame:
        ext = p.suffix.lower()
        media = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
        cache = "public, max-age=86400, immutable"
    elif is_mask:
        media = "image/png"
        cache = "public, max-age=86400, immutable"
    else:
        media = _ARTIFACT_CONTENT_TYPE.get(file, "application/octet-stream")
        cache = "no-cache" if file == "manifest.json" else "public, max-age=300"
    return FileResponse(
        path=str(p),
        media_type=media,
        headers={
            "Cache-Control": cache,
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.local_entrypoint()
def smoke(scene_id: str = "modal_smoke") -> None:
    """Local smoke from your laptop: `modal run inference/modal_app.py::smoke --scene-id foo`."""
    print("prepare:", prepare_scene.remote({"scene_id": scene_id}))
    # NOTE: this assumes you've already uploaded frames into the volume:
    #   modal volume put glasses-twin-artifacts ./local_scene scenes/<scene_id>
    print("inference:", run_inference.remote({"scene_id": scene_id}))
