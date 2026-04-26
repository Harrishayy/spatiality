"""E6 — Per-object quality control metrics.

Spec: 11_cad_export.md §11.5.

Computes the metrics that go into `cad/qc.json`. The bbox-IoU gate
(`ACCEPT_BBOX_IOU`, default 0.30) decides whether an object is included
in the final `scene.3mf` assembly — sub-threshold objects still get
written to `objects/` for forensics but are excluded from the assembly,
because shipping a chair embedded in a wall would be misleading.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal

import numpy as np
import trimesh
from scipy.spatial import cKDTree

from . import config


PathTaken = Literal["generative", "fallback_nksr", "fallback_poisson"]


@dataclass
class QCMetrics:
    obj_id: str
    is_watertight: bool
    is_manifold: bool
    vertex_count: int
    face_count: int
    hausdorff_to_cluster_m: float
    chamfer_to_cluster_m: float
    bbox_iou_with_annotation: float
    path_taken: PathTaken
    view_diversity_deg: float
    register_rmse: float
    included_in_assembly: bool


def _aabb_iou(a: np.ndarray, b: np.ndarray) -> float:
    """3D axis-aligned bbox IoU. Each input is shape (2, 3) = [min, max]."""
    inter_min = np.maximum(a[0], b[0])
    inter_max = np.minimum(a[1], b[1])
    inter = np.prod(np.maximum(0.0, inter_max - inter_min))
    a_vol = float(np.prod(np.maximum(0.0, a[1] - a[0])))
    b_vol = float(np.prod(np.maximum(0.0, b[1] - b[0])))
    union = a_vol + b_vol - float(inter)
    return float(inter) / max(union, 1e-9)


def _hausdorff_chamfer(
    mesh: trimesh.Trimesh,
    cluster_centers: np.ndarray,
    sample_count: int = 20_000,
) -> tuple[float, float]:
    samples, _ = trimesh.sample.sample_surface(mesh, sample_count)
    samples = np.asarray(samples, dtype=np.float64)
    cluster = np.asarray(cluster_centers, dtype=np.float64)
    tree_cluster = cKDTree(cluster)
    tree_mesh = cKDTree(samples)
    d_m_to_c, _ = tree_cluster.query(samples)
    d_c_to_m, _ = tree_mesh.query(cluster)
    hausdorff = float(d_m_to_c.max())
    chamfer = float(0.5 * (d_m_to_c.mean() + d_c_to_m.mean()))
    return hausdorff, chamfer


def _is_manifold(mesh: trimesh.Trimesh) -> bool:
    # trimesh exposes is_winding_consistent as the practical manifold check
    # for our purposes (every edge shared by ≤2 faces with consistent winding).
    return bool(mesh.is_winding_consistent)


def compute_qc(
    obj_id: str,
    mesh: trimesh.Trimesh,
    cluster_centers: np.ndarray,
    annotation_bbox: np.ndarray,
    *,
    path_taken: PathTaken,
    view_diversity_deg: float,
    register_rmse: float,
    accept_bbox_iou: float = config.ACCEPT_BBOX_IOU,
) -> QCMetrics:
    """Compute per-object QC. The mesh is expected to already be in scene
    coordinates (post-registration or post-fallback)."""
    annotation_bbox = np.asarray(annotation_bbox, dtype=np.float64)
    mesh_bbox = np.array([mesh.bounds[0], mesh.bounds[1]], dtype=np.float64)

    bbox_iou = _aabb_iou(mesh_bbox, annotation_bbox)
    hausdorff, chamfer = _hausdorff_chamfer(mesh, cluster_centers)

    return QCMetrics(
        obj_id=obj_id,
        is_watertight=bool(mesh.is_watertight),
        is_manifold=_is_manifold(mesh),
        vertex_count=int(len(mesh.vertices)),
        face_count=int(len(mesh.faces)),
        hausdorff_to_cluster_m=hausdorff,
        chamfer_to_cluster_m=chamfer,
        bbox_iou_with_annotation=bbox_iou,
        path_taken=path_taken,
        view_diversity_deg=float(view_diversity_deg),
        register_rmse=float(register_rmse),
        included_in_assembly=bbox_iou >= accept_bbox_iou,
    )


def to_jsonable(metrics: list[QCMetrics]) -> dict:
    """Serialize a list of QCMetrics to the per-object dict that goes into
    `cad/qc.json`."""
    return {m.obj_id: {k: v for k, v in asdict(m).items() if k != "obj_id"} for m in metrics}
