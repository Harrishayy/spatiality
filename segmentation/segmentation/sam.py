"""SAM 3.1 grounded mask generation on keyframes.

Spec: plans/modules/03_segmentation.md.
- Pick 4-6 keyframes evenly distributed by camera arc length (cameras.json).
- Run SAM 3.1 with a generic text prompt ("object") per keyframe; collect masks.

SAM 3.1 is text-grounded (no AutomaticMaskGenerator like SAM 2). To enumerate
objects unsupervised, we prompt with a generic catch-all phrase and let SAM 3.1
return all matching boxes + masks above the confidence threshold. The prompt
is overridable via SAM3_TEXT_PROMPT for scenes that need a tighter target.

Weights load from HF Hub on first call (gated repo, requires HF_TOKEN env var) —
SAM 3.1's `build_sam3_image_model(load_from_HF=True)` handles the download
itself, so no manual snapshot pre-fetch is needed.

Env vars:
  SAM3_CHECKPOINT      — path to a local sam3 .pt; default: HF auto-fetch
  SAM3_TEXT_PROMPT     — text prompt for enumeration (default: "object")
  SAM3_CONFIDENCE      — confidence threshold (default: 0.5)
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

SAM3_CHECKPOINT = os.environ.get("SAM3_CHECKPOINT")
SAM3_TEXT_PROMPT = os.environ.get("SAM3_TEXT_PROMPT", "object")
SAM3_CONFIDENCE = float(os.environ.get("SAM3_CONFIDENCE", "0.5"))


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


def _device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _build_sam3():
    """Build the grounded image model + processor (HF auto-fetches weights)."""
    import sam3
    from sam3 import build_sam3_image_model
    from sam3.model.sam3_image_processor import Sam3Processor

    bpe_path = os.path.join(
        os.path.dirname(sam3.__file__), "assets", "bpe_simple_vocab_16e6.txt.gz"
    )
    model = build_sam3_image_model(
        bpe_path=bpe_path,
        device=_device(),
        checkpoint_path=SAM3_CHECKPOINT,  # None → load_from_HF kicks in
        load_from_HF=SAM3_CHECKPOINT is None,
    )
    return Sam3Processor(model, confidence_threshold=SAM3_CONFIDENCE)


def build_generator() -> Any:
    """Build a SAM 3.1 grounded mask processor. Raises if SAM 3.1 isn't available."""
    return _build_sam3()


def _state_to_masks(
    state: dict, frame_idx: int, frame_name: str
) -> list[Mask]:
    """Convert a Sam3Processor state dict (after grounding) to our Mask records."""
    if "masks" not in state or "boxes" not in state or "scores" not in state:
        return []
    # Tensors live on device — pull to CPU for numpy conversion.
    masks_t = state["masks"].cpu()  # (N, 1, H, W) bool
    boxes_t = state["boxes"].cpu()  # (N, 4)  in [x0, y0, x1, y1] pixel coords
    scores_t = state["scores"].cpu()  # (N,)
    out: list[Mask] = []
    for j in range(masks_t.shape[0]):
        seg = masks_t[j, 0].numpy().astype(bool)
        x0, y0, x1, y1 = (float(v) for v in boxes_t[j].tolist())
        x, y = int(round(x0)), int(round(y0))
        w, h = int(round(x1 - x0)), int(round(y1 - y0))
        if w <= 0 or h <= 0:
            continue
        out.append(
            Mask(
                frame_idx=frame_idx,
                frame_name=frame_name,
                mask_id=j,
                segmentation=seg,
                bbox=(x, y, w, h),
                area=int(seg.sum()),
                confidence=float(scores_t[j].item()),
            )
        )
    return out


def run(scene_dir: Path, keyframes: list[int]) -> tuple[list[Mask], str]:
    """Generate masks for each keyframe; return flat mask list + backend name ('sam3')."""
    import logfire
    import torch

    cameras = json.loads((scene_dir / "cameras.json").read_text())
    frame_dir = scene_dir / "frames"
    processor = build_generator()
    backend = "sam3"

    # SAM 3.1 weights load in bfloat16 on CUDA — image inputs come in fp32 from
    # PIL, which trips `mat1/mat2 dtype mismatch` deep in the ViT. The official
    # examples wrap inference in autocast(bfloat16) + inference_mode. We mirror
    # that here. On CPU we fall back to fp32 (autocast is a no-op).
    device = _device()
    use_bf16 = device == "cuda" and torch.cuda.is_bf16_supported()
    autocast_ctx = (
        torch.autocast("cuda", dtype=torch.bfloat16)
        if use_bf16
        else torch.autocast("cpu", enabled=False)
    )

    masks: list[Mask] = []
    with autocast_ctx, torch.inference_mode():
        for idx in keyframes:
            cam = cameras[idx]
            frame_path = frame_dir / cam["frame"]
            if not frame_path.exists():
                sorted_frames = sorted(frame_dir.glob("*.png")) + sorted(frame_dir.glob("*.jpg"))
                if idx >= len(sorted_frames):
                    continue
                frame_path = sorted_frames[idx]

            img = Image.open(frame_path).convert("RGB")
            with logfire.span(
                "segmentation.sam3.keyframe",
                keyframe_idx=idx,
                frame_name=frame_path.name,
                backend=backend,
                text_prompt=SAM3_TEXT_PROMPT,
            ) as span:
                state = processor.set_image(img)
                state = processor.set_text_prompt(SAM3_TEXT_PROMPT, state)
                frame_masks = _state_to_masks(state, idx, frame_path.name)
                span.set_attribute("mask_count", len(frame_masks))
            masks.extend(frame_masks)
    return masks, backend
