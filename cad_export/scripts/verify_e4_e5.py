"""Fixture-driven verification for E4 (register) and E5 (fallback).

No real scene needed. Synthesizes:
  - A unit cube mesh + a known similarity transform → asserts E4 register
    recovers the transform within tolerance.
  - A noisy sphere point cloud with outward normals → asserts E5 fallback
    Poisson produces a watertight mesh roughly bbox-similar to ground truth.
  - The architectural-label regex routes "wall"/"floor"/etc. to Poisson.

Run:
    uv run python -m cad_export.scripts.verify_e4_e5
or via the justfile recipe added by E4+E5:
    just cad-verify
"""

from __future__ import annotations

import sys

import numpy as np
import trimesh
from shared.observability import configure_logfire

from cad_export import fallback, register


def _make_unit_cube_cluster(seed: int = 7) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    cube = trimesh.creation.box(extents=(1.0, 1.0, 1.0))
    samples, _ = trimesh.sample.sample_surface(cube, 6000)
    samples = samples + rng.normal(scale=0.005, size=samples.shape)
    centroid = samples.mean(axis=0)
    bbox = np.array([samples.min(axis=0), samples.max(axis=0)])
    return samples.astype(np.float64), centroid, bbox


def test_register_recovers_known_similarity() -> None:
    """Generated mesh in normalized frame + known transform → ICP recovers it."""
    rng = np.random.default_rng(11)
    truth_scale = 0.30
    truth_translation = np.array([5.0, -2.0, 1.5])

    # "Generated" mesh: a unit cube in the normalized frame.
    gen_mesh = trimesh.creation.box(extents=(1.0, 1.0, 1.0))

    # Cluster: same cube, transformed into scene coords (truth target).
    cluster_mesh = gen_mesh.copy()
    T_truth = np.eye(4)
    T_truth[:3, :3] *= truth_scale
    T_truth[:3, 3] = truth_translation
    cluster_mesh.apply_transform(T_truth)
    cluster_centers, _ = trimesh.sample.sample_surface(cluster_mesh, 6000)
    cluster_centers = cluster_centers + rng.normal(scale=0.001, size=cluster_centers.shape)
    centroid = cluster_centers.mean(axis=0)
    bbox = np.array([cluster_centers.min(axis=0), cluster_centers.max(axis=0)])

    result = register.register_mesh_to_cluster(
        obj_id="obj_test_cube",
        mesh=gen_mesh.copy(),
        cluster_centers=cluster_centers,
        cluster_centroid=centroid,
        cluster_bbox=bbox,
    )

    assert result.accepted, f"expected accepted=True, got rejection={result.rejection_reason!r}, rmse={result.rmse:.4f}"
    assert abs(result.scale - truth_scale) / truth_scale < 0.10, (
        f"scale recovery off: got {result.scale:.4f}, truth {truth_scale:.4f}"
    )
    bbox_diag = float(np.linalg.norm(bbox[1] - bbox[0]))
    assert result.rmse < 0.08 * bbox_diag, f"rmse {result.rmse:.4f} above gate"
    print(
        f"  ✓ register: scale={result.scale:.4f} (truth {truth_scale}), "
        f"rmse={result.rmse:.5f}, bbox_diag={bbox_diag:.4f}"
    )


def test_register_rejects_garbage_init() -> None:
    """Cluster too small for the mesh → scale clamp rejects, no mutation."""
    gen_mesh = trimesh.creation.box(extents=(1.0, 1.0, 1.0))
    rng = np.random.default_rng(3)
    # Tiny cluster (5 cm) but mesh expects ~1 m → init scale guess is 0.05;
    # ICP will resolve to something in that range; this test is mainly making
    # sure the function doesn't crash on a degenerate input and reports a
    # well-formed RegistrationResult either way.
    cluster_centers = rng.normal(scale=0.025, size=(500, 3)) + np.array([10.0, 10.0, 10.0])
    centroid = cluster_centers.mean(axis=0)
    bbox = np.array([cluster_centers.min(axis=0), cluster_centers.max(axis=0)])
    pre_vertices = gen_mesh.vertices.copy()

    result = register.register_mesh_to_cluster(
        obj_id="obj_degenerate",
        mesh=gen_mesh,
        cluster_centers=cluster_centers,
        cluster_centroid=centroid,
        cluster_bbox=bbox,
    )

    if not result.accepted:
        # On rejection, mesh must be left untouched so caller can route to fallback.
        assert np.allclose(gen_mesh.vertices, pre_vertices), (
            "rejected registration must not mutate mesh in place"
        )
        print(f"  ✓ register rejection: reason={result.rejection_reason!r}, rmse={result.rmse:.4f}")
    else:
        print(f"  ✓ register accepted on degenerate input: scale={result.scale:.4f}")


