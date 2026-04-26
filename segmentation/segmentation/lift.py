"""Lift 2D SAM masks to 3D Gaussian clusters.

Spec (plans/modules/03_segmentation.md) prefers mask co-occurrence across
frames. We use a simpler, more robust pipeline that the spec explicitly
allows as a fallback and treats as the v0:

1. DBSCAN on Gaussian centers -> N spatial clusters.
2. For each cluster, project its centroid into every keyframe and find
   the SAM mask that contains it. Pick the (frame, mask) with the largest
   area as the cluster's "anchor" — this is what the VLM gets to label.
3. Cluster's gaussian_indices are the DBSCAN members.

TODO(swap): mask co-occurrence graph for tighter per-object Gaussian sets.
The current scheme over-includes Gaussians (whole DBSCAN cluster), which is
fine for the demo (centroid + bbox + label) but loose for per-object masks
in the viewer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import logfire
import numpy as np
from sklearn.cluster import DBSCAN

from .sam import Mask
from .splat_io import load_centers


@dataclass
class Cluster:
    id: str
    gaussian_indices: list[int]
    centroid: np.ndarray  # (3,)
    bbox_3d: tuple[tuple[float, float, float], tuple[float, float, float]]
    anchor_frame: str | None
    anchor_mask_bbox: tuple[int, int, int, int] | None  # (x, y, w, h) in image
    anchor_area: int
    sources: tuple[str, ...] = ()  # subset of {"sam", "vlm"}, sorted
    proposed_phrase: str = ""  # best VLM phrase for the group; empty if SAM-only
    # Up to 6 frame names where this object appears, sorted. Used by the
    # multimodal chat agent to pull keyframes for visual reasoning.
    frame_ids: list[str] = field(default_factory=list)


def _project(point_xyz: np.ndarray, extrinsic: np.ndarray, intrinsic: np.ndarray) -> tuple[int, int, float] | None:
    """World point -> pixel (u, v, z_cam). Returns None if behind camera."""
    p = np.array([point_xyz[0], point_xyz[1], point_xyz[2], 1.0])
    cam = extrinsic @ p  # (4,)
    z = cam[2]
    if z <= 1e-6:
        return None
    uv = intrinsic @ (cam[:3] / z)
    return int(round(uv[0])), int(round(uv[1])), float(z)


def cluster(
    scene_dir: Path,
    masks: list[Mask],
    eps: float = 0.15,
    min_samples: int = 30,
    max_clusters: int = 12,
) -> list[Cluster]:
    """DBSCAN on Gaussian centers, then anchor each cluster to a (frame, mask)."""
    with logfire.span(
        "segmentation.lift.cluster",
        eps=eps,
        min_samples=min_samples,
        max_clusters=max_clusters,
        mask_count=len(masks),
    ) as span:
        centers = load_centers(scene_dir / "splat.ply")
        span.set_attribute("gaussian_count", int(centers.shape[0]))
        if centers.shape[0] == 0:
            span.set_attribute("cluster_count", 0)
            return []

        db = DBSCAN(eps=eps, min_samples=min_samples).fit(centers)
        labels = db.labels_  # -1 = noise
        span.set_attribute(
            "noise_fraction",
            float((labels == -1).sum()) / max(1, labels.size),
        )

        cameras = json.loads((scene_dir / "cameras.json").read_text())
        masks_by_frame_name: dict[str, list[Mask]] = {}
        for m in masks:
            masks_by_frame_name.setdefault(m.frame_name, []).append(m)

        cam_by_frame: dict[str, dict] = {c["frame"]: c for c in cameras if "frame" in c}

        clusters: list[Cluster] = []
        unique = sorted({lbl for lbl in labels if lbl != -1})
        for cid in unique[:max_clusters]:
            idx = np.where(labels == cid)[0]
            if idx.size < min_samples:
                continue
            pts = centers[idx]
            centroid = pts.mean(axis=0)
            bbox_lo = pts.min(axis=0)
            bbox_hi = pts.max(axis=0)

            anchor_frame: str | None = None
            anchor_bbox: tuple[int, int, int, int] | None = None
            anchor_area = 0
            for frame_name, frame_masks in masks_by_frame_name.items():
                cam = cam_by_frame.get(frame_name)
                if cam is None:
                    continue
                ext = np.array(cam["extrinsic"], dtype=np.float64)
                intr = np.array(cam["intrinsic"], dtype=np.float64)
                proj = _project(centroid, ext, intr)
                if proj is None:
                    continue
                u, v, _ = proj
                for m in frame_masks:
                    h, w = m.segmentation.shape
                    if not (0 <= u < w and 0 <= v < h):
                        continue
                    if not m.segmentation[v, u]:
                        continue
                    if m.area > anchor_area:
                        anchor_area = m.area
                        anchor_frame = frame_name
                        anchor_bbox = m.bbox

            clusters.append(
                Cluster(
                    id=f"obj_{cid + 1:03d}",
                    gaussian_indices=idx.tolist(),
                    centroid=centroid,
                    bbox_3d=(
                        (float(bbox_lo[0]), float(bbox_lo[1]), float(bbox_lo[2])),
                        (float(bbox_hi[0]), float(bbox_hi[1]), float(bbox_hi[2])),
                    ),
                    anchor_frame=anchor_frame,
                    anchor_mask_bbox=anchor_bbox,
                    anchor_area=anchor_area,
                )
            )

        span.set_attribute("cluster_count", len(clusters))
        return clusters
