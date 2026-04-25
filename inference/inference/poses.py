"""VGGT pose + per-pixel surfel synthesis.

Spec: plans/modules/02_inference.md.

This stage replaces the previous "VGGT pose-only" path. Per-scene gsplat
training is gone; instead we use VGGT's `depth_head` + `camera_head` to
synthesize anisotropic surface-aligned Gaussians directly from the
per-pixel depth grid. The README of facebookresearch/vggt explicitly
recommends unprojecting depth+camera over reading the world-points head
(more accurate at depth discontinuities), and the depth head also exposes
a per-pixel confidence we use to gate outliers and modulate opacity.

Outputs (per scene dir):
  cameras.json   — list of {frame, extrinsic 4x4, intrinsic 3x3} (unchanged contract).
  points.ply     — binary little-endian, fields x y z red green blue confidence.
                   For visual debugging and as a public artifact; the splat
                   stage doesn't read it.
  surfels.npz    — per-pixel surfel arrays (xyz, f_dc, opacity, log_scale,
                   quat_wxyz, conf). Consumed by splat.py for voxel-downsample
                   and INRIA-PLY export.

VGGT model output keys (verified against bundled facebookresearch/vggt source):
  preds["pose_enc"]       — (B, S, pose_dim) → extr+intr via pose_encoding_to_extri_intri
  preds["depth"]          — (B, S, H, W, 1) per-pixel depth in camera frame
  preds["depth_conf"]     — (B, S, H, W) per-pixel confidence in [0, 1]
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

VGGT_CHECKPOINT = os.environ.get("VGGT_CHECKPOINT", "facebook/VGGT-1B")
VGGT_LOCAL_WEIGHTS = os.environ.get("VGGT_LOCAL_WEIGHTS")  # /weights/vggt.pt on Modal

# ── Tunable knobs (defaults mirrored in modal_app.py:COMMON_ENV) ─────────
# Frame selection — VGGT compute is O(N²); quality saturates around 16–32
# views, A100-80GB headroom lets us go to 48.
VGGT_FRAMES_MAX = int(os.environ.get("VGGT_FRAMES_MAX", "48"))
VGGT_FPS_TARGET = float(os.environ.get("VGGT_FPS_TARGET", "4.0"))
VGGT_BLUR_DROP_PCT = float(os.environ.get("VGGT_BLUR_DROP_PCT", "0.20"))
VGGT_FRAMES_MIN = int(os.environ.get("VGGT_FRAMES_MIN", "8"))

# Per-pixel gates — keep what's geometrically reliable.
VGGT_DEPTH_CONF_MIN = float(os.environ.get("VGGT_DEPTH_CONF_MIN", "0.2"))
# Drop pixels at silhouette edges (depth gradient relative to local depth).
# These otherwise project as floaters between foreground and background.
VGGT_DEPTH_GRAD_MAX = float(os.environ.get("VGGT_DEPTH_GRAD_MAX", "0.04"))

# Surfel "pixel footprint" multiplier. Tangent scale = depth * footprint / focal.
# Footprint=1 makes each surfel exactly one source pixel wide; after voxel
# downsample, adjacent surfels sit ~voxel_size apart with gaps between them
# (visible speckle). 4.0 gives ~50% overlap between neighbours so surfaces fill
# in cleanly. Industry surfel renderers (Splatt3R, InstantSplat) use 2-4×.
VGGT_SURFEL_PIXEL_FOOTPRINT = float(os.environ.get("VGGT_SURFEL_PIXEL_FOOTPRINT", "4.0"))

# Edge-preserving depth smoothing. Bilateral filter cleans VGGT prediction
# noise within continuous surfaces without blurring across depth discontinuities
# (which would create floater surfels at silhouette edges). Standard step in
# photogrammetry and surfel-rendering pipelines (cf. Splatt3R, MVSplat).
# Set DEPTH_BILATERAL_D=0 to disable.
VGGT_DEPTH_BILATERAL_D = int(os.environ.get("VGGT_DEPTH_BILATERAL_D", "5"))
VGGT_DEPTH_BILATERAL_SIGMA_S = float(os.environ.get("VGGT_DEPTH_BILATERAL_SIGMA_S", "50.0"))
VGGT_DEPTH_BILATERAL_SIGMA_R = float(os.environ.get("VGGT_DEPTH_BILATERAL_SIGMA_R", "0.05"))

# Drop pixels with depth above this percentile × multiplier (per-frame). Catches
# sky / distant background that VGGT predicts as ~10× scene depth — those would
# project as enormous low-confidence surfels behind everything.
VGGT_DEPTH_FAR_PCT = float(os.environ.get("VGGT_DEPTH_FAR_PCT", "95.0"))
VGGT_DEPTH_FAR_MULT = float(os.environ.get("VGGT_DEPTH_FAR_MULT", "1.5"))

# SH DC encoding constant — inverse of the band-0 spherical harmonic Y_0_0.
# Mirror of SH_C0 in web/app/components/SplatViewer.tsx.
SH_C0 = 0.282094791


# ── Frame selection ─────────────────────────────────────────────────────
from ._frame_select import select_frames as _select_frames_impl


def _select_frames(frames_dir: Path) -> list[Path]:
    return _select_frames_impl(
        frames_dir,
        frames_max=VGGT_FRAMES_MAX,
        frames_min=VGGT_FRAMES_MIN,
        blur_drop_pct=VGGT_BLUR_DROP_PCT,
        log_prefix="vggt",
    )


# ── Model loading ───────────────────────────────────────────────────────
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
        model = VGGT.from_pretrained(VGGT_CHECKPOINT)
    return model.eval().to("cuda" if torch.cuda.is_available() else "cpu")


def _preprocess(paths: list[Path]):
    """Preprocess via VGGT's helper (expects PATHS, not arrays). Returns (S, 3, H, W)."""
    from vggt.utils.load_fn import load_and_preprocess_images

    return load_and_preprocess_images([str(p) for p in paths])