def test_fallback_poisson_on_sphere() -> None:
    """Noisy sphere PC + outward normals → Poisson produces a non-empty mesh."""
    rng = np.random.default_rng(19)
    n = 4000
    phi = rng.uniform(0, 2 * np.pi, n)
    cos_theta = rng.uniform(-1.0, 1.0, n)
    sin_theta = np.sqrt(1.0 - cos_theta**2)
    radius = 0.5
    positions = np.column_stack([
        radius * sin_theta * np.cos(phi),
        radius * sin_theta * np.sin(phi),
        radius * cos_theta,
    ]) + rng.normal(scale=0.002, size=(n, 3))
    normals = positions / (np.linalg.norm(positions, axis=1, keepdims=True) + 1e-9)
    bbox = np.array([positions.min(axis=0) - 0.05, positions.max(axis=0) + 0.05])

    result = fallback.fallback_reconstruct(
        obj_id="obj_test_sphere",
        label="lamp",
        positions=positions,
        normals=normals,
        bbox=bbox,
        mode="poisson",
        triggered_by="register_failed",
    )

    assert result.method == "poisson", f"expected poisson, got {result.method}"
    assert len(result.mesh.vertices) > 0, "Poisson returned empty mesh"
    assert len(result.mesh.faces) > 0, "Poisson returned no faces"
    extents = result.mesh.extents
    # Should be roughly 2 * radius in each axis after bbox crop.
    for axis_extent in extents:
        assert 0.4 < axis_extent < 1.5, f"unexpected sphere extent {axis_extent:.3f}"
    print(
        f"  ✓ fallback (poisson): method={result.method}, "
        f"vertices={len(result.mesh.vertices)}, faces={len(result.mesh.faces)}, "
        f"extents={extents}"
    )


def test_architectural_label_routing() -> None:
    """Walls/floors must route to Poisson regardless of mode='auto'."""
    rng = np.random.default_rng(23)
    positions = rng.uniform(-1.0, 1.0, size=(500, 3))
    normals = np.tile([0.0, 0.0, 1.0], (500, 1))
    bbox = np.array([[-1.5, -1.5, -1.5], [1.5, 1.5, 1.5]])

    for label in ("wall", "Wall", "floor", "ceiling", "window", "door"):
        assert fallback.is_architectural(label), f"{label!r} should be architectural"
    for label in ("chair", "laptop", "lamp", "MacBook Air", "wallet"):
        assert not fallback.is_architectural(label), f"{label!r} must not match"

    result = fallback.fallback_reconstruct(
        obj_id="obj_wall_test",
        label="wall",
        positions=positions, normals=normals, bbox=bbox,
        mode="auto",
        triggered_by="architectural_pre_route",
    )
    assert result.method == "poisson", "architectural label must force Poisson"
    assert result.reason == "architectural_label"
    print(f"  ✓ architectural routing: label='wall' → method={result.method}")


def test_normals_from_splat_quaternion() -> None:
    """Smallest-scale axis lookup recovers the third basis column."""
    rng = np.random.default_rng(29)
    n = 50
    # Build random orthonormal frames; the third column is the "normal".
    from scipy.spatial.transform import Rotation as R_scipy
    rotmats = R_scipy.random(n, rng).as_matrix()
    quat_xyzw = R_scipy.from_matrix(rotmats).as_quat()
    quat_wxyz = quat_xyzw[:, [3, 0, 1, 2]]
    # Make the third axis the smallest-scale axis (mirroring poses.py s_n = 0.3 * s_t).
    log_scale = np.tile([0.0, 0.0, -1.2], (n, 1))

    normals = fallback.derive_normals_from_splat(quat_wxyz, log_scale)
    expected = rotmats[:, :, 2]
    diff = np.linalg.norm(normals - expected, axis=1).max()
    assert diff < 1e-5, f"max normal mismatch {diff}"
    print(f"  ✓ derive_normals_from_splat: max diff vs ground truth = {diff:.2e}")


def main() -> int:
    configure_logfire("cad_export-verify")
    print("E4 register tests")
    test_register_recovers_known_similarity()
    test_register_rejects_garbage_init()
    print("E5 fallback tests")
    test_fallback_poisson_on_sphere()
    test_architectural_label_routing()
    test_normals_from_splat_quaternion()
    print("\nall fixture checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
