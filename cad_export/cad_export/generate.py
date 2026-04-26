"""E3 — TRELLIS.2-4B multi-view image-to-3D wrapper.

Spec: 11_cad_export.md §11.2.

Loads K RGBA crops from /tmp/cad_export/<obj_id>/views/, runs TRELLIS.2's
run_multi_image with the seeded sampler params from the spec, and writes
the resulting mesh as raw.glb in the model's normalized [-0.5, 0.5]^3
frame. Registration (E4) recovers metric scale + scene-coord transform.

License: TRELLIS.2 is MIT (model + code). Confirmed against the model card
at huggingface.co/microsoft/TRELLIS.2-4B and the GitHub README.

This module is import-light at top level so the package can be imported
locally for E4/E5/E6 fixture-driven dev without trellis2 installed —
trellis2 is loaded lazily inside `generate_mesh`. On the cad_export Modal
image (image_cad in inference/modal_app.py) trellis2 is installed editably
from /opt/trellis2.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

import logfire
from shared.observability import SPAN_CAD_GENERATE

from . import config


@dataclass
class GenerateResult:
    obj_id: str
    glb_path: Path
    vertex_count: int
    face_count: int
    latency_ms: float
    success: bool
    failure_reason: str | None


def _load_views(view_dir: Path):
    from PIL import Image
    paths = sorted(view_dir.glob("*.png"))
    if not paths:
        raise FileNotFoundError(f"no view crops under {view_dir}")
    return [Image.open(p).convert("RGBA") for p in paths]


def generate_mesh(
    obj_id: str,
    view_dir: Path,
    out_path: Path,
    *,
    scene_id: str = "",
    weights_dir: str | None = None,
    seed: int = config.TRELLIS_SEED,
    gpu_label: str = "H100",
    sparse_steps: int = 12,
    sparse_cfg: float = 7.5,
    slat_steps: int = 12,
    slat_cfg: float = 3.0,
) -> GenerateResult:
    """Run TRELLIS.2 multi-view image-to-3D for one object.

    Args:
        obj_id, scene_id: tagging for the cad_export.generate span.
        view_dir:         directory of RGBA PNG crops (E2's output).
        out_path:         where to write raw.glb (caller-controlled).
        weights_dir:      override TRELLIS_WEIGHTS_DIR env (Modal volume path).
        seed, *_steps, *_cfg: spec §11.2 sampler params; pin defaults here.

    Returns a GenerateResult. Raises ImportError-derived RuntimeError if
    trellis2 is not installed in the calling environment.
    """
    weights_dir = weights_dir or os.environ.get("TRELLIS_WEIGHTS_DIR", "/weights/trellis2")

    with logfire.span(
        SPAN_CAD_GENERATE,
        scene_id=scene_id,
        object_id=obj_id,
        gpu=gpu_label,
    ) as span:
        t0 = time.perf_counter()
        try:
            from trellis2.pipelines import Trellis2ImageTo3DPipeline  # type: ignore[import-not-found]
        except ImportError as exc:
            import sys
            span.set_attribute("import_error", str(exc))
            raise RuntimeError(
                f"trellis2 import failed: {exc!r}\n"
                f"sys.path={sys.path}\n"
                f"/opt/trellis2 listing: {list(__import__('os').listdir('/opt/trellis2')) if __import__('os').path.isdir('/opt/trellis2') else 'MISSING'}"
            ) from exc

        views = _load_views(view_dir)
        # TRELLIS.2's actual API is single-image: pipe.run(image). There is no
        # run_multi_image. The spec assumed otherwise; for now use the first
        # view as the conditioning image. trellis2's from_pretrained always
        # uses HF Hub (no local-dir branch); HF_HOME=/weights/trellis2/.hf
        # caches weights on the Modal volume after first cold-start.
        pipe = Trellis2ImageTo3DPipeline.from_pretrained("microsoft/TRELLIS.2-4B")
        pipe.cuda()

        meshes = pipe.run(
            views[0],
            num_samples=1,
            seed=seed,
            sparse_structure_sampler_params=dict(
                steps=sparse_steps, cfg_strength=sparse_cfg,
            ),
            shape_slat_sampler_params=dict(steps=slat_steps, cfg_strength=slat_cfg),
        )
        mesh = meshes[0]  # MeshWithVoxel in [-0.5, 0.5]^3
        latency_ms = (time.perf_counter() - t0) * 1000.0

        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Export as GLB using o_voxel's postprocess (PBR-aware). The simplify
        # step keeps face count under nvdiffrast's hard limit.
        import o_voxel  # type: ignore[import-not-found]
        mesh.simplify(16777216)
        glb = o_voxel.postprocess.to_glb(
            vertices=mesh.vertices,
            faces=mesh.faces,
            attr_volume=mesh.attrs,
            coords=mesh.coords,
            attr_layout=mesh.layout,
            voxel_size=mesh.voxel_size,
            aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
            decimation_target=int(os.environ.get("CAD_MAX_FACES", "150000")),
            texture_size=2048,
            remesh=True,
            remesh_band=1,
            remesh_project=0,
            verbose=False,
        )
        glb.export(str(out_path))

        vc = int(len(mesh.vertices))
        fc = int(len(mesh.faces))
        success = vc > 0 and fc > 0
        failure_reason = None if success else "empty_mesh"

        span.set_attribute("vertex_count", vc)
        span.set_attribute("face_count", fc)
        span.set_attribute("latency_ms", latency_ms)
        span.set_attribute("seed", seed)
        if failure_reason:
            span.set_attribute("failure_reason", failure_reason)

        return GenerateResult(
            obj_id=obj_id,
            glb_path=out_path,
            vertex_count=vc,
            face_count=fc,
            latency_ms=latency_ms,
            success=success,
            failure_reason=failure_reason,
        )