def _load_raw_rgb(paths: list[Path], target_hw: tuple[int, int]) -> np.ndarray:
    """RGB sampled at VGGT's input resolution, NOT normalised. Used for surfel
    color (the VGGT-preprocessed images go through ImageNet-style normalisation
    so they aren't directly usable as colors).

    Loads in parallel via a thread pool — PIL releases the GIL during JPEG
    decode + resize, and writes to disjoint slots of `out`, so threading is
    safe. ~6× speedup on a 4-core container at 200 frames.
    """
    from concurrent.futures import ThreadPoolExecutor
    from PIL import Image

    H, W = target_hw
    out = np.empty((len(paths), H, W, 3), dtype=np.float32)
    workers = int(os.environ.get("FRAME_SELECT_WORKERS", str(min(8, (os.cpu_count() or 4)))))

    def _load_one(idx_path: tuple[int, Path]) -> None:
        i, p = idx_path
        img = Image.open(p).convert("RGB")
        # Match VGGT's resize: keep aspect, fit long side. The preprocess
        # helper already pads or crops to (H, W) — we mimic with simple
        # bilinear resize because per-pixel correspondence with depth is what
        # matters, not exact pixel-for-pixel alignment with VGGT's internal
        # preprocessing.
        if img.size != (W, H):
            img = img.resize((W, H), Image.BILINEAR)
        out[i] = np.asarray(img, dtype=np.float32) / 255.0

    if workers <= 1 or len(paths) <= 1:
        for ip in enumerate(paths):
            _load_one(ip)
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            # `list(...)` forces every future to materialise → exceptions surface.
            list(ex.map(_load_one, enumerate(paths)))
    return out


# ── Output: cameras.json (unchanged contract) ───────────────────────────
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


# ── Per-frame surfel synthesis ──────────────────────────────────────────
def _unproject_frame(
    depth: np.ndarray,       # (H, W)
    K: np.ndarray,           # (3, 3) intrinsics
    E: np.ndarray,           # (4, 4) extrinsic, camera-from-world (OpenCV)
) -> np.ndarray:
    """Unproject a per-pixel depth map into world coordinates.

    Returns an (H, W, 3) array of world-space points. Pixels with non-positive
    or non-finite depth are returned as NaN — caller filters.
    """
    H, W = depth.shape
    fx, fy = K[0, 0], K[1, 1]
    cx, cy = K[0, 2], K[1, 2]
    u = np.arange(W, dtype=np.float32)[None, :].repeat(H, axis=0)
    v = np.arange(H, dtype=np.float32)[:, None].repeat(W, axis=1)

    # Camera-frame coords (OpenCV: +Z forward, +Y down, +X right).
    z = depth
    x_cam = (u - cx) * z / fx
    y_cam = (v - cy) * z / fy

    # Stack to (H, W, 4) homogeneous in camera frame, then transform to world.
    cam_pts = np.stack([x_cam, y_cam, z, np.ones_like(z)], axis=-1)
    # E is camera-from-world: world_pt = inv(E) @ cam_pt.
    E_inv = np.linalg.inv(E)
    world = cam_pts @ E_inv.T  # (H, W, 4)
    world_pts = world[..., :3]

    bad = ~np.isfinite(z) | (z <= 0)
    world_pts[bad] = np.nan
    return world_pts


