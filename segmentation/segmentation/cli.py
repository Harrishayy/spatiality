"""Segmentation stub — flips segmentation stage, writes hand-crafted annotations.

TODO(swap): Session C replaces with SAM 3.1 masks + Claude Haiku VLM labeling
(plans/modules/03_segmentation.md).
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import logfire

from shared.observability import (
    SPAN_SEGMENTATION_SAM3,
    SPAN_SEGMENTATION_VLM,
    configure_logfire,
)
from shared.paths import scene_dir as _scene_dir
from shared.schemas import Annotation, AnnotationsFile, Manifest


def _stub_annotations() -> AnnotationsFile:
    return AnnotationsFile(
        root=[
            Annotation(
                id="obj_001",
                label="MacBook Air (M3)",
                centroid=(0.42, 0.91, -1.23),
                bbox=((0.30, 0.85, -1.40), (0.55, 0.95, -1.10)),
                color="#a8b2bd",
                confidence=0.91,
                alternatives=["laptop", "MacBook"],
                cluster_gaussian_indices=[12, 45, 78, 102],
            ),
            Annotation(
                id="obj_002",
                label="stack of books",
                centroid=(-0.31, 0.88, -1.50),
                bbox=((-0.42, 0.80, -1.62), (-0.20, 0.96, -1.38)),
                color="#7a5a3a",
                confidence=0.83,
                alternatives=["books", "pile of books"],
                cluster_gaussian_indices=[201, 202, 215, 233, 244],
            ),
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="segmentation")
    parser.add_argument("--scene-id", required=True)
    parser.add_argument("--scene-dir", default=None, help="Override resolved scene dir")
    args = parser.parse_args()

    configure_logfire("segmentation")
    scene = Path(args.scene_dir) if args.scene_dir else _scene_dir(args.scene_id)
    manifest_path = scene / "manifest.json"

    manifest = Manifest.read(manifest_path)
    manifest.stages.segmentation.status = "running"
    manifest.write_atomic(manifest_path)

    with logfire.span(
        SPAN_SEGMENTATION_SAM3,
        scene_id=args.scene_id,
        keyframe_count=0,
        mask_count=0,
    ):
        t0 = time.perf_counter()
        # TODO(swap): SAM 3.1 mask generation per keyframe.
        sam_dur = time.perf_counter() - t0

    annotations = _stub_annotations()
    with logfire.span(
        SPAN_SEGMENTATION_VLM,
        scene_id=args.scene_id,
        cluster_count=len(annotations.root),
    ):
        t0 = time.perf_counter()
        # TODO(swap): Claude Haiku VLM labeling per cluster.
        annotations.write_atomic(scene / "annotations.json")
        vlm_dur = time.perf_counter() - t0

    total = sam_dur + vlm_dur
    manifest = Manifest.read(manifest_path)
    manifest.stages.segmentation.status = "complete"
    manifest.stages.segmentation.duration_s = round(total, 4)
    manifest.stages.segmentation.object_count = len(annotations.root)
    manifest.stats.object_count = len(annotations.root)
    manifest.status = "ready"
    manifest.write_atomic(manifest_path)
    print(f"segmentation stub complete: {args.scene_id} ({total:.3f}s, {len(annotations.root)} objects)")
