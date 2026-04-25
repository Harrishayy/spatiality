"""VGGT pose + point cloud estimation.

Spec: plans/modules/02_inference.md. VGGT is feed-forward — load checkpoint,
run on a stack of frames, write cameras.json + points.ply.

VGGT API surface (verified against bundled facebookresearch/vggt source):
  from vggt.models.vggt import VGGT
  from vggt.utils.load_fn import load_and_preprocess_images   # takes PATHS
  from vggt.utils.pose_enc import pose_encoding_to_extri_intri
  model = VGGT()                                              # then load weights
  images = load_and_preprocess_images(paths)                  # (S, 3, H, W)
  preds = model(images)                                       # auto-batches
  extr, intr = pose_encoding_to_extri_intri(preds["pose_enc"], images.shape[-2:])
  pts = preds["world_points"]            # (B, S, H, W, 3)
  pts_conf = preds["world_points_conf"]  # (B, S, H, W)

Weights file: huggingface.co/facebook/VGGT-1B distributes a `model.safetensors`.
The bundle script renames it to `vggt.pt` for stability, but the on-disk format
is still safetensors — torch.load() WILL NOT read it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

VGGT_CHECKPOINT = os.environ.get("VGGT_CHECKPOINT", "facebook/VGGT-1B")
VGGT_LOCAL_WEIGHTS = os.environ.get("VGGT_LOCAL_WEIGHTS")  # e.g. /weights/vggt.pt on Modal
# Cap on points written to points.ply — VGGT emits H*W*S points which is ~20M+
# for typical inputs. The point cloud is a seed for 3DGRUT, not the final scene,
# so subsample.
VGGT_POINTS_MAX = int(os.environ.get("VGGT_POINTS_MAX", "200000"))
# Confidence floor for the world-points head (0..1 after softmax-style activation).
VGGT_POINTS_CONF_MIN = float(os.environ.get("VGGT_POINTS_CONF_MIN", "0.5"))


def _list_image_paths(frames_dir: Path) -> list[Path]:
    paths = sorted(p for p in frames_dir.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
    if not paths:
        raise FileNotFoundError(f"no frames in {frames_dir}")
    return paths


def _is_safetensors(path: str) -> bool:
    """Sniff the first 12 bytes: safetensors starts with 8-byte LE header length + JSON `{`."""
    try:
        with open(path, "rb") as f:
            head = f.read(12)
        if len(head) < 12:
            return False
        return head[8:9] == b"{"
    except OSError:
        return False


def _load_model():
    import torch
    from vggt.models.vggt import VGGT

    if VGGT_LOCAL_WEIGHTS:
        model = VGGT()
        if _is_safetensors(VGGT_LOCAL_WEIGHTS):
            from safetensors.torch import load_file as _safe_load
            state = _safe_load(VGGT_LOCAL_WEIGHTS, device="cpu")
        else:
            state = torch.load(VGGT_LOCAL_WEIGHTS, map_location="cpu")
            if isinstance(state, dict) and "model" in state and isinstance(state["model"], dict):
                state = state["model"]
        missing, unexpected = model.load_state_dict(state, strict=False)
        if missing:
            print(f"vggt: {len(missing)} missing keys (first: {missing[0]})")
        if unexpected:
            print(f"vggt: {len(unexpected)} unexpected keys (first: {unexpected[0]})")
    else:
        # Online path — fetches from HF. Only viable in environments with internet
        # (Modal, Brev, local dev). Skip if you're in a sandboxed/offline env.
        model = VGGT.from_pretrained(VGGT_CHECKPOINT)
    return model.eval().to("cuda" if torch.cuda.is_available() else "cpu")


def _preprocess(paths: list[Path]):
    """Preprocess via VGGT's helper (expects PATHS, not arrays). Returns (S, 3, H, W)."""
    from vggt.utils.load_fn import load_and_preprocess_images

    return load_and_preprocess_images([str(p) for p in paths])


def _save_cameras(extr, intr, frame_paths: list[Path], out: Path) -> None:
    """Write cameras.json: list of {frame, extrinsic 4x4, intrinsic 3x3}.

    extr: (B, S, 3, 4)  intr: (B, S, 3, 3)
    """
    e = extr.squeeze(0).detach().cpu().numpy()  # (S, 3, 4)
    k = intr.squeeze(0).detach().cpu().numpy()  # (S, 3, 3)
    cameras = []
    for i, fp in enumerate(frame_paths):
        ext = e[i]
        if ext.shape == (3, 4):
            ext = np.vstack([ext, [0, 0, 0, 1]])
        cameras.append(
            {
                "frame": fp.name,
                "extrinsic": ext.tolist(),
                "intrinsic": k[i].tolist(),
            }
        )
    out.write_text(json.dumps(cameras, indent=2))


def _save_points(preds: dict, out: Path) -> None:
    """Write points.ply (ASCII) — confidence-filtered + subsampled to <= VGGT_POINTS_MAX."""
    pts = preds.get("world_points")
    if pts is None:
        out.write_bytes(_empty_ply_header())
        return
    arr = pts.squeeze(0).detach().cpu().numpy().reshape(-1, 3)

    conf = preds.get("world_points_conf")
    if conf is not None:
        c = conf.squeeze(0).detach().cpu().numpy().reshape(-1)
        keep = (c >= VGGT_POINTS_CONF_MIN) & np.isfinite(arr).all(axis=1)
    else:
        keep = np.isfinite(arr).all(axis=1)
    arr = arr[keep]

    if len(arr) > VGGT_POINTS_MAX:
        idx = np.random.default_rng(0).choice(len(arr), size=VGGT_POINTS_MAX, replace=False)
        arr = arr[idx]

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
    from vggt.utils.pose_enc import pose_encoding_to_extri_intri

    paths = _list_image_paths(frames_dir)
    images = _preprocess(paths)  # (S, 3, H, W) on CPU
    model = _load_model()
    device = next(model.parameters()).device
    images = images.to(device)

    with torch.no_grad():
        # bfloat16 autocast matches VGGT's official inference recipe.
        try:
            ctx = torch.cuda.amp.autocast(dtype=torch.bfloat16) if device.type == "cuda" else torch.cpu.amp.autocast(dtype=torch.bfloat16)
        except (AttributeError, TypeError):
            from contextlib import nullcontext
            ctx = nullcontext()
        with ctx:
            preds = model(images)

    extr, intr = pose_encoding_to_extri_intri(preds["pose_enc"], images.shape[-2:])
    _save_cameras(extr, intr, paths, out_dir / "cameras.json")
    _save_points(preds, out_dir / "points.ply")
    print(f"vggt: {len(paths)} frames -> cameras.json + points.ply")
