"""SAM 3.1 automatic mask generation on keyframes.

Spec: plans/modules/03_segmentation.md.
- Pick 4-6 keyframes evenly distributed by camera angle (cameras.json).
- Run SAM 3.1 in automatic mode per keyframe; collect mask dicts.

SAM 3.1 only — no fallback to SAM 2 or any other version. Lazy-downloads weights
from HF Hub the first time it's invoked (gated repo, requires HF_TOKEN env var).

Env vars:
  SAM3_WEIGHTS         — path to a local sam3 .pt; if missing, fetched from HF
  SAM3_CONFIG          — config name passed to build_sam3 (default: "sam3_hiera_l.yaml")
  SAM3_HF_REPO         — HF repo id with weights (default: "facebook/sam3.1")
  SAM3_SNAPSHOT_DIR    — where to materialize the HF snapshot
                         (default: same dir as SAM3_WEIGHTS, or /tmp/sam3-snapshot)
  HF_TOKEN             — gated repo auth (required for first download only)
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
SAM3_HF_REPO = os.environ.get("SAM3_HF_REPO", "facebook/sam3.1")
SAM3_SNAPSHOT_DIR = os.environ.get("SAM3_SNAPSHOT_DIR")


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


def _ensure_weights() -> str:
    """Return a usable path to sam3 weights, downloading from HF Hub if needed."""
    if SAM3_WEIGHTS and Path(SAM3_WEIGHTS).exists():
        return SAM3_WEIGHTS

    # Fall back to an HF snapshot; pulls the gated repo on first call.
    from huggingface_hub import snapshot_download

    target = Path(SAM3_SNAPSHOT_DIR) if SAM3_SNAPSHOT_DIR else (
        Path(SAM3_WEIGHTS).parent / "sam3-snapshot" if SAM3_WEIGHTS else Path("/tmp/sam3-snapshot")
    )
    target.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=SAM3_HF_REPO, local_dir=str(target), token=os.environ.get("HF_TOKEN"))

    # Find the weight file inside the snapshot. Prefer .pt over .safetensors over .bin.
    for ext in (".pt", ".pth", ".safetensors", ".bin"):
        hits = sorted(target.rglob(f"*{ext}"))
        if hits:
            return str(hits[0])
    raise RuntimeError(f"no weight file found in HF snapshot at {target}")


def _build_sam3():
    from sam3.build_sam import build_sam3  # type: ignore
    from sam3.automatic_mask_generator import SAM3AutomaticMaskGenerator  # type: ignore

    weights_path = _ensure_weights()
    sam = build_sam3(SAM3_CONFIG, weights_path, device=_device())
    return SAM3AutomaticMaskGenerator(sam)


def _device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def build_generator() -> Any:
    """Build a SAM 3.1 automatic mask generator. Raises if SAM 3.1 isn't available."""
    return _build_sam3()


def run(scene_dir: Path, keyframes: list[int]) -> tuple[list[Mask], str]:
    """Generate masks for each keyframe; return flat mask list + backend name ('sam3')."""
    import logfire

    cameras = json.loads((scene_dir / "cameras.json").read_text())
    frame_dir = scene_dir / "frames"
    generator = build_generator()
    backend = "sam3"

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
        with logfire.span(
            "segmentation.sam3.keyframe",
            keyframe_idx=idx,
            frame_name=frame_path.name,
            backend=backend,
        ) as span:
            raw = generator.generate(img)
            span.set_attribute("mask_count", len(raw))
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
