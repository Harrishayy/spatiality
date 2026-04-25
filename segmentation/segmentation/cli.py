"""Segmentation CLI.

Default: stub (hand-crafted annotations) so `just smoke` works without GPU.
--real: SAM 3.1 masks -> DBSCAN clusters -> Claude Haiku VLM labels via
Pydantic AI Gateway, per plans/modules/03_segmentation.md.

Span names match the demo evidence table in 08_observability.md.
"""

from __future__ import annotations

import argparse
import json
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

# Default cluster color when SAM/VLM doesn't volunteer one.
DEFAULT_COLOR = "#9ca3af"


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
    parser.add_argument(
        "--real",
        action="store_true",
        help="Run real SAM + VLM pipeline. Default: stub.",
    )
    parser.add_argument("--keyframes", type=int, default=5)
    parser.add_argument(
        "--lift-mode",
        choices=["masks", "dbscan"],
        default="masks",
        help="masks: project SAM masks into 3D and merge by Jaccard (fast, default). "
        "dbscan: legacy DBSCAN-on-centers (slow on large splats).",
    )
    parser.add_argument("--eps", type=float, default=0.15, help="DBSCAN eps (dbscan mode only)")
    parser.add_argument("--min-samples", type=int, default=30, help="DBSCAN min samples (dbscan mode only)")
    parser.add_argument(
        "--jaccard-min",
        type=float,
        default=0.30,
        help="Mask-merge threshold (masks mode only)",
    )
    args = parser.parse_args()

    configure_logfire("segmentation")
    scene = Path(args.scene_dir) if args.scene_dir else _scene_dir(args.scene_id)
    manifest_path = scene / "manifest.json"

    manifest = Manifest.read(manifest_path)
    manifest.stages.segmentation.status = "running"
    manifest.write_atomic(manifest_path)

    if args.real:
        annotations, sam_dur, vlm_dur, backend, mask_count, cluster_count = _run_real(
            scene, args
        )
        backend_label = backend
    else:
        annotations, sam_dur, vlm_dur = _run_stub(scene, args)
        backend_label = "stub"
        mask_count = 0
        cluster_count = len(annotations.root)

    total = sam_dur + vlm_dur
    manifest = Manifest.read(manifest_path)
    manifest.stages.segmentation.status = "complete"
    manifest.stages.segmentation.duration_s = round(total, 4)
    manifest.stages.segmentation.object_count = len(annotations.root)
    manifest.stages.segmentation.method = backend_label
    manifest.stats.object_count = len(annotations.root)
    manifest.status = "ready"
    manifest.write_atomic(manifest_path)
    print(
        f"segmentation {backend_label} complete: {args.scene_id} "
        f"({total:.2f}s, {mask_count} masks -> {cluster_count} clusters -> "
        f"{len(annotations.root)} labeled)"
    )


def _run_stub(scene: Path, args: argparse.Namespace) -> tuple[AnnotationsFile, float, float]:
    with logfire.span(
        SPAN_SEGMENTATION_SAM3,
        scene_id=args.scene_id,
        keyframe_count=0,
        mask_count=0,
    ):
        t0 = time.perf_counter()
        sam_dur = time.perf_counter() - t0

    annotations = _stub_annotations()
    with logfire.span(
        SPAN_SEGMENTATION_VLM,
        scene_id=args.scene_id,
        cluster_count=len(annotations.root),
    ):
        t0 = time.perf_counter()
        annotations.write_atomic(scene / "annotations.json")
        vlm_dur = time.perf_counter() - t0
    return annotations, sam_dur, vlm_dur


def _run_real(
    scene: Path, args: argparse.Namespace
) -> tuple[AnnotationsFile, float, float, str, int, int]:
    # Imported lazily so `--stub` runs without these heavy deps installed.
    from . import sam as _sam
    from . import vlm as _vlm

    cameras = json.loads((scene / "cameras.json").read_text())
    keyframe_indices = _sam.pick_keyframes(cameras, n=args.keyframes)

    with logfire.span(
        SPAN_SEGMENTATION_SAM3,
        scene_id=args.scene_id,
        keyframe_count=len(keyframe_indices),
        mask_count=0,
    ) as span:
        t0 = time.perf_counter()
        masks, backend = _sam.run(scene, keyframe_indices)
        span.set_attribute("mask_count", len(masks))
        span.set_attribute("backend", backend)
        sam_dur = time.perf_counter() - t0

    if args.lift_mode == "masks":
        from . import lift_masks as _lift_masks

        clusters = _lift_masks.cluster_via_masks(
            scene, masks, jaccard_min=args.jaccard_min
        )
    else:
        from . import lift as _lift

        clusters = _lift.cluster(
            scene, masks, eps=args.eps, min_samples=args.min_samples
        )

    with logfire.span(
        SPAN_SEGMENTATION_VLM,
        scene_id=args.scene_id,
        cluster_count=len(clusters),
    ):
        t0 = time.perf_counter()
        labels = _vlm.label_clusters(scene, clusters)
        annotations = _to_annotations(clusters, labels)
        annotations.write_atomic(scene / "annotations.json")
        vlm_dur = time.perf_counter() - t0

    return annotations, sam_dur, vlm_dur, backend, len(masks), len(clusters)


def _to_annotations(clusters, labels) -> AnnotationsFile:
    out: list[Annotation] = []
    for c in clusters:
        lab = labels.get(c.id)
        out.append(
            Annotation(
                id=c.id,
                label=lab.label if lab else "unknown",
                centroid=tuple(float(v) for v in c.centroid),
                bbox=c.bbox_3d,
                color=DEFAULT_COLOR,
                confidence=lab.confidence if lab else 0.0,
                alternatives=lab.alternatives if lab else [],
                cluster_gaussian_indices=c.gaussian_indices,
            )
        )
    return AnnotationsFile(root=out)
