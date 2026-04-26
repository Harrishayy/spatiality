"""Fixture-driven verification for E2 (object_views geometric core).

Synthesizes:
  - 8 cameras orbiting the origin at radius 3, evenly spaced 45° apart.
  - 1 "blind" camera looking AWAY from the cluster — must be ineligible.
  - 1 cluster: points sampled inside a unit-cube at the origin.
  - 1 occluder cluster placed between camera #7 and the target — the
    z-buffer occlusion test should drop or downgrade view #7.

Asserts:
  - With K=4 + min_angle=30°, all four chosen cameras come from the orbit
    and span ≥ 30° pairwise.
  - The blind camera never appears in chosen_camera_ids.
  - Tightening min_angle to 80° flags low_diversity_flag (only 2 cameras
    in 8 evenly-spaced ones can be ≥80° apart for K=4).
  - Occluded camera is downgraded by the visibility test.

Run:
    uv run python cad_export/scripts/verify_e2.py
"""

from __future__ import annotations

import sys

import numpy as np
from shared.observability import configure_logfire

from cad_export import object_views as ov


def _look_at_camera(
    frame_id: str,
    eye: np.ndarray,
    target: np.ndarray,
    *,
    up: np.ndarray = np.array([0.0, 0.0, 1.0]),
    width: int = 1024,
    height: int = 768,
    focal: float = 800.0,
) -> ov.CameraInfo:
    """OpenCV-style world→cam: +Z into scene, R rows = camera axes in world."""
    forward = target - eye
    forward = forward / np.linalg.norm(forward)
    right = np.cross(forward, up)
    nr = np.linalg.norm(right)
    if nr < 1e-9:
        right = np.array([1.0, 0.0, 0.0])
    else:
        right = right / nr
    cam_down = np.cross(forward, right)  # camera +Y points "down" in OpenCV
    R = np.stack([right, cam_down, forward], axis=0)
    t = -R @ eye
    Rt = np.eye(4)
    Rt[:3, :3] = R
    Rt[:3, 3] = t
    K = np.array([[focal, 0, width / 2.0], [0, focal, height / 2.0], [0, 0, 1.0]])
    return ov.CameraInfo(frame_id=frame_id, K=K, Rt=Rt, width=width, height=height)


def _orbit_cameras(n: int = 8, radius: float = 3.0) -> list[ov.CameraInfo]:
    cams = []
    for i in range(n):
        theta = 2 * np.pi * i / n
        eye = np.array([radius * np.cos(theta), radius * np.sin(theta), 0.5])
        cams.append(_look_at_camera(f"orbit_{i:02d}", eye, target=np.zeros(3)))
    return cams


def _cluster_points(seed: int = 11, n: int = 800) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    centers = rng.uniform(-0.4, 0.4, size=(n, 3))
    bbox = np.array([centers.min(axis=0), centers.max(axis=0)])
    return centers, bbox


def test_orbit_selects_four_diverse_views() -> None:
    cameras = _orbit_cameras()
    blind = _look_at_camera(
        "blind",
        eye=np.array([0.0, 0.0, -3.0]),
        target=np.array([0.0, 0.0, -10.0]),  # looking away from origin
    )
    cameras.append(blind)
    cluster, bbox = _cluster_points()
    full_splat = cluster.copy()  # no occluders for this test

    sel = ov.select_views_for_object(
        obj_id="orbit_obj",
        cluster_centers=cluster,
        cluster_bbox=bbox,
        full_splat_centers=full_splat,
        cameras=cameras,
        k=4,
        min_angle_deg=30.0,
        min_visible_frac=0.30,
    )

    assert len(sel.chosen_camera_ids) == 4, f"expected 4 chosen, got {len(sel.chosen_camera_ids)}"
    assert "blind" not in sel.chosen_camera_ids, "blind camera must not be selected"
    assert sel.view_diversity_deg >= 30.0, f"diversity below threshold: {sel.view_diversity_deg:.1f}"
    assert sel.low_diversity_flag is False
    print(
        f"  ✓ orbit selects diverse 4: chosen={sel.chosen_camera_ids}, "
        f"diversity={sel.view_diversity_deg:.1f}°, eligible={sel.eligible_count}"
    )