def _basis_to_quat_wxyz(R: np.ndarray) -> np.ndarray:
    """Convert (N, 3, 3) rotation matrices (column vectors are basis) to
    (N, 4) quaternions in wxyz order — matches Spark's convention.

    Numerically robust branch selection (Shepperd's method).
    """
    N = R.shape[0]
    m00 = R[:, 0, 0]; m01 = R[:, 0, 1]; m02 = R[:, 0, 2]
    m10 = R[:, 1, 0]; m11 = R[:, 1, 1]; m12 = R[:, 1, 2]
    m20 = R[:, 2, 0]; m21 = R[:, 2, 1]; m22 = R[:, 2, 2]
    trace = m00 + m11 + m22

    q = np.empty((N, 4), dtype=np.float32)

    # Branch 1: trace > 0
    b1 = trace > 0
    s = np.where(b1, np.sqrt(np.maximum(trace + 1.0, 1e-12)) * 2.0, 1.0)
    q[b1, 0] = 0.25 * s[b1]
    q[b1, 1] = (m21[b1] - m12[b1]) / s[b1]
    q[b1, 2] = (m02[b1] - m20[b1]) / s[b1]
    q[b1, 3] = (m10[b1] - m01[b1]) / s[b1]

    # Branch 2: m00 is largest diagonal
    b2 = ~b1 & (m00 >= m11) & (m00 >= m22)
    s2 = np.where(b2, np.sqrt(np.maximum(1.0 + m00 - m11 - m22, 1e-12)) * 2.0, 1.0)
    q[b2, 0] = (m21[b2] - m12[b2]) / s2[b2]
    q[b2, 1] = 0.25 * s2[b2]
    q[b2, 2] = (m01[b2] + m10[b2]) / s2[b2]
    q[b2, 3] = (m02[b2] + m20[b2]) / s2[b2]

    # Branch 3: m11 is largest diagonal
    b3 = ~b1 & ~b2 & (m11 >= m22)
    s3 = np.where(b3, np.sqrt(np.maximum(1.0 + m11 - m00 - m22, 1e-12)) * 2.0, 1.0)
    q[b3, 0] = (m02[b3] - m20[b3]) / s3[b3]
    q[b3, 1] = (m01[b3] + m10[b3]) / s3[b3]
    q[b3, 2] = 0.25 * s3[b3]
    q[b3, 3] = (m12[b3] + m21[b3]) / s3[b3]

    # Branch 4: m22 is largest diagonal
    b4 = ~b1 & ~b2 & ~b3
    s4 = np.where(b4, np.sqrt(np.maximum(1.0 + m22 - m00 - m11, 1e-12)) * 2.0, 1.0)
    q[b4, 0] = (m10[b4] - m01[b4]) / s4[b4]
    q[b4, 1] = (m02[b4] + m20[b4]) / s4[b4]
    q[b4, 2] = (m12[b4] + m21[b4]) / s4[b4]
    q[b4, 3] = 0.25 * s4[b4]

    # Normalise.
    q /= np.linalg.norm(q, axis=1, keepdims=True) + 1e-9
    return q


def _smooth_depth(depth: np.ndarray) -> np.ndarray:
    """Bilateral filter on depth (edge-preserving). Cleans VGGT prediction noise
    inside continuous surfaces without blurring depth discontinuities — same
    pattern as Splatt3R, InstantSplat, and most photogrammetry post-processing.
    No-op when VGGT_DEPTH_BILATERAL_D == 0."""
    if VGGT_DEPTH_BILATERAL_D <= 0:
        return depth
    import cv2

    # cv2.bilateralFilter requires float32 contiguous, finite values. Feed NaNs
    # through as 0; the gates downstream (depth > 0, isfinite) drop them anyway.
    d = np.where(np.isfinite(depth), depth, 0.0).astype(np.float32, copy=False)
    return cv2.bilateralFilter(
        d,
        d=VGGT_DEPTH_BILATERAL_D,
        sigmaColor=VGGT_DEPTH_BILATERAL_SIGMA_R,
        sigmaSpace=VGGT_DEPTH_BILATERAL_SIGMA_S,
    )


