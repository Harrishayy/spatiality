"""E6 — Final CAD assembly: post-process meshes, write OBJ/STL/3MF, manifest.

Spec: 11_cad_export.md §11.6.

Consumes per-object meshes (already in scene coordinates from either the
generative or fallback path), writes:
  cad/
    objects/<obj_id>.{obj,mtl,stl}   # per-object files (always written)
    scene.3mf                        # assembly with named parts (accepted only)
    positions.json                   # per-object SE(3)+scale from registration
    qc.json                          # per-object QC metrics

Then mutates the scene's manifest.json to mark `cad_export` complete.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import logfire
import numpy as np
import trimesh
from shared.observability import SPAN_CAD_ASSEMBLE
from shared.schemas.manifest import Manifest, Stage

from . import config
from .qc import QCMetrics, to_jsonable as qc_to_jsonable
from .register import RegistrationResult


@dataclass
class ObjectAsset:
    """Per-object input to assembly. Mesh must already be in scene coords."""
    obj_id: str
    label: str
    mesh: trimesh.Trimesh
    qc: QCMetrics
    registration: RegistrationResult | None  # None for fallback-only objects


@dataclass
class AssembleResult:
    scene_3mf_path: Path
    objects_dir: Path
    qc_json_path: Path
    positions_json_path: Path
    accepted_count: int
    rejected_count: int
    total_face_count: int


def _post_process(mesh: trimesh.Trimesh, *, max_faces: int) -> trimesh.Trimesh:
    """Watertight repair + normal fix + decimation. Mutates a *copy*."""
    out = mesh.copy()
    if not out.is_watertight:
        trimesh.repair.fill_holes(out)
    trimesh.repair.fix_inversion(out)
    trimesh.repair.fix_normals(out)
    if len(out.faces) > max_faces:
        decimated = out.simplify_quadric_decimation(face_count=max_faces)
        if decimated is not None and len(decimated.faces) > 0:
            out = decimated
    return out


def _write_atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    os.replace(tmp, path)


def _write_positions_json(path: Path, assets: list[ObjectAsset]) -> None:
    payload: dict[str, dict] = {}
    for a in assets:
        if a.registration is None:
            continue
        d = asdict(a.registration)
        payload[a.obj_id] = {k: v for k, v in d.items() if k != "obj_id"}
    _write_atomic_json(path, payload)


def assemble(
    scene_id: str,
    scene_root: Path,
    assets: list[ObjectAsset],
    *,
    started_at: float | None = None,
    max_faces: int = config.MAX_FACES,
) -> AssembleResult:
    """Write all cad/ outputs for the scene and update the manifest."""
    cad_root = scene_root / "cad"
    objects_dir = cad_root / "objects"
    objects_dir.mkdir(parents=True, exist_ok=True)

    accepted_meshes: dict[str, trimesh.Trimesh] = {}
    node_names: dict[str, str] = {}
    total_face_count = 0
    rejected_count = 0

    with logfire.span(
        SPAN_CAD_ASSEMBLE,
        scene_id=scene_id,
    ) as span:
        for asset in assets:
            processed = _post_process(asset.mesh, max_faces=max_faces)
            obj_path = objects_dir / f"{asset.obj_id}.obj"
            stl_path = objects_dir / f"{asset.obj_id}.stl"
            processed.export(obj_path)
            processed.export(stl_path)
            if asset.qc.included_in_assembly:
                accepted_meshes[asset.obj_id] = processed
                node_names[asset.obj_id] = asset.label
                total_face_count += int(len(processed.faces))
            else:
                rejected_count += 1

        # Build 3MF assembly with named parts. Sub-threshold objects are
        # written under objects/ for forensics but excluded here.
        scene = trimesh.Scene()
        for obj_id, mesh in accepted_meshes.items():
            scene.add_geometry(mesh, geom_name=obj_id, node_name=node_names[obj_id])
        scene_3mf_path = cad_root / "scene.3mf"
        scene.export(scene_3mf_path, file_type="3mf")

        positions_json_path = cad_root / "positions.json"
        _write_positions_json(positions_json_path, assets)

        qc_json_path = cad_root / "qc.json"
        _write_atomic_json(qc_json_path, qc_to_jsonable([a.qc for a in assets]))

        accepted_count = len(accepted_meshes)
        result = AssembleResult(
            scene_3mf_path=scene_3mf_path,
            objects_dir=objects_dir,
            qc_json_path=qc_json_path,
            positions_json_path=positions_json_path,
            accepted_count=accepted_count,
            rejected_count=rejected_count,
            total_face_count=total_face_count,
        )

        # Manifest update — make this stage's outputs visible to /web + /agent.
        manifest_path = scene_root / "manifest.json"
        if manifest_path.exists():
            duration_s = (time.perf_counter() - started_at) if started_at is not None else None
            _update_manifest(
                manifest_path,
                scene_root=scene_root,
                accepted_count=accepted_count,
                rejected_count=rejected_count,
                total_face_count=total_face_count,
                duration_s=duration_s,
            )

        span.set_attribute("accepted_count", accepted_count)
        span.set_attribute("rejected_count", rejected_count)
        span.set_attribute("assembly_face_count", total_face_count)
        return result


def _update_manifest(
    manifest_path: Path,
    *,
    scene_root: Path,
    accepted_count: int,
    rejected_count: int,
    total_face_count: int,
    duration_s: float | None,
) -> None:
    manifest = Manifest.read(manifest_path)
    manifest.stages.cad_export = Stage(
        status="complete",
        duration_s=duration_s,
        accepted_count=accepted_count,
        rejected_count=rejected_count,
    )
    manifest.artifacts.cad_scene_3mf = str(scene_root / "cad" / "scene.3mf")
    manifest.artifacts.cad_objects_dir = str(scene_root / "cad" / "objects")
    manifest.stats.cad_object_count = accepted_count
    manifest.stats.cad_total_face_count = total_face_count
    manifest.write_atomic(manifest_path)
