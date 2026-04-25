"""SAM 3.1 automatic mask generation on keyframes.

Spec: plans/modules/03_segmentation.md.
- Pick 4-6 keyframes evenly distributed by camera angle (cameras.json).
- Run SAM 3.1 in automatic mode per keyframe; collect mask dicts.

Falls back to SAM 2 if SAM 3.1 isn't installed (per "failure paths" in spec).
Both packages expose the same automatic-mask-generator shape:
  generate(np.ndarray HxWx3) -> [{segmentation: bool HxW, bbox: [x,y,w,h],
                                   area: int, predicted_iou: float, ...}, ...]

Env vars:
  SAM3_WEIGHTS  — path to sam3 .pt
  SAM3_CONFIG   — config name, e.g. "sam3_hiera_l.yaml" (default)
  SAM2_WEIGHTS  — path to sam2 .pt (used only if sam3 unavailable)
  SAM2_CONFIG   — config name, e.g. "sam2_hiera_l.yaml" (default)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

SAM3_WEIGHTS = os.environ.get("SAM3_WEIGHTS")
SAM3_CONFIG = os.environ.get("SAM3_CONFIG", "sam3_hiera_l.yaml")
SAM2_WEIGHTS = os.environ.get("SAM2_WEIGHTS")
SAM2_CONFIG = os.environ.get("SAM2_CONFIG", "sam2_hiera_l.yaml")


@dataclass
class Mask:
    frame_idx: int
    frame_name: str
    mask_id: int
    segmentation: np.ndarray  # bool HxW
    bbox: tuple[int, int, int, int]  # (x, y, w, h)
    area: int
    confidence: float


def pick_keyframes(cameras: list[dict], n: int = 5) -> list[int]:
    """Pick `n` keyframe indices evenly spaced by camera position arc length.

    Falls back to evenly-spaced-by-index if extrinsic parsing fails.
    """
    total = len(cameras)
    if total == 0:
        return []
    if total <= n:
        return list(range(total))

    try:
        positions = np.array(
            [np.array(c["extrinsic"], dtype=np.float64)[:3, 3] for c in cameras]
        )  # (T, 3)
        diffs = np.linalg.norm(np.diff(positions, axis=0), axis=1)
        cum = np.concatenate([[0.0], np.cumsum(diffs)])
        targets = np.linspace(0, cum[-1], n)
        return [int(np.argmin(np.abs(cum - t))) for t in targets]
    except Exception:
        return [int(round(i * (total - 1) / (n - 1))) for i in range(n)]


def _build_sam3():
    from sam3.build_sam import build_sam3  # type: ignore
    from sam3.automatic_mask_generator import SAM3AutomaticMaskGenerator  # type: ignore

    if not SAM3_WEIGHTS:
        raise RuntimeError("SAM3_WEIGHTS env var not set")
    sam = build_sam3(SAM3_CONFIG, SAM3_WEIGHTS, device=_device())
    return SAM3AutomaticMaskGenerator(sam), "sam3"


def _build_sam2():
    from sam2.build_sam import build_sam2  # type: ignore
    from sam2.automatic_mask_generator import SAM2AutomaticMaskGenerator  # type: ignore

    if not SAM2_WEIGHTS:
        raise RuntimeError("SAM2_WEIGHTS env var not set")
    sam = build_sam2(SAM2_CONFIG, SAM2_WEIGHTS, device=_device())
    return SAM2AutomaticMaskGenerator(sam), "sam2"


def _device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def build_generator() -> tuple[Any, str]:
    """Try SAM 3.1, fall back to SAM 2 (per spec failure paths)."""
    last_err: Exception | None = None
    for builder in (_build_sam3, _build_sam2):
        try:
            return builder()
        except Exception as e:
            last_err = e
    raise RuntimeError(f"no segmentation backend available: {last_err}")


def run(scene_dir: Path, keyframes: list[int]) -> tuple[list[Mask], str]:
    """Generate masks for each keyframe; return flat mask list + backend name."""
    cameras = json.loads((scene_dir / "cameras.json").read_text())
    frame_dir = scene_dir / "frames"
    generator, backend = build_generator()

    masks: list[Mask] = []
    for idx in keyframes:
        cam = cameras[idx]
        frame_path = frame_dir / cam["frame"]
        if not frame_path.exists():
            # cameras.json frame name might differ from frames/ files; resort by index.
            sorted_frames = sorted(frame_dir.glob("*.png")) + sorted(frame_dir.glob("*.jpg"))
            if idx >= len(sorted_frames):
                continue
            frame_path = sorted_frames[idx]

        img = np.array(Image.open(frame_path).convert("RGB"))
        raw = generator.generate(img)
        for j, m in enumerate(raw):
            x, y, w, h = (int(v) for v in m["bbox"])
            masks.append(
                Mask(
                    frame_idx=idx,
                    frame_name=frame_path.name,
                    mask_id=j,
                    segmentation=m["segmentation"].astype(bool),
                    bbox=(x, y, w, h),
                    area=int(m.get("area", int(m["segmentation"].sum()))),
                    confidence=float(m.get("predicted_iou", m.get("stability_score", 0.0))),
                )
            )
    return masks, backend
