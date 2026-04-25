"""Read Gaussian centers from a 3DGRUT-produced splat.ply.

3DGRUT writes one PLY vertex per Gaussian, with x/y/z (center) and many
extra properties (color SH, opacity, scale, rotation). For segmentation
clustering we only need centers.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from plyfile import PlyData


def load_centers(path: Path) -> np.ndarray:
    """Return Gaussian centers as float32 (N, 3). Empty array if no vertices."""
    ply = PlyData.read(str(path))
    if "vertex" not in ply:
        return np.zeros((0, 3), dtype=np.float32)
    v = ply["vertex"].data
    if v.size == 0:
        return np.zeros((0, 3), dtype=np.float32)
    return np.stack([v["x"], v["y"], v["z"]], axis=1).astype(np.float32)
