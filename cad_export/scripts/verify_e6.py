"""Fixture-driven verification for E6 (qc + assemble).

Synthesizes 3 hand-built unit meshes (cube, sphere, cone), runs QC against
matching synthetic clusters, and writes the full cad/ output tree to a
tempdir scene.

Verifies:
  - QC bbox-IoU correctly rejects offset meshes from the assembly.
  - objects/<id>.{obj,stl} are written for every object (accepted or not).
  - scene.3mf is roundtrip-loadable via trimesh and contains only accepted
    geometries.
  - positions.json + qc.json are valid JSON.
  - manifest.json is mutated with cad_export stage = complete + populated
    artifacts + stats.

Run:
    uv run python cad_export/scripts/verify_e6.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import trimesh
from shared.observability import configure_logfire
from shared.schemas.manifest import Artifacts, Manifest, Stage, Stages, Stats

from cad_export import assemble, qc, register


def _make_cluster_for(mesh: trimesh.Trimesh, n: int = 4000, noise: float = 0.005) -> np.ndarray:
    rng = np.random.default_rng(int(mesh.area * 1000) % 2**32)
    samples, _ = trimesh.sample.sample_surface(mesh, n)
    return np.asarray(samples, dtype=np.float64) + rng.normal(scale=noise, size=samples.shape)


def _seed_manifest(scene_root: Path, scene_id: str) -> Path:
    """Write a minimal pre-cad-export manifest so assemble can mutate it."""
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
        stats=Stats(frame_count=12, object_count=3, splat_size_mb=10.0),
    )
    path = scene_root / "manifest.json"
    manifest.write_atomic(path)
    return path


def _build_assets() -> list[assemble.ObjectAsset]:
    cube = trimesh.creation.box(extents=(0.4, 0.3, 0.2))
    cube.apply_translation([1.0, 0.0, 0.0])
    sphere = trimesh.creation.icosphere(subdivisions=3, radius=0.2)
    sphere.apply_translation([0.0, 1.5, 0.0])
    cone = trimesh.creation.cone(radius=0.15, height=0.4)
    cone.apply_translation([0.0, 0.0, 2.0])

    # The "bad" object: a mesh offset way outside its annotation bbox to
    # exercise the bbox-IoU rejection.
    bad = trimesh.creation.box(extents=(0.3, 0.3, 0.3))
    bad.apply_translation([10.0, 10.0, 10.0])

    objs = [
        ("obj_001", "MacBook Air", cube,   "generative",        45.0, 0.012),
        ("obj_002", "lamp",        sphere, "fallback_poisson",   0.0, 0.0),
        ("obj_003", "cone marker", cone,   "generative",        38.0, 0.020),
        ("obj_004", "phantom",     bad,    "generative",        25.0, 0.18),  # bbox IoU near 0
    ]
    assets: list[assemble.ObjectAsset] = []
    for obj_id, label, mesh, path_taken, view_div, rmse in objs:
        cluster = _make_cluster_for(mesh)
        # Make a tight annotation bbox AROUND the cluster. For the phantom
        # object we deliberately use a bbox where the mesh truly belongs
        # (origin-ish), so the mesh's actual bbox (at +10) won't overlap.
        if obj_id == "obj_004":
            ann_bbox = np.array([[-0.2, -0.2, -0.2], [0.2, 0.2, 0.2]])
        else:
            ann_bbox = np.array([cluster.min(axis=0), cluster.max(axis=0)])
        m = qc.compute_qc(
            obj_id=obj_id,
            mesh=mesh,
            cluster_centers=cluster,
            annotation_bbox=ann_bbox,
            path_taken=path_taken,  # type: ignore[arg-type]
            view_diversity_deg=view_div,
            register_rmse=rmse,
        )
        # Synthesize a registration result for the generative-path objects.
        reg = None
        if path_taken == "generative":
            reg = register.RegistrationResult(
                obj_id=obj_id,
                T_final=np.eye(4).tolist(),
                scale=1.0,
                rmse=rmse,
                accepted=True,
                rejection_reason=None,
            )
        assets.append(assemble.ObjectAsset(
            obj_id=obj_id, label=label, mesh=mesh, qc=m, registration=reg,
        ))
    return assets


def test_qc_metrics_basic() -> None:
    cube = trimesh.creation.box(extents=(0.4, 0.4, 0.4))
    cluster = _make_cluster_for(cube)
    bbox = np.array([cluster.min(axis=0), cluster.max(axis=0)])
    m = qc.compute_qc(
        obj_id="cube_test",
        mesh=cube,
        cluster_centers=cluster,
        annotation_bbox=bbox,
        path_taken="generative",
        view_diversity_deg=42.0,
        register_rmse=0.01,
    )
    assert m.is_watertight, "trimesh box must be watertight"
    assert m.is_manifold, "trimesh box must be manifold"
    assert m.bbox_iou_with_annotation > 0.5, f"expected high bbox IoU, got {m.bbox_iou_with_annotation:.3f}"
    assert m.included_in_assembly is True
    print(
        f"  ✓ qc cube: watertight={m.is_watertight}, faces={m.face_count}, "
        f"hausdorff={m.hausdorff_to_cluster_m:.4f}, bbox_iou={m.bbox_iou_with_annotation:.3f}"
    )


def test_qc_bbox_iou_rejection() -> None:
    cube = trimesh.creation.box(extents=(0.3, 0.3, 0.3))
    cube.apply_translation([10.0, 10.0, 10.0])
    cluster = _make_cluster_for(cube)
    far_bbox = np.array([[-0.2, -0.2, -0.2], [0.2, 0.2, 0.2]])
    m = qc.compute_qc(
        obj_id="cube_offset",
        mesh=cube,
        cluster_centers=cluster,
        annotation_bbox=far_bbox,
        path_taken="generative",
        view_diversity_deg=30.0,
        register_rmse=0.5,
    )
    assert m.bbox_iou_with_annotation < 0.1, f"expected ~0 IoU, got {m.bbox_iou_with_annotation:.3f}"
    assert m.included_in_assembly is False
    print(f"  ✓ qc rejection: bbox_iou={m.bbox_iou_with_annotation:.4f} → excluded from assembly")


def test_assemble_writes_full_tree() -> None:
    with tempfile.TemporaryDirectory() as td:
        scene_root = Path(td) / "scenes" / "verify_scene"
        scene_root.mkdir(parents=True)
        manifest_path = _seed_manifest(scene_root, "verify_scene")
        assets = _build_assets()

        started = time.perf_counter()
        result = assemble.assemble(
            scene_id="verify_scene",
            scene_root=scene_root,
            assets=assets,
            started_at=started,
        )

        # Per-object files: every asset (incl. the rejected phantom) gets OBJ + STL.
        for a in assets:
            assert (result.objects_dir / f"{a.obj_id}.obj").exists(), f"missing obj for {a.obj_id}"
            assert (result.objects_dir / f"{a.obj_id}.stl").exists(), f"missing stl for {a.obj_id}"

        # 3MF assembly: roundtrip via trimesh; only 3 of 4 assets should be in it.
        assert result.scene_3mf_path.exists()
        loaded = trimesh.load(result.scene_3mf_path)
        if hasattr(loaded, "geometry"):
            geom_count = len(loaded.geometry)
        else:
            geom_count = 1  # single-geometry export collapses
        assert geom_count == 3, f"expected 3 accepted geometries in 3MF, got {geom_count}"
        assert result.accepted_count == 3
        assert result.rejected_count == 1

        # qc.json + positions.json
        qc_payload = json.loads(result.qc_json_path.read_text())
        assert set(qc_payload.keys()) == {"obj_001", "obj_002", "obj_003", "obj_004"}
        assert qc_payload["obj_004"]["included_in_assembly"] is False

        positions_payload = json.loads(result.positions_json_path.read_text())
        # Only generative-path assets carry a registration → only those appear.
        assert set(positions_payload.keys()) == {"obj_001", "obj_003", "obj_004"}
        assert "T_final" in positions_payload["obj_001"]
        assert "scale" in positions_payload["obj_001"]

        # Manifest mutation
        m = Manifest.read(manifest_path)
        assert m.stages.cad_export.status == "complete"
        assert m.stats.cad_object_count == 3
        assert m.stats.cad_total_face_count > 0
        assert m.artifacts.cad_scene_3mf is not None
        assert m.artifacts.cad_objects_dir is not None
        print(
            f"  ✓ assemble: 3MF={result.scene_3mf_path.name}, "
            f"accepted={result.accepted_count}, rejected={result.rejected_count}, "
            f"face_count={result.total_face_count}, "
            f"manifest.cad_export.status={m.stages.cad_export.status}"
        )


def main() -> int:
    configure_logfire("cad_export-verify")
    print("E6 qc tests")
    test_qc_metrics_basic()
    test_qc_bbox_iou_rejection()
    print("E6 assemble tests")
    test_assemble_writes_full_tree()
    print("\nall E6 fixture checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
