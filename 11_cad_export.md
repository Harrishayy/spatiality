# Module 11 — CAD export (per-object watertight meshes)

## Goal
Take a finished scene (`splat.ply` + `cameras.json` + `annotations.json`) and produce **per-object watertight triangle meshes** that import cleanly into Fusion 360 / SolidWorks. The full scene is delivered as one **3MF** assembly with named parts plus a fallback directory of per-object **OBJ + MTL** (textured) and **STL** (geometry-only).

Output is "honest enough" for documentation and presentation, **not** parametric BREP. We do not attempt mesh→STEP reverse engineering — that is out of scope.

The headline pipeline is **per-object multi-view image-to-3D via TRELLIS.2-4B**, with **NKSR / screened Poisson** as a per-object fallback when the generative path fails QC. Critically, this is the only place in the system that *invents geometry* (the back of every object is hallucinated from priors). That tradeoff is conscious and documented in §"Honesty caveat".

## Inputs
- `artifacts/scenes/<scene_id>/splat.ply` — INRIA-layout Gaussians (from `/inference`).
- `artifacts/scenes/<scene_id>/cameras.json` — per-frame extrinsics + intrinsics (from `/inference`).
- `artifacts/scenes/<scene_id>/frames/*.png` — original RGB.
- `artifacts/scenes/<scene_id>/annotations.json` — every object with `cluster_gaussian_indices` (from `/segmentation`).

## Outputs
All written under `artifacts/scenes/<scene_id>/cad/`:

```
cad/
  objects/
    obj_001.obj         # textured mesh, scene coordinates
    obj_001.mtl
    obj_001.stl         # geometry-only, scene coordinates
    obj_001.png         # baked diffuse texture
    obj_002.obj
    ...
  scene.3mf             # assembly: every object as a named part, scene coords
  positions.json        # per-object SE(3) + scale used by the registration step
  qc.json               # per-object QC: watertight?, vertex/face count, hausdorff to source cluster, fallback used?
```

The new manifest stage `cad_export` records counts and timings (see §"Manifest changes").

