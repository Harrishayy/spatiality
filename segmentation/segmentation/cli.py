"""Segmentation CLI.

Default: stub (hand-crafted annotations) so `just smoke` works without GPU.
--real: VLM proposer + SAM 3.1 masks (parallel) -> Jaccard-merged 3D clusters
-> Claude Haiku VLM labeler.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import logfire

from shared.observability import (
    SPAN_SEGMENTATION_SAM3,
    SPAN_SEGMENTATION_VLM,
    SPAN_SEGMENTATION_VLM_PROPOSAL,
    attach_payload,
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
                # TODO(swap): real frame names from the cluster come from
                # lift_masks; stubs hard-code the first two so chat demos work.
                frame_ids=["frame_0001.jpg", "frame_0007.jpg"],
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
                frame_ids=["frame_0003.jpg", "frame_0009.jpg"],  # TODO(swap)
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
    parser.add_argument("--keyframes", type=int, default=12)
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
    parser.add_argument(
        "--no-vlm-proposals",
        action="store_true",
        help="Disable the parallel VLM proposer (Source A). Falls back to SAM-only.",
    )
    parser.add_argument(
        "--no-sam",
        action="store_true",
        help="Disable SAM 3.1 (Source B). Falls back to VLM-proposals-only.",
    )
    args = parser.parse_args()
    if args.no_vlm_proposals and args.no_sam:
        parser.error("--no-vlm-proposals and --no-sam together leave no annotation source")

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

    # Build the wireframe artifact (viewer's Wireframe view mode). Done
    # post-annotations so the per-object dense-point sets can be derived
    # from each annotation's cluster_gaussian_indices. Best-effort: a
    # missing points.ply just skips the artifact.
    try:
        from . import wireframe as _wireframe

        _wireframe.build_wireframe(scene, args.scene_id)
    except Exception as e:  # noqa: BLE001 — telemetry-only, do not fail the pipeline
        logfire.warn(
            "wireframe build failed",
            scene_id=args.scene_id,
            error=str(e)[:200],
        )

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


async def _gather_sources(
    scene: Path, keyframe_indices: list[int], args: argparse.Namespace
):
    """Run VLM proposer first, then SAM (auto-prompt + box-prompt) using its bboxes.

    Old approach: SAM auto-prompt and VLM proposer ran in parallel; VLM
    bboxes became RECTANGULAR masks via proposals_to_masks — those rectangles
    polluted clusters with whatever Gaussians shared the bbox area.

    New approach: VLM bboxes become geometric prompts to SAM 3.1, which
    returns the TIGHT pixel mask of the actual object inside the bbox (with
    SAM's built-in presence-token rejection for empty / hallucinated boxes).
    Phrase rides along on the resulting Mask for downstream labeling.
    Latency cost: VLM proposer (~1–3 s, fully cached on re-runs) added to
    the critical path before SAM.

    Returns (sam_masks, sam_backend, vlm_proposals).
    """
    from . import sam as _sam

    if args.no_vlm_proposals:
        vlm_proposals = []
    else:
        from . import proposer as _proposer

        vlm_proposals = await _wrap_vlm_proposals(
            _proposer.propose(scene, keyframe_indices, scene_id=args.scene_id),
            scene_id=args.scene_id,
        )

    if args.no_sam:
        return [], "skipped", vlm_proposals

    # Group proposals per frame for SAM box-prompting. Dedup phrases per
    # frame (if VLM named the same object two ways in one image, one box
    # is enough).
    proposals_by_frame: dict[str, list[tuple[str, tuple[float, float, float, float], float]]] = {}
    for p in vlm_proposals:
        bucket = proposals_by_frame.setdefault(p.frame_name, [])
        if any(existing == p.phrase for existing, _, _ in bucket):
            continue
        bucket.append((p.phrase, tuple(p.bbox_norm), float(p.confidence)))

    sam_masks, sam_backend = await asyncio.to_thread(
        _sam.run, scene, keyframe_indices, proposals_by_frame, args.scene_id
    )
    return sam_masks, sam_backend, vlm_proposals


async def _wrap_vlm_proposals(coro, scene_id: str = ""):
    """Logfire span around the proposer + tolerant return on failure."""
    with logfire.span(SPAN_SEGMENTATION_VLM_PROPOSAL, scene_id=scene_id) as span:
        try:
            proposals = await coro
        except Exception as e:
            span.set_attribute("error", str(e)[:200])
            return []
        span.set_attribute("proposal_count", len(proposals))
        return proposals


def _run_real(
    scene: Path, args: argparse.Namespace
) -> tuple[AnnotationsFile, float, float, str, int, int]:
    # Imported lazily so `--stub` runs without these heavy deps installed.
    from . import sam as _sam
    from . import vlm as _vlm

    cameras = json.loads((scene / "cameras.json").read_text())
    keyframe_indices = _sam.pick_keyframes(cameras, n=args.keyframes)

    t_sources_start = time.perf_counter()
    sam_masks, backend, vlm_proposals = asyncio.run(
        _gather_sources(scene, keyframe_indices, args)
    )
    sources_dur = time.perf_counter() - t_sources_start

    with logfire.span(
        SPAN_SEGMENTATION_SAM3,
        scene_id=args.scene_id,
        keyframe_count=len(keyframe_indices),
        mask_count=len(sam_masks),
        vlm_proposal_count=len(vlm_proposals),
        backend=backend,
    ):
        pass  # detail spans live inside sam.run / proposer.propose

    if args.lift_mode == "masks":
        from . import lift_masks as _lift_masks

        # sam_masks now contains BOTH auto-prompt SAM masks (generic
        # discovery) and box-prompted SAM masks (tight boundaries from VLM
        # bboxes, tagged source="vlm" with the VLM phrase). No more
        # rectangle conversion — every mask is a real boundary.
        clusters = _lift_masks.cluster_via_masks(
            scene, sam_masks, jaccard_min=args.jaccard_min, scene_id=args.scene_id
        )

        # Post-cluster dedup: merge clusters whose proposed_phrases are
        # similar AND centroids are within 1.5 m. The Jaccard merge in
        # cluster_via_masks fails for cross-view box-prompted masks
        # (same physical object, but each view captures different surfels)
        # — this pass catches what Jaccard misses. Also pulls Gaussians
        # from multiple views into one cluster so the centroid is the 3D
        # center of the object, not a single visible face.
        with logfire.span(
            "segmentation.lift.merge_duplicates",
            scene_id=args.scene_id,
            cluster_count_pre=len(clusters),
        ) as merge_span:
            merge_stats = _lift_masks.merge_duplicate_clusters(scene, clusters)
            for k, v in merge_stats.items():
                merge_span.set_attribute(k, v)
    else:
        from . import lift as _lift

        # DBSCAN path is SAM-only legacy; VLM proposals are ignored.
        clusters = _lift.cluster(
            scene, sam_masks, eps=args.eps, min_samples=args.min_samples
        )

    with logfire.span(
        SPAN_SEGMENTATION_VLM,
        scene_id=args.scene_id,
        cluster_count=len(clusters),
    ) as vlm_span:
        t0 = time.perf_counter()
        labels = _vlm.label_clusters(scene, clusters, scene_id=args.scene_id)
        annotations = _to_annotations(clusters, labels)

        # Post-VLM dedup. The pre-VLM merge_duplicate_clusters gates on each
        # cluster's proposed_phrase (a noisy per-keyframe hint), so cross-view
        # duplicates of the same physical object slip through and reach the
        # labeler as separate clusters. Final VLM labels are far more stable
        # ("door" + "door" + "door"...), so re-running dedup on the labels
        # collapses what the first pass missed. Bbox-midpoint replaces the
        # partial-view geometric median on merged groups.
        from . import lift_masks as _lift_masks_mod
        with logfire.span(
            "segmentation.annotations.merge_duplicates",
            scene_id=args.scene_id,
            annotation_count_pre=len(annotations.root),
        ) as ann_merge_span:
            merged_anns, ann_merge_stats = _lift_masks_mod.merge_annotations_by_label(
                annotations.root
            )
            annotations = AnnotationsFile(root=merged_anns)
            for k, v in ann_merge_stats.items():
                ann_merge_span.set_attribute(k, v)
            ann_merge_span.set_attribute(
                "annotation_count_post", len(annotations.root)
            )

        annotations.write_atomic(scene / "annotations.json")
        vlm_dur = time.perf_counter() - t0
        # Final, post-filter inventory so the demo's evidence span carries the
        # actual labelled objects (after duplicate / "none" rejection).
        attach_payload(
            vlm_span,
            "annotations",
            [
                {
                    "id": a.id,
                    "label": a.label,
                    "confidence": a.confidence,
                    "alternatives": a.alternatives,
                    "provenance": list(a.provenance),
                }
                for a in annotations.root
            ],
        )
        vlm_span.set_attribute("annotation_count", len(annotations.root))

    total_mask_count = len(sam_masks)
    return (
        annotations,
        sources_dur,
        vlm_dur,
        backend,
        total_mask_count,
        len(clusters),
    )


def _to_annotations(clusters, labels) -> AnnotationsFile:
    """Build AnnotationsFile, dropping VLM-rejected clusters and duplicates.

    A cluster is dropped when:
      - label == "none" (proposer/labeler rejected the crop), or
      - alternatives[0] starts with "duplicate_of:" (canonical kept elsewhere).
    """
    out: list[Annotation] = []
    for c in clusters:
        lab = labels.get(c.id)
        if lab is not None:
            if lab.label.strip().lower() == "none":
                continue
            if lab.alternatives and str(lab.alternatives[0]).startswith("duplicate_of:"):
                continue
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
                provenance=list(c.sources),
                frame_ids=list(c.frame_ids),
            )
        )
    return AnnotationsFile(root=out)