def _frame_surfels(
    depth: np.ndarray,       # (H, W)
    depth_conf: np.ndarray,  # (H, W)
    rgb: np.ndarray,         # (H, W, 3) in [0, 1]
    K: np.ndarray,           # (3, 3)
    E: np.ndarray,           # (4, 4) camera-from-world
) -> dict:
    """Synthesize per-pixel anisotropic surfels for one frame.

    Returns a dict of arrays (each (M,) or (M, *)) over kept pixels:
      xyz       (M, 3) world position
      f_dc      (M, 3) SH band-0 coefficient
      opacity   (M,)   raw (logit) opacity
      log_scale (M, 3) log of (s_t, s_t, s_n) — tangent, tangent, normal
      quat      (M, 4) wxyz quaternion aligning surfel-local +Z with world normal
      conf      (M,)   passed through for downstream voxel-downsample tie-breaking

    Pixels are dropped when:
      - depth is non-finite or <= 0
      - confidence < VGGT_DEPTH_CONF_MIN
      - relative depth gradient exceeds VGGT_DEPTH_GRAD_MAX (silhouette guard)
      - depth above a per-frame far cap (sky / distant background)
      - any neighbor needed for the gradient is itself bad (border pixels too)
    """
    # Smooth depth first — every downstream computation (unproject, gradient,
    # surface normal) sees the cleaned signal.
    depth = _smooth_depth(depth)

    H, W = depth.shape

    world = _unproject_frame(depth, K, E)  # (H, W, 3) — NaN where depth is bad

    # Depth gradient in pixel space, normalised by local depth (relative gradient).
    # Use central differences; mark borders bad so we don't use stale neighbors.
    valid = np.isfinite(depth) & (depth > 0)
    d_pad = np.where(valid, depth, np.nan)
    grad_u = np.full_like(d_pad, np.nan)
    grad_v = np.full_like(d_pad, np.nan)
    grad_u[:, 1:-1] = (d_pad[:, 2:] - d_pad[:, :-2]) * 0.5
    grad_v[1:-1, :] = (d_pad[2:, :] - d_pad[:-2, :]) * 0.5
    rel_grad_mag = np.sqrt(grad_u ** 2 + grad_v ** 2) / (d_pad + 1e-9)

    # World-space partial derivatives ∂p/∂u, ∂p/∂v via central differences on
    # the unprojected map. Borders are NaN by construction.
    dpdu = np.full_like(world, np.nan)
    dpdv = np.full_like(world, np.nan)
    dpdu[:, 1:-1, :] = (world[:, 2:, :] - world[:, :-2, :]) * 0.5
    dpdv[1:-1, :, :] = (world[2:, :, :] - world[:-2, :, :]) * 0.5

    # Per-frame depth far-cap: drop sky / distant background. VGGT predicts very
    # large depths for unbounded regions, which would project as enormous
    # low-confidence surfels behind everything.
    valid_depths = depth[valid]
    if valid_depths.size > 0:
        far_cap = float(np.percentile(valid_depths, VGGT_DEPTH_FAR_PCT)) * VGGT_DEPTH_FAR_MULT
    else:
        far_cap = float("inf")

    # Mask: confident, in-bounds, low gradient, not too distant, valid neighbors.
    keep = (
        valid
        & (depth <= far_cap)
        & (depth_conf >= VGGT_DEPTH_CONF_MIN)
        & np.isfinite(rel_grad_mag)
        & (rel_grad_mag <= VGGT_DEPTH_GRAD_MAX)
        & np.isfinite(dpdu).all(axis=-1)
        & np.isfinite(dpdv).all(axis=-1)
    )
    if not keep.any():
        empty = np.empty((0, 3), dtype=np.float32)
        return {
            "xyz": empty, "f_dc": empty,
            "opacity": np.empty((0,), dtype=np.float32),
            "log_scale": empty, "quat": np.empty((0, 4), dtype=np.float32),
            "conf": np.empty((0,), dtype=np.float32),
        }

    idx = np.flatnonzero(keep.reshape(-1))
    pts = world.reshape(-1, 3)[idx].astype(np.float32)
    e1 = dpdu.reshape(-1, 3)[idx].astype(np.float32)
    e2_raw = dpdv.reshape(-1, 3)[idx].astype(np.float32)
    cols = rgb.reshape(-1, 3)[idx].astype(np.float32)
    confs = depth_conf.reshape(-1)[idx].astype(np.float32)
    depths = depth.reshape(-1)[idx].astype(np.float32)

    # Gram-Schmidt: e1 normalised; e2 = (e2_raw - <e2_raw, e1> e1) normalised;
    # n = e1 × e2 (right-handed, +Z forward in surfel-local frame).
    e1 /= np.linalg.norm(e1, axis=1, keepdims=True) + 1e-9
    e2 = e2_raw - (np.einsum("ij,ij->i", e2_raw, e1)[:, None]) * e1
    e2 /= np.linalg.norm(e2, axis=1, keepdims=True) + 1e-9
    n = np.cross(e1, e2)
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-9
    R = np.stack([e1, e2, n], axis=-1)  # (M, 3, 3) columns are basis vectors
    quat = _basis_to_quat_wxyz(R)

    # Tangent scale ≈ pixel footprint at this depth, scaled by a multiplier so
    # each surfel covers more than one source pixel and adjacent surfels overlap
    # after voxel downsample (closes the speckle gaps).
    focal = float(0.5 * (K[0, 0] + K[1, 1]))
    s_t = (depths * VGGT_SURFEL_PIXEL_FOOTPRINT / focal).clip(min=1e-6)
    s_n = (0.3 * s_t).clip(min=1e-6)
    log_scale = np.log(np.stack([s_t, s_t, s_n], axis=1)).astype(np.float32)

    # SH DC and opacity.
    f_dc = ((cols - 0.5) / SH_C0).astype(np.float32)
    op_clip = np.clip(confs, 0.1, 0.99)
    raw_opacity = np.log(op_clip / (1.0 - op_clip)).astype(np.float32)

    return {
        "xyz": pts,
        "f_dc": f_dc,
        "opacity": raw_opacity,
        "log_scale": log_scale,
        "quat": quat,
        "conf": confs,
    }


