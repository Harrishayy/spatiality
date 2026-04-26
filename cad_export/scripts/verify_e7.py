"""Fixture-driven end-to-end verification for E7 (orchestrator).

Builds a synthetic scene under a tempdir:
  - 3 cluster annotations (cube, sphere, cone) at known centroids
  - splat.ply with all INRIA fields (xyz + quat + log_scale)
  - cameras.json with 8 orbit cameras around the origin
  - frames/ as solid-color PNGs (size matches camera intrinsics)
  - annotations.json + initial manifest.json

Runs orchestrate() with FlatMaskRunner + LocalGenerateStub. The stub
forces every object through the Poisson fallback (no GPU/TRELLIS
needed). Asserts:
  - cad/scene.3mf is written
  - cad/objects/<id>.obj + .stl per accepted object
  - cad/qc.json + cad/positions.json valid JSON
  - manifest.json has stages.cad_export.status == "complete"

Run:
    uv run python cad_export/scripts/verify_e7.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image
from plyfile import PlyData, PlyElement
from shared.observability import configure_logfire
from shared.schemas.manifest import Artifacts, Manifest, Stage, Stages, Stats

from cad_export.orchestrator import orchestrate
from cad_export.runners import FlatMaskRunner, LocalGenerateStub


def _look_at_extrinsic(eye, target, up=np.array([0.0, 0.0, 1.0])):
    forward = target - eye
    forward = forward / np.linalg.norm(forward)
    right = np.cross(forward, up)
    nr = np.linalg.norm(right)
    right = right / nr if nr > 1e-9 else np.array([1.0, 0.0, 0.0])
    cam_down = np.cross(forward, right)
    R = np.stack([right, cam_down, forward], axis=0)
    t = -R @ eye
    Rt = np.eye(4)
    Rt[:3, :3] = R
    Rt[:3, 3] = t
    return Rt


def _orbit_cameras(n=8, radius=3.0, width=512, height=384, focal=400.0):
    cams = []
    K = [[focal, 0.0, width / 2.0], [0.0, focal, height / 2.0], [0.0, 0.0, 1.0]]
    for i in range(n):
        theta = 2 * np.pi * i / n
        eye = np.array([radius * np.cos(theta), radius * np.sin(theta), 0.5])
        Rt = _look_at_extrinsic(eye, np.zeros(3))
        cams.append({
            "frame": f"orbit_{i:02d}.png",
            "extrinsic": Rt.tolist(),
            "intrinsic": K,
            "width": width, "height": height,
        })
    return cams


def _synthesize_clusters(seed=11):
    rng = np.random.default_rng(seed)
    cube = rng.uniform(-0.4, 0.4, size=(120, 3)) + np.array([0.0, 0.0, 0.0])

    # Sphere cluster
    n = 120
    phi = rng.uniform(0, 2 * np.pi, n)
    cos_theta = rng.uniform(-1, 1, n)
    sin_theta = np.sqrt(1 - cos_theta**2)
    sphere_local = np.column_stack([
        0.35 * sin_theta * np.cos(phi),
        0.35 * sin_theta * np.sin(phi),
        0.35 * cos_theta,
    ]) + rng.normal(0, 0.005, (n, 3))
    sphere = sphere_local + np.array([1.5, 0.0, 0.0])

    cone = rng.uniform(-0.3, 0.3, size=(120, 3)) + np.array([0.0, 1.5, 0.5])

    return cube.astype(np.float32), sphere.astype(np.float32), cone.astype(np.float32)


def _quat_for_axis_z():
    # Identity quaternion (w, x, y, z) — surface "normal" axis is +Z.
    return np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)


def _write_synthetic_splat(path: Path, clusters: list[np.ndarray]):
    """Write a minimal INRIA-layout splat.ply with quat + log_scale fields
    so cad_export.io.load_splat_full can read it back."""
    all_xyz = np.concatenate(clusters, axis=0)
    n = len(all_xyz)
    # Random quaternions per Gaussian — for the fallback's normal derivation
    # we just need *some* quat + smallest-axis convention. Identity works.
    quats = np.tile(_quat_for_axis_z(), (n, 1))
    # log_scale: third axis smallest (mirrors poses.py s_n = 0.3 * s_t).
    log_scale = np.tile(np.array([0.0, 0.0, -1.2], dtype=np.float32), (n, 1))

    dtype = [
        ("x", "f4"), ("y", "f4"), ("z", "f4"),
        ("nx", "f4"), ("ny", "f4"), ("nz", "f4"),
        ("f_dc_0", "f4"), ("f_dc_1", "f4"), ("f_dc_2", "f4"),
        ("opacity", "f4"),
        ("scale_0", "f4"), ("scale_1", "f4"), ("scale_2", "f4"),
        ("rot_0", "f4"), ("rot_1", "f4"), ("rot_2", "f4"), ("rot_3", "f4"),
    ]
    arr = np.zeros(n, dtype=dtype)
    arr["x"], arr["y"], arr["z"] = all_xyz[:, 0], all_xyz[:, 1], all_xyz[:, 2]
    arr["scale_0"], arr["scale_1"], arr["scale_2"] = log_scale[:, 0], log_scale[:, 1], log_scale[:, 2]
    arr["rot_0"], arr["rot_1"], arr["rot_2"], arr["rot_3"] = quats[:, 0], quats[:, 1], quats[:, 2], quats[:, 3]

    el = PlyElement.describe(arr, "vertex")
    PlyData([el], text=False, byte_order="<").write(str(path))


def _write_solid_frames(frames_dir: Path, n: int = 8, width: int = 512, height: int = 384):
    frames_dir.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        # A neutral RGB solid color with a slight gradient so it isn't all zeros.
        img = np.full((height, width, 3), 128, dtype=np.uint8)
        img[..., 0] = (i * 30) % 255
        Image.fromarray(img, mode="RGB").save(frames_dir / f"orbit_{i:02d}.png")


def _seed_manifest(scene_root: Path, scene_id: str) -> Path:
    manifest = Manifest(
        scene_id=scene_id,
        created_at=datetime.now(timezone.utc),
        status="processing",
        stages=Stages(
            capture=Stage(status="complete"),
            poses=Stage(status="complete"),
            splat=Stage(status="complete"),
            segmentation=Stage(status="complete"),
        ),
        artifacts=Artifacts(
            splat_ply=str(scene_root / "splat.ply"),
            annotations_json=str(scene_root / "annotations.json"),
            thumbnail_jpg=str(scene_root / "thumbnail.jpg"),
            cameras_json=str(scene_root / "cameras.json"),
        ),
        stats=Stats(frame_count=8, object_count=3, splat_size_mb=0.1),
    )
    path = scene_root / "manifest.json"
    manifest.write_atomic(path)
    return path


def build_synthetic_scene(scene_root: Path, scene_id: str) -> Path:
    scene_root.mkdir(parents=True, exist_ok=True)
    cube, sphere, cone = _synthesize_clusters()
    clusters = [cube, sphere, cone]
    _write_synthetic_splat(scene_root / "splat.ply", clusters)
    cameras = _orbit_cameras()
    (scene_root / "cameras.json").write_text(json.dumps(cameras, indent=2))
    _write_solid_frames(scene_root / "frames", n=len(cameras))

    # Annotations: indices into the concatenated splat array.
    annotations = []
    offset = 0
    for i, (label, cluster) in enumerate(
        [("MacBook Air", cube), ("lamp", sphere), ("cone marker", cone)],
        start=1,
    ):
        n = len(cluster)
        idx = list(range(offset, offset + n))
        offset += n
        centroid = cluster.mean(axis=0).tolist()
        bbox = [cluster.min(axis=0).tolist(), cluster.max(axis=0).tolist()]
        annotations.append({
            "id": f"obj_{i:03d}",
            "label": label,
            "centroid": centroid,
            "bbox": bbox,
            "color": "#888888",
            "confidence": 0.9,
            "alternatives": [],
            "cluster_gaussian_indices": idx,
        })
    (scene_root / "annotations.json").write_text(json.dumps(annotations, indent=2))
    Image.new("RGB", (32, 32), color=(64, 64, 64)).save(scene_root / "thumbnail.jpg")
    return _seed_manifest(scene_root, scene_id)


def test_orchestrator_offline_full_pipeline() -> None:
    with tempfile.TemporaryDirectory() as td:
        scene_root = Path(td) / "scenes" / "verify_e7"
        manifest_path = build_synthetic_scene(scene_root, scene_id="verify_e7")

        result = orchestrate(
            scene_id="verify_e7",
            scene_root=scene_root,
            mask_runner=FlatMaskRunner(),
            generate_runner=LocalGenerateStub(),
            crop_workspace=Path(td) / "tmp_crops",
        )

        cad_dir = scene_root / "cad"
        assert (cad_dir / "scene.3mf").exists(), "scene.3mf not written"
        assert (cad_dir / "qc.json").exists()
        assert (cad_dir / "positions.json").exists()
        assert (cad_dir / "objects").is_dir()

        objs = sorted(cad_dir.glob("objects/*.obj"))
        stls = sorted(cad_dir.glob("objects/*.stl"))
        assert len(objs) == len(stls), f"obj/stl count mismatch {len(objs)} != {len(stls)}"
        # All 3 objects should produce *something* via Poisson fallback.
        assert len(objs) == 3, f"expected 3 OBJs, got {len(objs)}"

        qc = json.loads((cad_dir / "qc.json").read_text())
        assert set(qc.keys()) == {"obj_001", "obj_002", "obj_003"}
        for obj_id, m in qc.items():
            assert m["path_taken"] == "fallback_poisson", (
                f"{obj_id} took {m['path_taken']}, expected fallback_poisson "
                f"because LocalGenerateStub forces every object through E5"
            )

        m = Manifest.read(manifest_path)
        assert m.stages.cad_export.status == "complete"
        assert m.stats.cad_object_count >= 1
        assert m.artifacts.cad_scene_3mf is not None

        print(
            f"  ✓ orchestrator: accepted={result.assemble.accepted_count}, "
            f"rejected={result.assemble.rejected_count}, "
            f"skipped_no_fallback={len(result.skipped_no_fallback)}, "
            f"triggered_by={result.triggered_by}"
        )


def test_orchestrator_no_fallback_skips() -> None:
    with tempfile.TemporaryDirectory() as td:
        scene_root = Path(td) / "scenes" / "verify_e7_nofb"
        build_synthetic_scene(scene_root, scene_id="verify_e7_nofb")

        try:
            orchestrate(
                scene_id="verify_e7_nofb",
                scene_root=scene_root,
                fallback_mode="none",
                mask_runner=FlatMaskRunner(),
                generate_runner=LocalGenerateStub(),
                crop_workspace=Path(td) / "tmp_crops",
            )
        except RuntimeError as exc:
            # 0 assets is the expected outcome when --no-fallback skips
            # everything that the stub fails to generate.
            assert "0 assets" in str(exc), f"unexpected error: {exc}"
            print(f"  ✓ --no-fallback: orchestrator raised (no assets) — {exc}")
            return
        raise AssertionError("expected RuntimeError when no-fallback drops every object")


def main() -> int:
    configure_logfire("cad_export-verify")
    print("E7 orchestrator tests")
    test_orchestrator_offline_full_pipeline()
    test_orchestrator_no_fallback_skips()
    print("\nall E7 fixture checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
