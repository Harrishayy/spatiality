"""E4 — Scaled ICP registration of generated mesh to scene coordinates.

Spec: 11_cad_export.md §11.3.

The TRELLIS.2 generative path emits a mesh in a normalized [-0.5, 0.5]^3
frame with no canonical pose. This module recovers the similarity transform
T_final (rotation + translation + uniform scale) that snaps it back into
real scene coordinates, using the cluster's Gaussian centers as the target
point cloud and the annotation's centroid + bbox to seed the initial scale.

Wrong scale is the demo-killer (per spec §"Failure paths"); the RMSE gate +
scale clamp here are the safety net.
"""

from __future__ import annotations

from dataclasses import dataclass

import logfire
import numpy as np
import open3d as o3d
import trimesh
from shared.observability import SPAN_CAD_REGISTER

from . import config


@dataclass
class RegistrationResult:
    obj_id: str
    T_final: list[list[float]]      # 4x4 row-major
    scale: float                    # uniform scale recovered from T_final
    rmse: float                     # ICP inlier RMSE in metres
    accepted: bool                  # passes RMSE gate AND scale clamp
    rejection_reason: str | None    # None if accepted, else short tag


_SCALE_LO_FACTOR = 0.5
_SCALE_HI_FACTOR = 2.0


def _initial_transform(centroid: np.ndarray, scale_init: float) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] *= scale_init
    T[:3, 3] = centroid
    return T


def _recover_scale(T: np.ndarray) -> float:
    # Uniform-scale similarity: each column of the upper-left 3x3 has length = scale.
    return float(np.linalg.norm(T[:3, 0]))


def register_mesh_to_cluster(
    obj_id: str,
    mesh: trimesh.Trimesh,
    cluster_centers: np.ndarray,
    cluster_centroid: np.ndarray,
    cluster_bbox: np.ndarray,
    *,
    scene_id: str = "",
    rmse_frac: float = config.REGISTER_RMSE_FRAC,
    sample_count: int = 50_000,
    max_iterations: int = 100,
) -> RegistrationResult:
    """Register `mesh` (in normalized frame) to `cluster_centers` (scene coords).

    Args:
        obj_id:           annotation id, used in span attrs and the result.
        mesh:             generated mesh, vertices in TRELLIS's normalized frame.
        cluster_centers:  (N, 3) Gaussian centers from the cluster, scene coords.
        cluster_centroid: (3,) annotation centroid, used for translation init.
        cluster_bbox:     (2, 3) [min, max] annotation bbox in scene coords.

    Side effect: mutates `mesh.vertices` in place to scene coordinates iff
    the result is accepted. On rejection, mesh is left untouched so the
    caller can route it through the fallback path.
    """
    cluster_centers = np.asarray(cluster_centers, dtype=np.float64)
    cluster_centroid = np.asarray(cluster_centroid, dtype=np.float64)
    cluster_bbox = np.asarray(cluster_bbox, dtype=np.float64)

    bbox_extent = cluster_bbox[1] - cluster_bbox[0]
    bbox_diag = float(np.linalg.norm(bbox_extent))
    scale_init = float(np.max(bbox_extent))
    icp_threshold = 0.05 * bbox_diag

    with logfire.span(
        SPAN_CAD_REGISTER,
        scene_id=scene_id,
        object_id=obj_id,
    ) as span:
        samples, _ = trimesh.sample.sample_surface(mesh, sample_count)
        source = o3d.geometry.PointCloud()
        source.points = o3d.utility.Vector3dVector(np.asarray(samples, dtype=np.float64))
        target = o3d.geometry.PointCloud()
        target.points = o3d.utility.Vector3dVector(cluster_centers)

        T_init = _initial_transform(cluster_centroid, scale_init)
        icp = o3d.pipelines.registration.registration_icp(
            source, target, icp_threshold, T_init,
            o3d.pipelines.registration.TransformationEstimationPointToPoint(with_scaling=True),
            o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=max_iterations),
        )
        T_final = np.asarray(icp.transformation, dtype=np.float64)
        rmse = float(icp.inlier_rmse) if icp.inlier_rmse > 0 else float("inf")
        scale = _recover_scale(T_final)

        # Scale clamp (spec §"Failure paths"): if scale drifted >2x or <0.5x
        # of the initial bbox-derived guess, ICP almost certainly latched onto
        # the wrong basin. Reject for fallback rather than risk a
        # wall-embedded chair.
        scale_lo = _SCALE_LO_FACTOR * scale_init
        scale_hi = _SCALE_HI_FACTOR * scale_init
        if not (scale_lo <= scale <= scale_hi):
            rejection_reason = "scale_out_of_range"
        elif rmse > rmse_frac * bbox_diag:
            rejection_reason = "rmse_above_threshold"
        else:
            rejection_reason = None

        accepted = rejection_reason is None
        if accepted:
            mesh.apply_transform(T_final)

        span.set_attribute("rmse", rmse)
        span.set_attribute("scale_recovered", scale)
        span.set_attribute("accepted", accepted)
        if rejection_reason is not None:
            span.set_attribute("rejection_reason", rejection_reason)

        return RegistrationResult(
            obj_id=obj_id,
            T_final=T_final.tolist(),
            scale=scale,
            rmse=rmse,
            accepted=accepted,
            rejection_reason=rejection_reason,
        )