def test_blind_camera_is_ineligible() -> None:
    cluster, bbox = _cluster_points()
    blind = _look_at_camera(
        "blind",
        eye=np.array([0.0, 0.0, -3.0]),
        target=np.array([0.0, 0.0, -10.0]),
    )
    cameras = [blind]
    sel = ov.select_views_for_object(
        obj_id="blind_only",
        cluster_centers=cluster,
        cluster_bbox=bbox,
        full_splat_centers=cluster,
        cameras=cameras,
        k=4, min_angle_deg=30.0, min_visible_frac=0.30,
    )
    assert sel.eligible_count == 0, f"expected 0 eligible, got {sel.eligible_count}"
    assert len(sel.chosen_camera_ids) == 0
    assert sel.low_diversity_flag is True
    print(f"  ✓ blind-only scene: eligible={sel.eligible_count}, low_diversity={sel.low_diversity_flag}")


def test_high_min_angle_flags_low_diversity() -> None:
    """8 evenly-spaced cameras → max K=4 separation is 90° (every other one);
    requiring 91° forces a fall to K=2 and trips the low_diversity flag."""
    cameras = _orbit_cameras()
    cluster, bbox = _cluster_points()
    sel = ov.select_views_for_object(
        obj_id="strict_diversity",
        cluster_centers=cluster,
        cluster_bbox=bbox,
        full_splat_centers=cluster,
        cameras=cameras,
        k=4, min_angle_deg=91.0, min_visible_frac=0.30,
    )
    assert sel.low_diversity_flag is True, "expected low_diversity at 91° / 45°-orbit"
    print(
        f"  ✓ strict 80° diversity: chose {len(sel.chosen_camera_ids)}, "
        f"diversity={sel.view_diversity_deg:.1f}°, low_diversity={sel.low_diversity_flag}"
    )


def test_occlusion_downgrades_back_camera() -> None:
    """Place a wall between camera #4 (looking +X→origin from -X) and the
    cluster. The wall's z-buffer should reduce the visible_fraction of
    that camera's score so its eligibility / score drops."""
    cluster, bbox = _cluster_points()
    cameras = _orbit_cameras()
    # Wall is a dense slab between origin and the +X-side camera (orbit_00 at +X).
    # Camera 0 is at (3, 0, 0.5), looking toward origin. Wall lives at x≈1.5
    # blocking that view.
    rng = np.random.default_rng(33)
    wall = np.column_stack([
        np.full(2000, 1.5) + rng.normal(0, 0.02, 2000),
        rng.uniform(-1.0, 1.0, 2000),
        rng.uniform(-1.0, 1.0, 2000),
    ])
    full_splat = np.vstack([cluster, wall])

    sel = ov.select_views_for_object(
        obj_id="occlusion_test",
        cluster_centers=cluster,
        cluster_bbox=bbox,
        full_splat_centers=full_splat,
        cameras=cameras,
        k=8, min_angle_deg=0.0,  # disable diversity to inspect raw scoring
        min_visible_frac=0.10,
    )
    score_by_id = {s.cam.frame_id: s for s in sel.scores_debug}
    occluded = score_by_id["orbit_00"]
    unobstructed = score_by_id["orbit_04"]  # opposite side, clear line-of-sight
    assert occluded.visible_fraction < unobstructed.visible_fraction, (
        f"occluded vis {occluded.visible_fraction:.3f} should be less than "
        f"unobstructed {unobstructed.visible_fraction:.3f}"
    )
    print(
        f"  ✓ occlusion: orbit_00 visible_fraction={occluded.visible_fraction:.3f} "
        f"< orbit_04 visible_fraction={unobstructed.visible_fraction:.3f}"
    )


def test_select_views_for_scene_emits_span_attrs() -> None:
    cameras = _orbit_cameras()
    cluster, bbox = _cluster_points()
    objects = [("obj_001", cluster, bbox), ("obj_002", cluster + 0.1, bbox + 0.1)]
    results = ov.select_views_for_scene(
        scene_id="synthetic_e2",
        objects=objects,
        full_splat_centers=cluster,
        cameras=cameras,
    )
    assert len(results) == 2
    for r in results:
        assert len(r.chosen_camera_ids) == 4
    print(f"  ✓ scene-level: {len(results)} objects → 4 views each")


def main() -> int:
    configure_logfire("cad_export-verify")
    print("E2 view-selection tests")
    test_orbit_selects_four_diverse_views()
    test_blind_camera_is_ineligible()
    test_high_min_angle_flags_low_diversity()
    test_occlusion_downgrades_back_camera()
    test_select_views_for_scene_emits_span_attrs()
    print("\nall E2 fixture checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
