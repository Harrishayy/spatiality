"""VGGT pose + point cloud estimation.

Spec: plans/modules/02_inference.md. VGGT is feed-forward — load checkpoint,
run on a stack of frames, write cameras.json + points.ply.

VGGT API surface (verified against facebookresearch/vggt as of April 2026):
  from vggt.models.vggt import VGGT
  model = VGGT.from_pretrained("facebook/VGGT-1B").cuda()
  with torch.no_grad():
      preds = model(images)            # B,S,3,H,W
  preds["extrinsic"], preds["intrinsic"], preds["world_points"], ...

If the checkpoint name / output keys drift, update _load_model() and _save_cameras().
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

VGGT_CHECKPOINT = os.environ.get("VGGT_CHECKPOINT", "facebook/VGGT-1B")
VGGT_LOCAL_WEIGHTS = os.environ.get("VGGT_LOCAL_WEIGHTS")  # e.g. /kaggle/input/glasses-twin-bundle/weights/vggt.pt


def _load_images(frames_dir: Path) -> "list[np.ndarray]":
    from PIL import Image

    paths = sorted([p for p in frames_dir.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg")])
    if not paths:
        raise FileNotFoundError(f"no frames in {frames_dir}")
    return [np.array(Image.open(p).convert("RGB")) for p in paths], paths


def _load_model():
    import torch
    from vggt.models.vggt import VGGT

    if VGGT_LOCAL_WEIGHTS:
        model = VGGT()
        state = torch.load(VGGT_LOCAL_WEIGHTS, map_location="cpu")
        # Handle either a raw state_dict or a {model: state_dict} wrapper.
        if isinstance(state, dict) and "model" in state and isinstance(state["model"], dict):
            state = state["model"]
        model.load_state_dict(state, strict=False)
    else:
        model = VGGT.from_pretrained(VGGT_CHECKPOINT)
    return model.eval().to("cuda" if torch.cuda.is_available() else "cpu")


def _to_tensor(images: "list[np.ndarray]"):
    """Stack frames into the (B=1, S, 3, H, W) layout VGGT expects."""
    import torch

    # VGGT ships an image_processor; use it if available.
    try:
        from vggt.utils.load_fn import load_and_preprocess_images

        return load_and_preprocess_images(images)  # already returns (S, 3, H, W) tensor
    except Exception:
        # Fallback: naive resize + normalize.
        import torch.nn.functional as F

        ts = []
        for img in images:
            t = torch.from_numpy(img).permute(2, 0, 1).float() / 255.0
            t = F.interpolate(t.unsqueeze(0), size=(518, 518), mode="bilinear", align_corners=False).squeeze(0)
            ts.append(t)
        return torch.stack(ts)


def _save_cameras(preds: dict, frame_paths: list, out: Path) -> None:
    """Write cameras.json in 3DGRUT-compatible JSON.

    Schema is intentionally simple — list of {frame, extrinsic 4x4, intrinsic 3x3}.
    3DGRUT actually consumes its own per-dataset format; we'll convert in splat.run.
    """
    extrinsic = preds["extrinsic"].squeeze(0).detach().cpu().numpy()  # (S, 3, 4) or (S, 4, 4)
    intrinsic = preds["intrinsic"].squeeze(0).detach().cpu().numpy()  # (S, 3, 3)
    cameras = []
    for i, fp in enumerate(frame_paths):
        ext = extrinsic[i]
        if ext.shape == (3, 4):
            ext = np.vstack([ext, [0, 0, 0, 1]])
        cameras.append(
            {
                "frame": fp.name,
                "extrinsic": ext.tolist(),
                "intrinsic": intrinsic[i].tolist(),
            }
        )
    out.write_text(json.dumps(cameras, indent=2))


def _save_points(preds: dict, out: Path) -> None:
    """Write points.ply (ASCII) from VGGT's predicted world points."""
    pts = preds.get("world_points") or preds.get("points")
    if pts is None:
        out.write_bytes(_empty_ply_header())
        return
    arr = pts.squeeze(0).detach().cpu().numpy().reshape(-1, 3)
    arr = arr[np.isfinite(arr).all(axis=1)]
    header = (
        "ply\nformat ascii 1.0\n"
        f"element vertex {len(arr)}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "end_header\n"
    )
    with out.open("w") as f:
        f.write(header)
        for x, y, z in arr:
            f.write(f"{x} {y} {z}\n")


def _empty_ply_header() -> bytes:
    return (
        b"ply\nformat binary_little_endian 1.0\nelement vertex 0\n"
        b"property float x\nproperty float y\nproperty float z\nend_header\n"
    )


def run(frames_dir: Path, out_dir: Path) -> None:
    import torch

    images, paths = _load_images(frames_dir)
    model = _load_model()
    batch = _to_tensor(images).unsqueeze(0).to(next(model.parameters()).device)
    with torch.no_grad():
        preds = model(batch)
    _save_cameras(preds, paths, out_dir / "cameras.json")
    _save_points(preds, out_dir / "points.ply")
    print(f"vggt: {len(paths)} frames -> cameras.json + points.ply")
