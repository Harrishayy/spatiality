"""E5 — Fallback surface reconstruction from cluster point cloud.

Spec: 11_cad_export.md §11.4.

When the generative path (TRELLIS.2 in E3 + scaled-ICP in E4) fails — no
mesh returned, non-manifold output, hausdorff exceeds tolerance, or RMSE
gate fails — we reconstruct directly from the cluster's Gaussian centers
+ normals. Output is intentionally lower-fidelity than the generative
path: holes from occluded backs become smooth blobs. The fallback exists
so one bad object doesn't break the assembly.

Architectural surfaces (walls/floors/ceilings/windows/doors) are pre-routed
to this path and never go through TRELLIS, since TRELLIS is trained on
object-scale assets and produces nonsense for large planar surfaces.

Both reconstruction backends are open-source:
  - NKSR (nv-tlabs OSS, Apache-style) — primary if installable.
  - Open3D screened Poisson (Apache 2.0) — always-available baseline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import logfire
import numpy as np
import open3d as o3d
import trimesh
from shared.observability import SPAN_CAD_FALLBACK

from . import config


Method = Literal["nksr", "poisson"]


@dataclass
class FallbackResult:
    obj_id: str
    mesh: trimesh.Trimesh
    method: Method
    reason: str          # short tag: architectural_label / forced_<method> / auto_nksr / nksr_unavailable / register_failed
    point_count: int     # input cluster size


def _o3d_to_trimesh(mesh: o3d.geometry.TriangleMesh) -> trimesh.Trimesh:
    return trimesh.Trimesh(
        vertices=np.asarray(mesh.vertices),
        faces=np.asarray(mesh.triangles),
        process=False,
    )


def derive_normals_from_splat(
    quat_wxyz: np.ndarray,
    log_scale: np.ndarray,
) -> np.ndarray:
    """Recover surface normals from a slice of splat.ply Gaussian fields.

    The surfel synthesis in `inference/inference/poses.py` constructs each
    Gaussian's rotation as R = [e1, e2, n] where `n` is the surface normal.
    By construction n maps to the smallest log_scale axis (s_n = 0.3 × s_t).
    We recover n by rotating to matrix form and selecting the column with
    the smallest scale — making this robust if scale ordering ever changes.
    """
    from scipy.spatial.transform import Rotation as R_scipy

    quat_xyzw = quat_wxyz[:, [1, 2, 3, 0]]
    R = R_scipy.from_quat(quat_xyzw).as_matrix()  # (N, 3, 3)
    smallest = np.argmin(log_scale, axis=1)
    rows = np.arange(len(R))
    return R[rows, :, smallest]


def _poisson_reconstruct(
    positions: np.ndarray,
    normals: np.ndarray,
    bbox: np.ndarray,
    *,
    depth: int = 9,
) -> trimesh.Trimesh:
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(np.asarray(positions, dtype=np.float64))
    pcd.normals = o3d.utility.Vector3dVector(np.asarray(normals, dtype=np.float64))
    mesh_o3d, _densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(
        pcd, depth=depth, scale=1.1, linear_fit=False,
    )
    # Crop to the cluster bbox to discard Poisson's unbounded extrapolation
    # outside the supported region.
    aabb = o3d.geometry.AxisAlignedBoundingBox(
        min_bound=np.asarray(bbox[0], dtype=np.float64),
        max_bound=np.asarray(bbox[1], dtype=np.float64),
    )
    mesh_o3d = mesh_o3d.crop(aabb)
    return _o3d_to_trimesh(mesh_o3d)


def _try_nksr(positions: np.ndarray, normals: np.ndarray) -> trimesh.Trimesh | None:
    """Best-effort NKSR reconstruction. Returns None if NKSR or CUDA isn't
    available in this environment — caller falls back to Poisson."""
    try:
        import nksr  # type: ignore[import-not-found]
        import torch
    except ImportError:
        return None

    if not torch.cuda.is_available():
        return None

    try:
        device = torch.device("cuda")
        reconstructor = nksr.Reconstructor(device)
        field = reconstructor.reconstruct(
            torch.from_numpy(np.asarray(positions, dtype=np.float32)).to(device),
            torch.from_numpy(np.asarray(normals, dtype=np.float32)).to(device),
        )
        dual = field.extract_dual_mesh()
        return trimesh.Trimesh(
            vertices=dual.v.cpu().numpy(),
            faces=dual.f.cpu().numpy(),
            process=False,
        )
    except RuntimeError:
        return None


def is_architectural(label: str) -> bool:
    return bool(re.match(config.ARCHITECTURAL_LABEL_PATTERN, label, re.IGNORECASE))


def fallback_reconstruct(
    obj_id: str,
    label: str,
    positions: np.ndarray,
    normals: np.ndarray,
    bbox: np.ndarray,
    *,
    scene_id: str = "",
    mode: config.FallbackMode | None = None,
    triggered_by: str = "register_failed",
) -> FallbackResult:
    """Reconstruct an oriented mesh in scene coordinates from cluster points.

    Args:
        obj_id, label:    annotation id and label string.
        positions:        (N, 3) cluster Gaussian centers (scene coords).
        normals:          (N, 3) surface normals from `derive_normals_from_splat`.
        bbox:             (2, 3) [min, max] cluster bbox for Poisson cropping.
        mode:             override CAD_FALLBACK env (auto/nksr/poisson). 'none'
                          is rejected here — callers must avoid invoking this
                          function when fallback is disabled.
        triggered_by:     short tag describing why fallback was invoked.

    Caller is responsible for not calling this when mode == 'none'. The output
    mesh is already in scene coordinates so no registration is needed.
    """
    resolved = mode if mode is not None else config.fallback_mode()
    if resolved == "none":
        raise ValueError("fallback_reconstruct invoked with mode='none' — caller bug")

    architectural = is_architectural(label)
    point_count = int(len(positions))

    with logfire.span(
        SPAN_CAD_FALLBACK,
        scene_id=scene_id,
        object_id=obj_id,
    ) as span:
        if architectural or resolved == "poisson":
            method: Method = "poisson"
            reason = "architectural_label" if architectural else "forced_poisson"
            mesh = _poisson_reconstruct(positions, normals, bbox)
        elif resolved == "nksr":
            nksr_mesh = _try_nksr(positions, normals)
            if nksr_mesh is None:
                raise RuntimeError(
                    "CAD_FALLBACK=nksr but NKSR is unavailable in this environment"
                )
            method = "nksr"
            reason = "forced_nksr"
            mesh = nksr_mesh
        else:  # auto
            nksr_mesh = _try_nksr(positions, normals)
            if nksr_mesh is not None:
                method = "nksr"
                reason = "auto_nksr"
                mesh = nksr_mesh
            else:
                method = "poisson"
                reason = "nksr_unavailable"
                mesh = _poisson_reconstruct(positions, normals, bbox)

        span.set_attribute("method", method)
        span.set_attribute("reason", f"{triggered_by}:{reason}")
        span.set_attribute("point_count", point_count)

        return FallbackResult(
            obj_id=obj_id, mesh=mesh, method=method,
            reason=reason, point_count=point_count,
        )
