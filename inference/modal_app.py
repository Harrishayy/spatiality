"""Modal app skeleton — deploys cleanly even before Session B wires real training.

When real training lands, uncomment the VGGT/3DGRUT install lines and replace
the body of run_inference with the actual pipeline.
"""

from __future__ import annotations

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
        "pydantic>=2.7",
        "pyyaml>=6",
    )
    # TODO(swap): re-enable when Session B wires real training.
    # .run_commands(
    #     "git clone https://github.com/facebookresearch/vggt /opt/vggt && pip install -e /opt/vggt",
    #     "git clone https://github.com/nv-tlabs/3dgrut /opt/3dgrut && pip install --no-build-isolation -e /opt/3dgrut",
    # )
)

artifacts_volume = modal.Volume.from_name(
    "glasses-twin-artifacts", create_if_missing=True
)


@app.function(
    image=image,
    gpu="A100",
    timeout=600,
    volumes={"/artifacts": artifacts_volume},
    # secrets=[modal.Secret.from_name("logfire")],  # TODO(swap): create the Modal secret first.
)
@modal.web_endpoint(method="POST")
def run_inference(payload: dict) -> dict:
    scene_id = payload["scene_id"]
    # TODO(swap): real pipeline:
    #   1. read /artifacts/scenes/<scene_id>/frames/
    #   2. run VGGT for poses → cameras.json + points.ply
    #   3. run 3DGRUT for splat → splat.ply
    #   4. update manifest.json after each stage
    return {"status": "stub", "scene_id": scene_id}
