"""Crop 4 source frames to 1024x1024 RGBA tight around the Stitch plushie.

Detects Stitch by HSV blue threshold, finds the largest connected blue
region, squares the bbox with margin, then crops + resizes to 1024.
Output: /tmp/trellis_smoke/views/{0,1,2,3}.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

SOURCE_FRAMES = [
    "/tmp/trellis_smoke/frames/0048.png",
    "/tmp/trellis_smoke/frames/0050.png",
    "/tmp/trellis_smoke/frames/0052.png",
    "/tmp/trellis_smoke/frames/0058.png",
]
OUT_DIR = Path("/tmp/trellis_smoke/views")
OUT_SIZE = 1024
MARGIN_FRAC = 0.12


def stitch_bbox(rgb: np.ndarray) -> tuple[int, int, int, int]:
    """Return (x0, y0, x1, y1) of the largest blue (Stitch) region.

    Stitch is saturated blue/teal — H ~ 180-220, S > 0.35, V > 0.25.
    """
    arr = rgb.astype(np.float32) / 255.0
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    mx = arr.max(axis=-1)
    mn = arr.min(axis=-1)
    v = mx
    s = np.where(mx > 0, (mx - mn) / np.where(mx > 0, mx, 1.0), 0.0)
    diff = mx - mn + 1e-8
    h = np.zeros_like(mx)
    mask_b = (mx == b) & (diff > 0)
    mask_g = (mx == g) & (diff > 0) & ~mask_b
    mask_r = (mx == r) & (diff > 0) & ~mask_b & ~mask_g
    h = np.where(mask_b, 60.0 * ((r - g) / diff) + 240.0, h)
    h = np.where(mask_g, 60.0 * ((b - r) / diff) + 120.0, h)
    h = np.where(mask_r, (60.0 * ((g - b) / diff)) % 360.0, h)

    blue = (h > 175) & (h < 230) & (s > 0.30) & (v > 0.18)
    if not blue.any():
        raise ValueError("no blue region detected")

    ys, xs = np.where(blue)
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def square_with_margin(
    bbox: tuple[int, int, int, int], W: int, H: int, margin_frac: float
) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = bbox
    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2
    side = max(x1 - x0, y1 - y0) * (1.0 + margin_frac)
    half = side / 2
    sx0 = int(round(cx - half))
    sy0 = int(round(cy - half))
    sx1 = int(round(cx + half))
    sy1 = int(round(cy + half))
    if sx0 < 0:
        sx1 -= sx0
        sx0 = 0
    if sy0 < 0:
        sy1 -= sy0
        sy0 = 0
    if sx1 > W:
        sx0 -= sx1 - W
        sx1 = W
    if sy1 > H:
        sy0 -= sy1 - H
        sy1 = H
    sx0 = max(0, sx0)
    sy0 = max(0, sy0)
    sx1 = min(W, sx1)
    sy1 = min(H, sy1)
    return sx0, sy0, sx1, sy1


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for i, frame_path in enumerate(SOURCE_FRAMES):
        img = Image.open(frame_path).convert("RGB")
        W, H = img.size
        rgb = np.array(img)
        bbox = stitch_bbox(rgb)
        sq = square_with_margin(bbox, W, H, MARGIN_FRAC)
        crop = img.crop(sq).resize((OUT_SIZE, OUT_SIZE), Image.LANCZOS)
        crop_rgba = crop.convert("RGBA")
        out = OUT_DIR / f"{i}.png"
        crop_rgba.save(out)
        print(f"{frame_path} -> {out}  raw_bbox={bbox} square_bbox={sq}")
    print(f"\nWrote {len(SOURCE_FRAMES)} crops to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
