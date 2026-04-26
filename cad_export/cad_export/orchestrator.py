"""E7 — End-to-end cad_export orchestrator.

Composes E2 (views) → E3 (TRELLIS generation) → E4 (register) →
E5 (fallback) → E6 (qc + assemble) for one scene. Pure Python; the
Modal endpoint wraps this with image_cad + cad_export_object.map().

Two seams are pluggable so the same code runs locally (with stubs) and
on Modal (with real SAM/TRELLIS). See `runners.py`.

Failure routing — for each object:
  - generative path is taken when ALL of:
      * E2 picked enough diverse views (low_diversity_flag is False)
      * label is not architectural (wall/floor/ceiling/window/door)
      * generate_runner produced a valid .glb
      * register accepted the result (RMSE + scale clamp)
  - otherwise → E5 fallback (Poisson on cluster point cloud)
  - if fallback_mode == "none" and generative didn't pan out, the object
    is dropped from the assembly with a 'skipped_no_fallback' tag.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import logfire
import numpy as np
import trimesh
from shared.observability import configure_logfire
from shared.schemas.manifest import Manifest, Stage

from . import config
from .assemble import AssembleResult, ObjectAsset, assemble
from .config import FallbackMode
from .fallback import (
    derive_normals_from_splat,
    fallback_reconstruct,
    is_architectural,
)
from .io import cameras_by_frame_id, load_cameras, load_splat_full
from .object_views import (
    emit_crops_for_views,
    select_views_for_scene,
)
from .qc import compute_qc
from .register import register_mesh_to_cluster
from .runners import (
    FlatMaskRunner,
    GenerateInput,
    GenerateRunner,
    LocalGenerateStub,
    MaskRunner,
)


@dataclass
class OrchestratorResult:
    assemble: AssembleResult
    skipped_no_fallback: list[str]   # obj_ids dropped because mode='none'
    triggered_by: dict[str, str]     # obj_id → reason fallback / skip happened


def _set_stage_running(manifest_path: Path) -> None:
    if not manifest_path.exists():
        return
    m = Manifest.read(manifest_path)
    m.stages.cad_export = Stage(status="running")
    m.write_atomic(manifest_path)


def _set_stage_failed(manifest_path: Path, error: str) -> None:
    if not manifest_path.exists():
        return
    m = Manifest.read(manifest_path)
    m.stages.cad_export = Stage(status="failed")
    m.errors.append(f"cad_export: {error}")
    m.write_atomic(manifest_path)


def orchestrate(
    scene_id: str,
    scene_root: Path,
    *,
    object_filter: list[str] | None = None,
    fallback_mode: FallbackMode | None = None,
    mask_runner: MaskRunner | None = None,
    generate_runner: GenerateRunner | None = None,
    crop_workspace: Path | None = None,
) -> OrchestratorResult:
    """Run E2 → E3 → E4 → E5 → E6 end-to-end for `scene_id`.

    Args:
        scene_id, scene_root: scene identification + artifacts/scenes/<id>/.
        object_filter:        only process this list of annotation ids
                              (corresponds to the CLI `--object` repeatable).
        fallback_mode:        `auto`/`nksr`/`poisson`/`none`. None → env default.
        mask_runner:          for E2.2 crop emission. None → FlatMaskRunner.
        generate_runner:      for E3 TRELLIS. None → LocalGenerateStub
                              (offline, forces fallback path on every object).
        crop_workspace:       where to stage per-object views. None → /tmp.

    Mutates scene_root/manifest.json (sets cad_export stage running →
    complete via E6's assemble) and commits the cad/ subtree under
    scene_root.
    """
    configure_logfire(f"cad_export-{scene_id}")

    if mask_runner is None:
        mask_runner = FlatMaskRunner()
    if generate_runner is None:
        generate_runner = LocalGenerateStub()
    if crop_workspace is None:
        crop_workspace = Path("/tmp/cad_export")
    resolved_mode: FallbackMode | None = fallback_mode

    manifest_path = scene_root / "manifest.json"
    _set_stage_running(manifest_path)
    started_at = time.perf_counter()

    try:
        annotations: list[dict[str, Any]] = json.loads(
            (scene_root / "annotations.json").read_text()
        )
        if object_filter:
            wanted = set(object_filter)
            annotations = [a for a in annotations if a["id"] in wanted]
        if not annotations:
            raise ValueError(
                f"no annotations to process for scene {scene_id}"
                + (f" with filter {object_filter}" if object_filter else "")
            )

        splat = load_splat_full(scene_root / "splat.ply")
        cameras = load_cameras(scene_root / "cameras.json")
        cams_by_id = cameras_by_frame_id(cameras)
        frames_dir = scene_root / "frames"

        # ── E2: view selection (geometric) ──────────────────────────────
        objects = [
            (
                a["id"],
                splat.centers[a["cluster_gaussian_indices"]],
                np.asarray(a["bbox"], dtype=np.float64),
            )
            for a in annotations
        ]
        selections = select_views_for_scene(
            scene_id=scene_id,
            objects=objects,
            full_splat_centers=splat.centers,
            cameras=cameras,
        )
        sel_by_id = {s.obj_id: s for s in selections}

        # ── E2.2: crop emission ─────────────────────────────────────────
        crop_dirs: dict[str, Path] = {}
        for ann in annotations:
            sel = sel_by_id.get(ann["id"])
            if sel is None or not sel.chosen_camera_ids:
                continue
            out_dir = crop_workspace / ann["id"] / "views"
            emit_crops_for_views(
                obj_id=ann["id"],
                selection=sel,
                cameras_by_id=cams_by_id,
                cluster_bbox_world=np.asarray(ann["bbox"], dtype=np.float64),
                frames_dir=frames_dir,
                out_dir=out_dir,
                mask_runner=mask_runner,
            )
            crop_dirs[ann["id"]] = out_dir

        # ── E3: TRELLIS generation (fan-out) ────────────────────────────
        gen_inputs = [
            GenerateInput(obj_id=a["id"], view_dir=crop_dirs.get(a["id"]))
            for a in annotations
        ]
        gen_outputs = generate_runner.run_batch(scene_id, gen_inputs)
        gen_by_id = {g.obj_id: g for g in gen_outputs}

        # ── E4 + E5: per-object register-or-fallback ────────────────────
        assets: list[ObjectAsset] = []
        skipped: list[str] = []
        triggered_by: dict[str, str] = {}

        for ann in annotations:
            ann_id = ann["id"]
            cluster_idx = ann["cluster_gaussian_indices"]
            cluster_centers = splat.centers[cluster_idx].astype(np.float64)
            cluster_quats = splat.quat_wxyz[cluster_idx]
            cluster_log_scales = splat.log_scale[cluster_idx]
            cluster_centroid = np.asarray(ann["centroid"], dtype=np.float64)
            cluster_bbox = np.asarray(ann["bbox"], dtype=np.float64)

            gen = gen_by_id.get(ann_id)
            sel = sel_by_id.get(ann_id)

            mesh: trimesh.Trimesh | None = None
            registration = None
            path_taken: str | None = None
            triggered = "no_generative"

            try_generative = (
                gen is not None
                and gen.success
                and gen.glb_path is not None
                and Path(gen.glb_path).exists()
                and not is_architectural(ann["label"])
                and sel is not None
                and not sel.low_diversity_flag
            )
            if try_generative:
                try:
                    gen_mesh = trimesh.load(gen.glb_path, force="mesh")
                    reg = register_mesh_to_cluster(
                        obj_id=ann_id,
                        mesh=gen_mesh,
                        cluster_centers=cluster_centers,
                        cluster_centroid=cluster_centroid,
                        cluster_bbox=cluster_bbox,
                        scene_id=scene_id,
                    )
                    if reg.accepted:
                        mesh = gen_mesh
                        registration = reg
                        path_taken = "generative"
                    else:
                        triggered = f"register_{reg.rejection_reason}"
                except Exception as exc:
                    triggered = f"generative_load_failed:{type(exc).__name__}"
            elif gen is not None and not gen.success:
                triggered = f"generate_failed:{gen.failure_reason or 'unknown'}"
            elif is_architectural(ann["label"]):
                triggered = "architectural_label"
            elif sel is None or sel.low_diversity_flag:
                triggered = "low_view_diversity"

            if mesh is None:
                resolved = resolved_mode if resolved_mode is not None else config.fallback_mode()
                if resolved == "none":
                    skipped.append(ann_id)
                    triggered_by[ann_id] = f"{triggered}:no_fallback"
                    continue
                normals = derive_normals_from_splat(cluster_quats, cluster_log_scales)
                fb = fallback_reconstruct(
                    obj_id=ann_id,
                    label=ann["label"],
                    positions=cluster_centers,
                    normals=normals,
                    bbox=cluster_bbox,
                    scene_id=scene_id,
                    mode=resolved_mode,
                    triggered_by=triggered,
                )
                mesh = fb.mesh
                path_taken = f"fallback_{fb.method}"
                triggered_by[ann_id] = f"{triggered}:{fb.reason}"
            else:
                triggered_by[ann_id] = "generative"

            view_div = float(sel.view_diversity_deg) if sel is not None else 0.0
            rmse = float(registration.rmse) if registration is not None else 0.0
            qc_metrics = compute_qc(
                obj_id=ann_id,
                mesh=mesh,
                cluster_centers=cluster_centers,
                annotation_bbox=cluster_bbox,
                path_taken=path_taken or "fallback_poisson",  # type: ignore[arg-type]
                view_diversity_deg=view_div,
                register_rmse=rmse,
            )
            assets.append(ObjectAsset(
                obj_id=ann_id,
                label=ann["label"],
                mesh=mesh,
                qc=qc_metrics,
                registration=registration,
            ))

        # ── E6: QC + assemble ───────────────────────────────────────────
        if not assets:
            raise RuntimeError(
                f"cad_export produced 0 assets for scene {scene_id}"
                + (f" (skipped: {skipped})" if skipped else "")
            )
        assembly = assemble(
            scene_id=scene_id,
            scene_root=scene_root,
            assets=assets,
            started_at=started_at,
        )

        return OrchestratorResult(
            assemble=assembly,
            skipped_no_fallback=skipped,
            triggered_by=triggered_by,
        )

    except Exception as exc:
        _set_stage_failed(manifest_path, str(exc))
        logfire.error("cad_export.orchestrate_failed", scene_id=scene_id, error=str(exc))
        raise
