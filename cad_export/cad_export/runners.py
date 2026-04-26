"""E7 — Pluggable runners for the cad_export orchestrator.

Two seams in the orchestrator are environment-dependent:
  - **Mask runner**: turns a per-frame RGB image + projected 2D bbox into
    an alpha mask. Production = SAM 3.1 box-prompted (TODO(swap), see
    Sam3Runner stub below). Default = FlatMaskRunner (projected bbox as
    a flat rectangle); good enough for a square 1024² crop fed to TRELLIS.
  - **Generate runner**: produces a per-object .glb. Production = Modal
    `cad_export_object.map(payloads, return_exceptions=True)` for parallel
    H100 fan-out. Offline = LocalGenerateStub which fails every object so
    the orchestrator routes everything through the fallback (E5) path —
    useful for fixture-driven dev without TRELLIS weights.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol

import numpy as np


class MaskRunner(Protocol):
    """Produces an HxW bool mask for an object given image + 2D bbox prompt."""

    def mask_for_bbox(
        self,
        image_rgb: np.ndarray,        # (H, W, 3) uint8
        bbox_xyxy: np.ndarray,        # (4,) — x0, y0, x1, y1 in pixel coords
    ) -> np.ndarray:                  # (H, W) bool
        ...


class FlatMaskRunner:
    """Returns the projected bbox itself as a flat rectangular mask.

    No external dependencies — runs anywhere. The crop downstream is
    square-padded to 1024² so a flat rectangle vs. a tight SAM mask
    matters only at object silhouettes. For TRELLIS multi-view, the
    silhouette quality is a quality refinement, not a correctness gate.
    """

    def mask_for_bbox(self, image_rgb: np.ndarray, bbox_xyxy: np.ndarray) -> np.ndarray:
        H, W = image_rgb.shape[:2]
        x0, y0, x1, y1 = (int(round(v)) for v in bbox_xyxy)
        x0 = max(0, min(W, x0))
        x1 = max(0, min(W, x1))
        y0 = max(0, min(H, y0))
        y1 = max(0, min(H, y1))
        mask = np.zeros((H, W), dtype=bool)
        mask[y0:y1, x0:x1] = True
        return mask


class Sam3Runner:
    """TODO(swap): wrap the SAM 3.1 box-prompt API.

    The existing `segmentation/segmentation/sam.py` exposes only the
    text-prompted Sam3Processor. SAM 3.1 supports box prompts via the
    image predictor variant — slot it in here once the wrapper is added
    in segmentation/.

    Until then, FlatMaskRunner is the default. Quality-only swap.
    """

    def mask_for_bbox(self, image_rgb: np.ndarray, bbox_xyxy: np.ndarray) -> np.ndarray:
        raise NotImplementedError(
            "Sam3Runner is a TODO(swap) seam — segmentation/sam.py needs a "
            "box-prompted variant added before this can be wired up. Use "
            "FlatMaskRunner in the meantime."
        )


# ─── Generate runners ─────────────────────────────────────────────────────


@dataclass
class GenerateInput:
    obj_id: str
    view_dir: Path | None  # None when E2 produced no chosen views


@dataclass
class GenerateOutput:
    obj_id: str
    glb_path: Path | None
    success: bool
    failure_reason: str | None
    vertex_count: int = 0
    face_count: int = 0
    latency_ms: float = 0.0


class GenerateRunner(Protocol):
    """Run TRELLIS.2 across a batch of objects and return per-object results."""

    def run_batch(self, scene_id: str, inputs: Iterable[GenerateInput]) -> list[GenerateOutput]:
        ...


class LocalGenerateStub:
    """Offline stub that fails every object so the orchestrator routes them
    all through the E5 fallback path (Poisson on cluster point cloud).

    Used by the local CLI smoke test and by `verify_e7.py` so neither
    requires TRELLIS weights, GPU, or Modal connectivity.
    """

    def __init__(self, reason: str = "trellis_unavailable_local") -> None:
        self.reason = reason

    def run_batch(self, scene_id: str, inputs: Iterable[GenerateInput]) -> list[GenerateOutput]:
        return [
            GenerateOutput(obj_id=g.obj_id, glb_path=None, success=False, failure_reason=self.reason)
            for g in inputs
        ]
