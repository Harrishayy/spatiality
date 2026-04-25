"""Frame selection shared by both inference backends.

Both `poses.py` (vanilla VGGT) and `fastvggt.py` (FastVGGT) need the same
pre-filter logic: subsample by stride, drop the blurriest frames by
Laplacian variance, then cap to a budget. Each backend passes its own
env-var-driven defaults so they can have different frame budgets without
duplicating the algorithm.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

# JPEG decode + Laplacian are CPU-bound but cv2 releases the GIL, so a
# thread pool gives near-linear speedup on multi-core boxes. Modal containers
# are sized at cpu=4.0 (see modal_app.py); 8 worker threads still helps via
# overlap between disk read and decode.
_FRAME_SELECT_WORKERS = int(
    os.environ.get("FRAME_SELECT_WORKERS", str(min(8, (os.cpu_count() or 4))))
)


def list_image_paths(frames_dir: Path) -> list[Path]:
    paths = sorted(p for p in frames_dir.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
    if not paths:
        raise FileNotFoundError(f"no frames in {frames_dir}")
    return paths


def laplacian_variance(path: Path) -> float:
    """Cheap motion-blur proxy: variance of the Laplacian of a small grayscale
    crop of the frame. Lower = blurrier."""
    import cv2

    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0.0
    h, w = img.shape
    scale = 256.0 / max(h, w)
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(img, cv2.CV_64F).var())


def _laplacian_variance_parallel(paths: list[Path]) -> np.ndarray:
    """Parallel Laplacian scoring across a thread pool. cv2 releases the GIL
    during imread + resize + Laplacian, so threading gives a ~4× speedup on
    a 4-core container with no per-task setup cost."""
    if not paths:
        return np.empty(0, dtype=np.float64)
    if _FRAME_SELECT_WORKERS <= 1 or len(paths) <= 1:
        return np.array([laplacian_variance(p) for p in paths], dtype=np.float64)
    with ThreadPoolExecutor(max_workers=_FRAME_SELECT_WORKERS) as ex:
        # `map` preserves input order — critical so scores align with `paths`.
        return np.fromiter(ex.map(laplacian_variance, paths), dtype=np.float64, count=len(paths))


def select_frames(
    frames_dir: Path,
    *,
    frames_max: int,
    frames_min: int,
    blur_drop_pct: float,
    log_prefix: str = "vggt",
) -> list[Path]:
    """Pre-filter: stride down to ~2× target → drop bottom blur_drop_pct by
    Laplacian variance → even-spacing cap at frames_max. Floor at frames_min.
    """
    paths = list_image_paths(frames_dir)
    n = len(paths)

    if n > frames_max * 2:
        stride = max(1, n // (frames_max * 2))
        paths = paths[::stride]
        n = len(paths)

    if n > frames_min:
        scores = _laplacian_variance_parallel(paths)
        keep_count = max(frames_min, int(round(n * (1.0 - blur_drop_pct))))
        if keep_count < n:
            order = np.argsort(scores)[::-1]
            keep_idx = sorted(order[:keep_count].tolist())
            paths = [paths[i] for i in keep_idx]

    if len(paths) > frames_max:
        idx = np.linspace(0, len(paths) - 1, frames_max).round().astype(int)
        paths = [paths[i] for i in idx.tolist()]

    print(f"{log_prefix}: selected {len(paths)} / {n} frames", flush=True)
    return paths