## Tech
- **Multi-view image→mesh:** [TRELLIS.2-4B](https://github.com/microsoft/TRELLIS.2) (Microsoft, CVPR'25). Native `run_multi_image()` accepts up to 16 views (we pass 4). Cleaner topology than Hunyuan3D and built-in PBR — we keep diffuse only.
- **Mask reprojection:** custom NumPy. Project each cluster's Gaussian centers into every camera, score views, re-derive a tight SAM bbox-prompted mask in the chosen frames.
- **Registration:** Open3D scaled-ICP (`o3d.t.pipelines.registration.icp` with `estimation_method=TransformationEstimationPointToPoint(with_scaling=True)`). Initial transform from the cluster's centroid + bbox principal axes.
- **Fallback surface reconstruction:** [NKSR](https://github.com/nv-tlabs/NKSR) primary, falls back to Open3D screened Poisson if NKSR can't be installed in the Modal image.
- **Mesh post-processing:** trimesh (watertight check, hole fill, decimation if >150k faces, manifold guarantee).
- **3MF assembly:** trimesh has 3MF writer; supports named parts.
- **GPU host:** Modal H100 (same image as `/inference` + a separate weights volume entry for TRELLIS.2). Per-object Modal `.map(return_exceptions=True)` for parallelism.

## Pipeline shape

```
annotations.json  splat.ply  cameras.json  frames/
       │              │           │            │
       └──────┬───────┴─────┬─────┴────────────┘
              │             │
              ▼             ▼
   ┌──────────────────────────────┐
   │ object_views.py              │  For each annotation: project cluster
   │ (stage: cad_export.views)    │  Gaussians into all cameras, score views,
   │                              │  pick K=4 with min angular separation,
   │                              │  re-derive SAM mask in each chosen frame,
   │                              │  emit RGBA crops to /tmp/<obj_id>/views/.
   └──────────────────────────────┘
              │
              ▼  (per-object, parallel)
   ┌──────────────────────────────┐
   │ generate.py                  │  Modal .map() over annotations.
   │ (stage: cad_export.generate) │  Each task: run TRELLIS.2-4B
   │ GPU: H100                    │  multi-image on the K crops.
   │                              │  Output: trimesh in normalized frame.
   └──────────────────────────────┘
              │
              ▼
   ┌──────────────────────────────┐
   │ register.py                  │  Scaled-ICP each generated mesh
   │ (stage: cad_export.register) │  against its source cluster's
   │                              │  Gaussian centers. Init from cluster
   │                              │  centroid + bbox principal axes.
   │                              │  Reject if RMSE > τ → fallback.
   └──────────────────────────────┘
              │              │
              ▼              ▼ (only on rejection)
   ┌──────────────┐  ┌──────────────────────┐
   │ qc.py        │  │ fallback.py          │  NKSR or screened Poisson
   │              │  │ (stage:              │  on the cluster's Gaussian
   │              │  │ cad_export.fallback) │  centers (oriented PC).
   └──────────────┘  └──────────────────────┘
              │              │
              └──────┬───────┘
                     ▼
   ┌──────────────────────────────┐
   │ assemble.py                  │  Write objects/, scene.3mf,
   │ (stage: cad_export.assemble) │  positions.json, qc.json.
   │                              │  Update manifest.
   └──────────────────────────────┘
```

The whole thing is one Modal function (`cad_export`) that fans out to a per-object Modal function (`cad_export_object`) via `.map(return_exceptions=True)` so a single bad object does not poison the scene-level run.

## Per-stage detail

### 11.1 — `object_views.py` (view selection)

For every annotation `A`:

1. Slice the cluster's Gaussian centers `P` from `splat.ply` using `A.cluster_gaussian_indices`.
2. For each camera `C` in `cameras.json`:
   - Project `P` through `C.K @ C.Rt` into image space.
   - Score = `visible_fraction × in_frame_fraction × mean_depth_inverse × √(min_dist_to_image_edge)`.
   - Drop cameras where <30% of cluster points project inside frame OR the cluster is occluded by other clusters' Gaussians (z-test against the full splat at the projected pixels).
3. Greedy-select K=4 cameras with **angular separation ≥ 30°** between camera viewing directions (so the four views aren't four near-duplicates). Fall back to K=2 if only two angularly distinct views exist; flag for "low view diversity".
4. For each chosen camera:
   - Project the cluster bbox into image → 2D bbox prompt for SAM.
   - Run SAM (the same model already in segmentation/) box-prompted; pick the largest mask whose IoU with the projected cluster is ≥ 0.4.
   - Apply mask, alpha-matte to transparent background, square-pad to `1024×1024` (TRELLIS expects square). Keep the crop tight (mask bbox + 8% margin).
5. Write `/tmp/cad_export/<obj_id>/views/{0..3}.png` (RGBA).

Emits a per-object `views_meta.json` with `chosen_camera_ids`, `view_diversity_deg` (min angle between any pair), `low_diversity_flag`. View diversity feeds QC.

### 11.2 — `generate.py` (TRELLIS.2 multi-view)

Per object, on H100:

```python
from trellis2.pipelines import Trellis2ImageTo3DPipeline

pipe = Trellis2ImageTo3DPipeline.from_pretrained("microsoft/TRELLIS.2-4B")
pipe.cuda()

views = [PIL.Image.open(p).convert("RGBA") for p in sorted(view_dir.glob("*.png"))]
out = pipe.run_multi_image(
    views,
    seed=42,
    formats=["mesh"],            # we don't need gaussians or radiance fields
    sparse_structure_sampler_params=dict(steps=12, cfg_strength=7.5),
    slat_sampler_params=dict(steps=12, cfg_strength=3.0),
)
mesh = out["mesh"][0]            # trimesh.Trimesh
```

- Save as `/tmp/cad_export/<obj_id>/raw.glb`.
- TRELLIS output is in a normalized cube `[-0.5, 0.5]³`. Carry that frame forward; registration recovers metric scale.
- Pin the seed in code (`seed=42`). The build must be reproducible.
- TRELLIS.2 weights live on `glasses-twin-weights` Modal Volume at `trellis2/`. First-time download is ~16 GB; one-time `modal volume put` documented in `09_deployment.md` (see §"Manifest changes" — also note `09_deployment.md` needs the upload command appended).

### 11.3 — `register.py` (scaled ICP back to scene coordinates)

Per object:

1. Build initial transform `T_init`:
   - Translation = `cluster_centroid` (from `Annotation.centroid`).
   - Rotation = identity (TRELLIS doesn't preserve a canonical pose, so we deliberately let ICP find it).
   - Scale = `max(bbox_extent) / 1.0` (TRELLIS output spans ~1 unit).
2. Sample 50k points uniformly from the generated mesh surface.
3. Run scaled point-to-point ICP against the cluster's Gaussian centers, max 100 iters, threshold = 5% of bbox diagonal.
4. Apply `T_final` to the mesh vertices in place. Persist `T_final` to `positions.json` for that object.
5. Acceptance gate: `rmse < 8% of cluster bbox diagonal`. On failure → emit `register.failed` reason and route this object through `fallback.py`.

Why scaled ICP and not vanilla: TRELLIS output is in a normalized frame; without scale recovery the mesh will be the wrong size in scene coordinates. Open3D's `with_scaling=True` is the supported path. Initial transform must be reasonable or ICP will snap to a wrong basin and you will get a chair embedded in a wall — this is the demo-killer failure mode (see §"Failure paths").

### 11.4 — `fallback.py` (NKSR / Poisson on cluster point cloud)

Triggered only when generation fails (no mesh returned, non-manifold, hausdorff > τ to cluster) or registration fails RMSE gate.

1. Build oriented point cloud from the cluster's Gaussians: positions from PLY xyz, normals from the Gaussian rotation quaternion (the column of R aligned with the smallest scale; this is how the surfel synthesis defines the surface normal in `inference/poses.py`).
2. Try NKSR first:
   ```python
   import nksr, torch
   reconstructor = nksr.Reconstructor(torch.device("cuda"))
   field = reconstructor.reconstruct(points, normals)
   mesh_o3d = field.extract_dual_mesh()
   ```
3. If NKSR can't be installed (kernel build issues are the main risk on the existing CUDA 12.4 image) fall back to Open3D screened Poisson:
   ```python
   pcd = o3d.geometry.PointCloud()
   pcd.points = o3d.utility.Vector3dVector(positions)
   pcd.normals = o3d.utility.Vector3dVector(normals)
   mesh, _ = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(
       pcd, depth=9, scale=1.1, linear_fit=False
   )
   # Crop to cluster bbox to remove Poisson's unbounded extrapolation:
   mesh = mesh.crop(cluster_bbox_o3d)
   ```
4. Run the same QC + post-processing as the generative path. The output mesh is already in scene coordinates so no registration is needed.

NKSR / Poisson preserve geometric fidelity to what the Ray-Bans actually saw, but holes from occluded backsides become smooth blobs. The fallback is intentionally lower-fidelity than the generative path — it exists so that one-bad-object doesn't break the assembly.

### 11.5 — `qc.py` (per-object quality control)

Compute per object and emit `qc.json`:
- `is_watertight: bool` (`trimesh.Trimesh.is_watertight`)
- `is_manifold: bool`
- `vertex_count`, `face_count`
- `hausdorff_to_cluster_m: float` (one-sided, mesh→cluster)
- `chamfer_to_cluster_m: float`
- `bbox_iou_with_annotation: float` (registered mesh bbox vs annotation bbox)
- `path_taken: "generative" | "fallback_nksr" | "fallback_poisson"`
- `view_diversity_deg: float`
- `register_rmse: float`

Mesh is rejected from `scene.3mf` (but still written under `objects/`) if `bbox_iou_with_annotation < 0.3` — that signals the registration is so off that including it in the assembly would be misleading.

### 11.6 — `assemble.py` (final write)

1. For each accepted object:
   - Watertight repair if needed (`trimesh.repair.fill_holes` then `trimesh.repair.fix_normals`).
   - Decimate to ≤150k faces if larger (`trimesh.simplify_quadric_decimation`). SolidWorks STL importer caps at ~1M tris but performance suffers above 200k.
   - Bake TRELLIS PBR textures down to a single diffuse PNG (drop metallic/roughness — STL/3MF/Fusion360 won't carry them in our format choice).
   - Write `objects/<obj_id>.obj` + `<obj_id>.mtl` + `<obj_id>.png` + `<obj_id>.stl`.
2. Build the 3MF assembly:
   ```python
   scene = trimesh.Scene()
   for ann_id, mesh in accepted_meshes.items():
       scene.add_geometry(mesh, geom_name=ann_id, node_name=annotations[ann_id].label)
   scene.export("scene.3mf")
   ```
3. Write `positions.json` (per-object SE(3) + scale from registration).
4. Write `qc.json`.
5. Update manifest (see §"Manifest changes").

## CLI

```
just cad-export scene_id="demo_scene_v1"
# → uv run python -m cad_export --scene-id {{scene_id}}
```

`--no-fallback` disables NKSR/Poisson (useful for debugging the generative path). `--object obj_001` runs a single object end-to-end (useful for iterating on view selection / registration).

## Modal endpoint
Add to `inference/modal_app.py`:

```python
@app.function(
    gpu="H100",
    timeout=3600,
    image=image,                     # extend image with: trellis2 wheel, open3d, trimesh[easy], nksr (best-effort)
    volumes={ARTIFACTS_PATH: artifacts_volume, WEIGHTS_PATH: weights_volume},
    secrets=[modal.Secret.from_name("logfire"), modal.Secret.from_name("pydantic-gateway")],
)
@modal.fastapi_endpoint(method="POST")
def run_cad_export(scene_id: str, object_filter: list[str] | None = None) -> dict: ...
```

The per-object work is fanned out via a sub-function `cad_export_object` declared with `.map(return_exceptions=True)`. The orchestrating function consumes results, writes the assembly, and updates the manifest.

## Manifest changes
Append a `cad_export` stage to `Stages` in `shared/shared/schemas/manifest.py`:

```python
class Stages(BaseModel):
    capture: Stage
    poses: Stage
    splat: Stage
    segmentation: Stage
    cad_export: Stage = Stage(status="pending")     # new
```

Append CAD artifacts to `Artifacts`:

```python
class Artifacts(BaseModel):
    splat_ply: str
    annotations_json: str
    thumbnail_jpg: str
    cameras_json: str
    cad_scene_3mf: str | None = None                # new — null until cad_export runs
    cad_objects_dir: str | None = None              # new — directory path
```

Mirror in `shared/types/manifest.ts` (Devin's territory — flag in PR description, do not edit `/web` or `/agent` directly per the session-scope rule in CLAUDE.md).

Add to `Stats`:

```python
class Stats(BaseModel):
    frame_count: int
    object_count: int
    splat_size_mb: float
    cad_object_count: int = 0                       # new
    cad_total_face_count: int = 0                   # new
```

Update `inference/modal_app.py` to also commit the `cad/` subdirectory in the artifacts volume after `run_cad_export` finishes.

## Observability spans
Add to `08_observability.md` table:

| Span name | Module | Required attrs |
|-----------|--------|----------------|
| `cad_export.views` | cad_export | `scene_id`, `object_count`, `mean_view_diversity_deg`, `low_diversity_count` |
| `cad_export.generate` | cad_export | `scene_id`, `object_id`, `gpu`, `latency_ms`, `vertex_count`, `face_count` |
| `cad_export.register` | cad_export | `scene_id`, `object_id`, `rmse`, `scale_recovered`, `accepted` |
| `cad_export.fallback` | cad_export | `scene_id`, `object_id`, `method` (`nksr`/`poisson`), `reason` |
| `cad_export.assemble` | cad_export | `scene_id`, `accepted_count`, `rejected_count`, `assembly_face_count` |

Each span attaches `est_cost_usd` if any model call goes through the Gateway (none currently planned; TRELLIS.2 runs locally on H100, no Gateway involvement).

## Knobs (env vars; defaults in `cad_export/config.py`)

| Var | Default | Purpose |
|---|---|---|
| `CAD_VIEW_K` | `4` | Number of views per object fed to TRELLIS.2 (max 16, mem cost climbs hard above 8). |
| `CAD_VIEW_MIN_ANGLE_DEG` | `30` | Min angular separation between selected views. Below this we mark "low diversity" (back hallucination risk). |
| `CAD_VIEW_MIN_VISIBLE_FRAC` | `0.30` | Fraction of cluster points that must project inside a frame for it to be eligible. |
| `CAD_REGISTER_RMSE_FRAC` | `0.08` | RMSE / bbox-diagonal acceptance threshold for ICP. Above → fallback. |
| `CAD_ACCEPT_BBOX_IOU` | `0.30` | Per-object 3MF inclusion gate. Below → write to `objects/` only, exclude from assembly. |
| `CAD_MAX_FACES` | `150_000` | Per-object face cap; decimate above. |
| `CAD_FALLBACK` | `auto` | `auto` / `nksr` / `poisson` / `none`. `none` makes failures hard. |
| `CAD_TRELLIS_SEED` | `42` | Generation seed. Do not change without re-baking acceptance fixtures. |

## Implementation steps

Hour budget assumes one focused builder. Do not expand scope — this module is on the critical path for the user's stated demo goal but it is *new* work, so cut at any point if the rest of the demo regresses.

1. **+0:00 → +0:30** — Scaffold `cad_export/` package: `pyproject.toml`, `__init__.py`, `__main__.py`, `cli.py`, `config.py`. Add `just cad-export` recipe. Add `cad_export` stage to `Stages` (stub; status `pending`). Commit ("scaffolded with stub output").
2. **+0:30 → +2:30** — `object_views.py`: cluster slicing, projection, view scoring, angular-separation greedy selection, SAM bbox-prompted re-masking, RGBA crop output. Test against an existing demo scene; eyeball the four crops per object — if they look like four pictures of the object from genuinely different angles, you're done.
3. **+2:30 → +4:30** — TRELLIS.2 deployment on Modal. Extend `inference/modal_app.py` image (trellis2 wheel install, open3d, trimesh, nksr best-effort). One-time `modal volume put glasses-twin-weights ./trellis2/ trellis2/`. Implement `cad_export_object` per-object Modal function. Smoke on one object end-to-end (skip registration; eyeball the raw `.glb` in any GLB viewer).
4. **+4:30 → +6:00** — `register.py`: scaled ICP, init from cluster bbox, RMSE gate. **Spend the time here.** Wrong scale is the demo-killer. Check on at least 3 distinct objects (a chair, a laptop, a plant — different shape priors).
5. **+6:00 → +7:00** — `fallback.py`: at minimum the Open3D Poisson path (NKSR is a stretch — install only if the kernel build succeeds first try in the Modal image). Wire QC failure → fallback routing.
6. **+7:00 → +8:00** — `assemble.py`: 3MF + OBJ + STL writers, manifest update, `qc.json`.
7. **+8:00 → +9:00** — End-to-end on the hero scene. Open `scene.3mf` in Fusion 360. Open one of the `.stl` files in SolidWorks. Verify both render without errors.
8. **+9:00 → +10:00** — Buffer for the inevitable scale-debugging session, plus screenshots of meshes-in-Fusion for the pitch deck.

## Acceptance criteria
- For the hero scene: at least 5 of the top 8 annotated objects export with `path_taken == "generative"` and `is_watertight == True`.
- `scene.3mf` opens in Fusion 360 (file import → 3MF) without warnings, with each object as a named component.
- At least one `.stl` opens in SolidWorks (file import → STL) without warnings.
- Wall clock from `annotations.json` ready to `scene.3mf` written: **≤ 8 minutes on Modal H100** for an 8-object scene with `.map()` parallelism (TRELLIS.2 is ~30–60s/object on H100).
- `qc.json` exists and every object has all fields populated, including the failure path used.
- Manifest reflects the new stage with `status: "complete"` and accurate `cad_object_count`.

## Failure paths
- **Wrong scale after registration.** The single most likely cause of "looks wrong in Fusion": ICP converged to a local minimum because the initial scale guess was off. Mitigation: enforce scale within `[0.5, 2.0] × bbox_diag_ratio`; reject and re-run with grid-searched scales if outside. If still bad → fallback.
- **TRELLIS hallucinates absurd back of object.** Failure mode: low view diversity (selected views are too similar). Detection: `view_diversity_deg < 30` AND `hausdorff_to_cluster > 15% bbox_diag`. Mitigation: route to fallback.
- **Cluster includes adjacent object's Gaussians (segmentation bleed).** TRELLIS will dutifully generate one mesh of "the conjoined thing." Detection: bbox IoU collapses post-registration. There is no fix at this layer — this is a segmentation quality issue. Mitigation: log it, write the mesh to `objects/` for forensics, exclude from the 3MF assembly.
- **NKSR install fails on Modal.** Likely due to torch/CUDA ABI mismatch with the existing image. Mitigation: `CAD_FALLBACK=poisson` permanently; skip NKSR.
- **TRELLIS.2 weights too large to download in the Modal cold-start window (~16 GB).** Mitigation: `modal volume put` once, persist on `glasses-twin-weights`. The cold-start cost is only paid on weight upload.
- **3MF written but Fusion 360 reports "no bodies".** Cause: 3MF expects manifold meshes; non-manifold inputs silently drop. Mitigation: `trimesh.repair.fix_inversion` and `fill_holes` are in the post-process path, but verify pre-write by asserting `mesh.is_watertight` for everything that goes into the assembly.

## Out of scope
- **Mesh → BREP / STEP / IGES.** True parametric solids would need CAD-Recode or HoLa-style abstraction networks. Multi-day project. Not in this hackathon.
- **PBR materials in the final assembly.** STL drops textures entirely; 3MF carries them poorly across CAD importers. We emit textured OBJ for the object viewer and bake-down diffuse PNGs alongside, but the canonical CAD deliverable is geometry-only.
- **Per-object rerun via the web UI.** The CLI accepts `--object`, but a re-run button in `/web` is Devin's call.
- **Joint scene-level relighting.** Each object carries its own diffuse texture from TRELLIS. They will not look photometrically consistent when assembled.
- **Floor / walls / ceiling / large architectural surfaces.** TRELLIS is trained on object-scale assets; "left wall" will fail. Detection: annotation label matches `/^(wall|floor|ceiling|window|door)$/`. Force these to `path_taken == "fallback_poisson"` from the start, and crop tightly to the cluster bbox.

## Honesty caveat (must surface in the demo if shown)
The 3MF assembly is **not** a faithful capture of the room. It is a per-object hallucination conditioned on a few real views, registered into real-scene coordinates. The point cloud is what was measured; the meshes are what TRELLIS *thinks* would explain those views. For documentation/visualization this is great; for measurement, manufacturing, or anything where back-of-object geometry matters, use the fallback (Poisson) variant which preserves "what was actually seen, with holes."

## Cost target
- TRELLIS.2 inference on H100: ~30–60s/object × 8 objects, parallelized 4-wide via `.map()` → ~2 min wall clock.
- H100 at ~$4/hr × ~2 min ≈ **$0.13 per scene CAD export**.
- One-time TRELLIS.2 weight upload to volume: ~16 GB transfer.
- No Gateway / VLM cost in this module — generation is purely local on H100.

## Open questions (resolve before starting impl)
- TRELLIS.2 license — confirm Microsoft's terms allow Modal-hosted inference for hackathon-public demos. (As of CVPR'25 release: research+commercial OK; verify on the model card.)
- Do we want to ship the `objects/` directory publicly, or only `scene.3mf`? Bandwidth concern: 8 OBJs + textures + STLs ≈ 50–200 MB per scene.
- Do `/web` and `/agent` need a download button for the 3MF? If yes, this is a Devin coord — surface in PR, do not edit `/web` here per session scope.

## Coordination notes (read before opening a PR)
- This module is **session-scope new** — it does not exist in CLAUDE.md's named sessions. Treat it as an extension of Session D (Polish), since it sits downstream of segmentation and object isolation.
- `inference/modal_app.py` is shared territory — extending its image and adding `run_cad_export` is in-scope here, but do not refactor existing endpoints.
- Schema changes in `shared/shared/schemas/manifest.py` require a mirror update in `shared/types/manifest.ts` — Devin owns that file. Either coordinate or write the mirror as a suggestion in the PR description, but do not edit `/web` or `/agent`.
- `08_observability.md` should be updated with the new spans (additive change only).
- `ORCHESTRATOR.md` module-map table should grow a row 11. `05_storage.md` should append the `cad/` subtree to the layout block.
