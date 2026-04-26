"""E7 — I/O helpers: read scene inputs from artifacts/scenes/<scene_id>/.

splat.ply: INRIA-layout Gaussian splat. We need positions (x/y/z) plus the
rotation quaternion (rot_0..3 in WXYZ order) and log-scales (scale_0..2)
for the fallback module's normal derivation. Color/opacity are ignored.

cameras.json: list of {frame, extrinsic 4x4, intrinsic 3x3}.

annotations.json: list of Annotation per shared/schemas/annotations.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from plyfile import PlyData

from .object_views import CameraInfo


@dataclass
class SplatData:
    centers: np.ndarray          # (N, 3) float32 positions
    quat_wxyz: np.ndarray        # (N, 4) float32 — rot_0=w, rot_1=x, rot_2=y, rot_3=z
    log_scale: np.ndarray        # (N, 3) float32


def load_splat_full(path: Path) -> SplatData:
    """Read positions + quaternions + log-scales from an INRIA splat.ply.

    Mirrors the layout written by `inference/inference/splat.py`:
        x y z nx ny nz f_dc_0..2 opacity scale_0..2 rot_0..3
    where rot_* is a unit quaternion in WXYZ order.
    """
    ply = PlyData.read(str(path))
    v = ply["vertex"].data
    if v.size == 0:
        empty3 = np.zeros((0, 3), dtype=np.float32)
        empty4 = np.zeros((0, 4), dtype=np.float32)
        return SplatData(centers=empty3, quat_wxyz=empty4, log_scale=empty3)
    centers = np.stack([v["x"], v["y"], v["z"]], axis=1).astype(np.float32)
    quat_wxyz = np.stack([v["rot_0"], v["rot_1"], v["rot_2"], v["rot_3"]], axis=1).astype(np.float32)
    log_scale = np.stack([v["scale_0"], v["scale_1"], v["scale_2"]], axis=1).astype(np.float32)
    return SplatData(centers=centers, quat_wxyz=quat_wxyz, log_scale=log_scale)


def load_cameras(path: Path, *, default_width: int = 1024, default_height: int = 768) -> list[CameraInfo]:
    """Parse cameras.json into CameraInfo records.

    Width/height are inferred from the principal-point convention if absent
    (intrinsic[0,2] = cx ≈ W/2, intrinsic[1,2] = cy ≈ H/2). Falls back to
    `default_*` when the JSON entry doesn't carry image dimensions.
    """
    raw = json.loads(Path(path).read_text())
    out: list[CameraInfo] = []
    for entry in raw:
        K = np.asarray(entry["intrinsic"], dtype=np.float64)
        Rt = np.asarray(entry["extrinsic"], dtype=np.float64)
        if Rt.shape == (3, 4):
            T = np.eye(4)
            T[:3, :] = Rt
            Rt = T
        width = int(entry.get("width", round(2 * float(K[0, 2])) or default_width))
        height = int(entry.get("height", round(2 * float(K[1, 2])) or default_height))
        frame_id = str(entry.get("frame", entry.get("id", "")))
        out.append(CameraInfo(frame_id=frame_id, K=K, Rt=Rt, width=width, height=height))
    return out


def cameras_by_frame_id(cameras: list[CameraInfo]) -> dict[str, CameraInfo]:
    return {c.frame_id: c for c in cameras}
