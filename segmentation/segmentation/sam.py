"""SAM 3.1 grounded mask generation on keyframes.

Spec: plans/modules/03_segmentation.md.
- Pick keyframes evenly distributed by camera arc length (cameras.json).
- Run SAM 3.1 with a small list of generic text prompts per keyframe; collect
  all masks above the confidence threshold; per-frame IoU-dedup.

SAM 3.1 is text-grounded — to enumerate a scene unsupervised we issue several
complementary prompts (object / furniture / electronic device / small item /
container) and union the results. Single-prompt mode is preserved behind the
legacy SAM3_TEXT_PROMPT env var for backward compat.

Weights load from HF Hub on first call (gated repo, requires HF_TOKEN env var).

Env vars:
  SAM3_CHECKPOINT      — path to a local sam3 .pt; default: HF auto-fetch
  SAM3_TEXT_PROMPTS    — comma-separated prompts (default: 5-prompt list)
  SAM3_TEXT_PROMPT     — legacy single prompt; if set overrides SAM3_TEXT_PROMPTS
  SAM3_CONFIDENCE      — confidence threshold (default: 0.35)
  SAM3_DEDUP_IOU       — intra-frame dedup IoU threshold (default: 0.85)
  HF_TOKEN             — gated repo auth (required for first download only)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

SAM3_CHECKPOINT = os.environ.get("SAM3_CHECKPOINT")
SAM3_CONFIDENCE = float(os.environ.get("SAM3_CONFIDENCE", "0.35"))
SAM3_DEDUP_IOU = float(os.environ.get("SAM3_DEDUP_IOU", "0.85"))

_DEFAULT_PROMPTS = "object,furniture,electronic device,small item on a surface,container"


def _resolve_prompts() -> list[str]:
    """Single legacy prompt wins if explicitly set; otherwise the multi-prompt list."""
    legacy = os.environ.get("SAM3_TEXT_PROMPT")
    if legacy:
        return [legacy]
    raw = os.environ.get("SAM3_TEXT_PROMPTS", _DEFAULT_PROMPTS)
    return [p.strip() for p in raw.split(",") if p.strip()]


@dataclass
class Mask:
    frame_idx: int
    frame_name: str
    mask_id: int
    segmentation: np.ndarray  # bool HxW
    bbox: tuple[int, int, int, int]  # (x, y, w, h)
    area: int
    confidence: float
    source: str = "sam"  # "sam" or "vlm"
    prompt: str = ""  # SAM prompt that produced this mask, if source="sam"
    phrase: str = ""  # VLM phrase, if source="vlm"
    proposal_confidence: float = 0.0  # VLM proposer confidence, if source="vlm"


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
    state: dict, frame_idx: int, frame_name: str, prompt: str, mask_id_offset: int = 0
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
                mask_id=mask_id_offset + j,
                segmentation=seg,
                bbox=(x, y, w, h),
                area=int(seg.sum()),
                confidence=float(scores_t[j].item()),
                source="sam",
                prompt=prompt,
            )
        )
    return out


def _dedup_per_frame(masks: list[Mask], iou_threshold: float) -> tuple[list[Mask], int]:
    """Drop near-duplicate masks within one frame; keep higher-confidence one.

    Two masks are duplicates when their pixel IoU >= iou_threshold. O(N²) on
    the (typically <50) masks per frame; dwarfed by SAM inference cost.
    """
    if len(masks) < 2:
        return masks, 0
    order = sorted(range(len(masks)), key=lambda i: masks[i].confidence, reverse=True)
    keep = [True] * len(masks)
    dropped = 0
    for ai, a in enumerate(order):
        if not keep[a]:
            continue
        seg_a = masks[a].segmentation
        area_a = masks[a].area
        for b in order[ai + 1 :]:
            if not keep[b]:
                continue
            seg_b = masks[b].segmentation
            if seg_a.shape != seg_b.shape:
                continue
            inter = int(np.logical_and(seg_a, seg_b).sum())
            if inter == 0:
                continue
            union = area_a + masks[b].area - inter
            if union <= 0:
                continue
            iou = inter / union
            if iou >= iou_threshold:
                keep[b] = False
                dropped += 1
    return [m for m, k in zip(masks, keep) if k], dropped


def run(scene_dir: Path, keyframes: list[int]) -> tuple[list[Mask], str]:
    """Generate masks for each keyframe; return flat mask list + backend name ('sam3').

    Iterates the SAM3_TEXT_PROMPTS list per keyframe so a text-grounded model
    enumerates more than one category. Per-frame IoU dedup keeps near-duplicates
    out of the lift step.
    """
    import logfire
    import torch

    cameras = json.loads((scene_dir / "cameras.json").read_text())
    frame_dir = scene_dir / "frames"
    processor = build_generator()
    backend = "sam3"
    prompts = _resolve_prompts()

    device = _device()
    use_bf16 = device == "cuda" and torch.cuda.is_bf16_supported()
    autocast_ctx = (
        torch.autocast("cuda", dtype=torch.bfloat16)
        if use_bf16
        else torch.autocast("cpu", enabled=False)
    )

    masks: list[Mask] = []
    mask_count_per_prompt: dict[str, int] = {p: 0 for p in prompts}
    total_dedup_dropped = 0

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
            frame_masks: list[Mask] = []
            with logfire.span(
                "segmentation.sam3.keyframe",
                keyframe_idx=idx,
                frame_name=frame_path.name,
                backend=backend,
                prompt_count=len(prompts),
            ) as span:
                state = processor.set_image(img)
                mask_id_offset = 0
                for prompt in prompts:
                    state = processor.set_text_prompt(prompt, state)
                    prompt_masks = _state_to_masks(
                        state, idx, frame_path.name, prompt, mask_id_offset
                    )
                    mask_count_per_prompt[prompt] += len(prompt_masks)
                    mask_id_offset += len(prompt_masks)
                    frame_masks.extend(prompt_masks)
                # Within-frame near-duplicate suppression across prompts.
                deduped, dropped = _dedup_per_frame(frame_masks, SAM3_DEDUP_IOU)
                total_dedup_dropped += dropped
                span.set_attribute("mask_count_raw", len(frame_masks))
                span.set_attribute("mask_count", len(deduped))
                span.set_attribute("dedup_dropped", dropped)
            masks.extend(deduped)

    with logfire.span(
        "segmentation.sam3.summary",
        backend=backend,
        prompt_list=",".join(prompts),
        keyframe_count=len(keyframes),
        total_masks=len(masks),
        dedup_dropped=total_dedup_dropped,
    ) as span:
        for p, c in mask_count_per_prompt.items():
            span.set_attribute(f"mask_count[{p}]", c)

    return masks, backend