# ── Output: binary points.ply (xyz + RGB + conf) for debugging ──────────
def _save_points_ply(xyz: np.ndarray, rgb: np.ndarray, conf: np.ndarray, out: Path) -> None:
    """Binary little-endian PLY with fields:
        x y z (float32)  red green blue (uchar)  confidence (float32)
    Public artifact for visual debugging — splat.py does not read it."""
    n = xyz.shape[0]
    rgb_u8 = np.clip(rgb * 255.0, 0, 255).astype(np.uint8)
    header = (
        b"ply\n"
        b"format binary_little_endian 1.0\n"
        b"element vertex " + str(n).encode() + b"\n"
        b"property float x\nproperty float y\nproperty float z\n"
        b"property uchar red\nproperty uchar green\nproperty uchar blue\n"
        b"property float confidence\n"
        b"end_header\n"
    )
    # Per-vertex layout: 3*float (xyz) + 3*uchar (rgb) + 1*float (conf) = 19 bytes.
    rec = np.empty(n, dtype=np.dtype([
        ("xyz", "<f4", 3),
        ("rgb", "u1", 3),
        ("conf", "<f4"),
    ]))
    rec["xyz"] = xyz.astype(np.float32)
    rec["rgb"] = rgb_u8
    rec["conf"] = conf.astype(np.float32)
    with out.open("wb") as f:
        f.write(header)
        f.write(rec.tobytes())


