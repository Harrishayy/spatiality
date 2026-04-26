"""Voxel-downsample VGGT surfels into an INRIA-layout splat PLY.

Pipeline shape:
  poses.py → surfels.npz (per-pixel anisotropic Gaussians from VGGT depth)
  splat.py → splat.ply   (voxel-downsampled, INRIA-format binary PLY)

The previous gsplat per-scene training has been removed entirely. Surfels
synthesised from VGGT's depth + camera heads are already aligned to scene
surfaces — they just need de-duplication where multiple input frames see
the same surface point. Voxel downsample at ~0.5% of scene-diagonal does
that in <100 ms on CPU at 8M points (NumPy-only, no Open3D dep).
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

# Voxel size as a fraction of scene diagonal. Smaller = denser cloud, finer
# detail, more GPU cost in the viewer. 0.005 is the perf knee for the
# Spark renderer on a laptop GPU at MAX_SPLATS=1.5M.
VGGT_VOXEL_SIZE_FRAC = float(os.environ.get("VGGT_VOXEL_SIZE_FRAC", "0.005"))

# Hard floor — below this, surfel synthesis has gone wrong upstream.
MIN_SURFELS = 1000


# ── Voxel downsample (NumPy, no Open3D) ─────────────────────────────────
def _voxel_downsample(
    xyz: np.ndarray,        # (N, 3)
    conf: np.ndarray,       # (N,)
    voxel_size: float,
) -> np.ndarray:
    """Group points by voxel; return indices of the highest-confidence point
    in each voxel. Fully vectorised — uses a lexsort trick: sort by
    (voxel_hash, -conf) so the first element of each group is its argmax,
    then the unique-keys boundary mask gives us those representatives in one
    pass. ~100× faster than a Python per-group argmax loop at 2 M+ voxels.
    """
    keys = np.floor(xyz / voxel_size).astype(np.int64)
    # Pack (kx, ky, kz) into a single int64 hash. We allow per-axis up to ~21
    # bits which is plenty for any reasonable scene at 0.005 fraction.
    SHIFT = 21
    MASK = (1 << SHIFT) - 1
    h = ((keys[:, 0] & MASK) << (2 * SHIFT)) \
        | ((keys[:, 1] & MASK) << SHIFT) \
        | (keys[:, 2] & MASK)

    # lexsort orders by the LAST key first → primary key h ascending,
    # secondary key conf descending (via -conf). Within each h-group the
    # highest-conf point now sits at the group's first position.
    order = np.lexsort((-conf, h))
    h_sorted = h[order]

    # Mark the first index of every new group: those are the representatives
    # we want to keep (one per voxel, max-conf).
    diff = np.empty(h_sorted.shape, dtype=bool)
    diff[0] = True
    diff[1:] = h_sorted[1:] != h_sorted[:-1]
    return order[diff]


# ── Output: INRIA-layout PLY ────────────────────────────────────────────
def _export_inria_ply(
    out_ply: Path,
    xyz: np.ndarray,         # (N, 3)
    f_dc: np.ndarray,        # (N, 3)
    opacity: np.ndarray,     # (N,)
    log_scale: np.ndarray,   # (N, 3)
    quat: np.ndarray,        # (N, 4) wxyz
) -> int:
    """Write the standard INRIA 3DGS layout: x y z nx ny nz f_dc_0..2 opacity
    scale_0..2 rot_0..3 (binary little-endian float32). Web viewer
    (web/app/components/SplatViewer.tsx) decodes this layout natively."""
    n = xyz.shape[0]
    # Normalise quaternions defensively — surfel synth in poses.py already
    # does this but voxel-downsample doesn't preserve the constraint.
    q = quat.astype(np.float32)
    q /= np.linalg.norm(q, axis=1, keepdims=True) + 1e-9

    rows = np.empty((n, 17), dtype=np.float32)
    rows[:, 0:3] = xyz.astype(np.float32)
    rows[:, 3:6] = 0.0  # nx ny nz placeholders — Spark ignores these.
    rows[:, 6:9] = f_dc.astype(np.float32)
    rows[:, 9] = opacity.astype(np.float32)
    rows[:, 10:13] = log_scale.astype(np.float32)
    rows[:, 13:17] = q  # wxyz

    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {n}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property float nx\nproperty float ny\nproperty float nz\n"
        "property float f_dc_0\nproperty float f_dc_1\nproperty float f_dc_2\n"
        "property float opacity\n"
        "property float scale_0\nproperty float scale_1\nproperty float scale_2\n"
        "property float rot_0\nproperty float rot_1\nproperty float rot_2\nproperty float rot_3\n"
        "end_header\n"
    ).encode()
    with out_ply.open("wb") as f:
        f.write(header)
        f.write(rows.tobytes(order="C"))
    return n


# ── Public entry point ──────────────────────────────────────────────────
def run(
    frames_dir: Path,
    cameras_json: Path,
    out_ply: Path,
    scene_id: str | None = None,
) -> dict:
    """Voxel-downsample the surfels emitted by poses.py and write splat.ply.
    Returns `{"gaussian_count": int}`.

    Raises (no fallback) on:
      - missing surfels.npz (poses stage probably failed)
      - degenerate cloud (< MIN_SURFELS surfels)

    The frames_dir + cameras_json args are kept for parity with the call-site
    in cli.py but are unused — all the per-pixel work happened upstream.
    """
    surfels_path = cameras_json.parent / "surfels.npz"
    if not surfels_path.exists():
        raise FileNotFoundError(
            f"splat: surfels.npz missing at {surfels_path} — "
            "VGGT poses stage probably failed (check stages.poses.error in manifest)"
        )

    data = np.load(surfels_path)
    xyz = data["xyz"]
    f_dc = data["f_dc"]
    opacity = data["opacity"]
    log_scale = data["log_scale"]
    quat = data["quat"]
    conf = data["conf"]

    n_in = xyz.shape[0]
    if n_in < MIN_SURFELS:
        raise RuntimeError(
            f"splat: surfel cloud too small ({n_in} pts) — "
            "VGGT depth gates probably too strict (lower VGGT_DEPTH_CONF_MIN)"
        )

    # Scene diagonal sets the voxel size. Use 95th-percentile bounding-box
    # extent rather than min/max to ignore the long tail of low-confidence
    # outliers (which voxel-downsample would otherwise dilute against).
    p_lo = np.percentile(xyz, 2.5, axis=0)
    p_hi = np.percentile(xyz, 97.5, axis=0)
    diag = float(np.linalg.norm(p_hi - p_lo))
    voxel_size = max(VGGT_VOXEL_SIZE_FRAC * diag, 1e-4)

    keep = _voxel_downsample(xyz, conf, voxel_size)
    print(
        f"splat: {n_in} surfels → {keep.shape[0]} after voxel downsample "
        f"(voxel={voxel_size:.4f}, scene_diag={diag:.3f})",
        flush=True,
    )

    n_out = _export_inria_ply(
        out_ply,
        xyz=xyz[keep],
        f_dc=f_dc[keep],
        opacity=opacity[keep],
        log_scale=log_scale[keep],
        quat=quat[keep],
    )
    print(f"splat: wrote {n_out} gaussians -> {out_ply}", flush=True)

    return {"gaussian_count": n_out}