# ── Public entry point ──────────────────────────────────────────────────
def run(frames_dir: Path, out_dir: Path) -> None:
    """Run VGGT, then synthesize per-pixel surfels. Writes:
        cameras.json   — list of {frame, extrinsic, intrinsic}
        points.ply     — binary RGB+conf cloud (debug artifact)
        surfels.npz    — per-pixel surfel arrays consumed by splat.py
    """
    import torch
    from vggt.utils.pose_enc import pose_encoding_to_extri_intri

    paths = _select_frames(frames_dir)
    images = _preprocess(paths)  # (S, 3, H, W) on CPU, ImageNet-normalised
    model = _load_model()
    device = next(model.parameters()).device
    images_dev = images.to(device)

    # bfloat16 autocast matches VGGT's official inference recipe.
    with torch.no_grad():
        try:
            ctx = torch.cuda.amp.autocast(dtype=torch.bfloat16) if device.type == "cuda" \
                else torch.cpu.amp.autocast(dtype=torch.bfloat16)
        except (AttributeError, TypeError):
            from contextlib import nullcontext
            ctx = nullcontext()
        with ctx:
            preds = model(images_dev)

    # ── Cameras (extrinsics + intrinsics from pose_enc) ─────────────────
    extr, intr = pose_encoding_to_extri_intri(preds["pose_enc"], images.shape[-2:])
    _save_cameras(extr, intr, paths, out_dir / "cameras.json")

    # ── Depth + confidence (per-pixel, camera-frame depth) ──────────────
    if "depth" not in preds or "depth_conf" not in preds:
        raise RuntimeError(
            "vggt: model output missing depth/depth_conf; "
            "this build of VGGT does not expose the depth head"
        )
    depth = preds["depth"].squeeze(0).detach().float().cpu().numpy()           # (S, H, W, 1)
    depth_conf = preds["depth_conf"].squeeze(0).detach().float().cpu().numpy()  # (S, H, W)
    if depth.ndim == 4 and depth.shape[-1] == 1:
        depth = depth[..., 0]
    extr_np = extr.squeeze(0).detach().cpu().numpy()  # (S, 3, 4) or (S, 4, 4)
    intr_np = intr.squeeze(0).detach().cpu().numpy()  # (S, 3, 3)

    # Make extrinsics 4×4 (camera-from-world OpenCV convention).
    if extr_np.shape[-2:] == (3, 4):
        bottom = np.tile(np.array([0, 0, 0, 1], dtype=extr_np.dtype), (extr_np.shape[0], 1, 1))
        extr_np = np.concatenate([extr_np, bottom], axis=1)

    H, W = depth.shape[-2:]
    rgb_all = _load_raw_rgb(paths, (H, W))  # (S, H, W, 3) ∈ [0, 1]

    # ── Per-frame surfel synthesis, stacked across frames ───────────────
    # Parallel: each `_frame_surfels` is a pure NumPy + cv2 (bilateral
    # filter) function over disjoint per-frame slices. Both NumPy and cv2
    # release the GIL, so threading gives a ~3-4× speedup over the previous
    # sequential per-frame loop. Order is preserved by writing into a
    # pre-sized `parts` list under indexed assignment.
    from concurrent.futures import ThreadPoolExecutor
    workers = int(os.environ.get("FRAME_SELECT_WORKERS", str(min(8, (os.cpu_count() or 4)))))
    n_frames = len(paths)
    parts: list[dict] = [None] * n_frames  # type: ignore[list-item]

    def _do_frame(i: int) -> None:
        parts[i] = _frame_surfels(
            depth=depth[i],
            depth_conf=depth_conf[i],
            rgb=rgb_all[i],
            K=intr_np[i],
            E=extr_np[i],
        )

    if workers <= 1 or n_frames <= 1:
        for i in range(n_frames):
            _do_frame(i)
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(_do_frame, range(n_frames)))
    for i, part in enumerate(parts):
        print(
            f"vggt: frame {i + 1}/{n_frames} → {part['xyz'].shape[0]} surfels",
            flush=True,
        )

    def _cat(key: str) -> np.ndarray:
        return np.concatenate([p[key] for p in parts], axis=0) if parts else np.empty((0,))

    surfels = {k: _cat(k) for k in ("xyz", "f_dc", "opacity", "log_scale", "quat", "conf")}
    n_total = surfels["xyz"].shape[0]
    if n_total == 0:
        raise RuntimeError(
            "vggt: zero surfels survived confidence/gradient gates — "
            "VGGT depth output is degenerate (check input frames + weights)"
        )
    print(f"vggt: {n_total} total surfels across {len(paths)} frames", flush=True)

    # ── Persist outputs ─────────────────────────────────────────────────
    np.savez(
        out_dir / "surfels.npz",
        xyz=surfels["xyz"],
        f_dc=surfels["f_dc"],
        opacity=surfels["opacity"],
        log_scale=surfels["log_scale"],
        quat=surfels["quat"],
        conf=surfels["conf"],
    )

    # Reconstruct RGB ∈ [0, 1] for the debug points.ply (decode f_dc).
    rgb_decoded = (surfels["f_dc"] * SH_C0 + 0.5).clip(0.0, 1.0)
    _save_points_ply(surfels["xyz"], rgb_decoded, surfels["conf"], out_dir / "points.ply")

    print(
        f"vggt: {len(paths)} frames -> cameras.json + points.ply + surfels.npz "
        f"({n_total} surfels)",
        flush=True,
    )
