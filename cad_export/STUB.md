# cad_export — fixture layout for downstream outcomes

This package is being filled in across outcomes E1-E7 (see
`/Users/harrishayyanar/.claude/plans/sorted-seeking-cascade.md`). E1 (this
landing) ships the schema + scaffold so E2-E6 can develop in parallel against
fixtures.

The full pipeline spec lives at `11_cad_export.md` at repo root. Read that
first; this file documents only the **fixture-shape contracts** between
outcomes — i.e. what each outcome must hand off to the next when the real
upstream isn't ready yet.

## Per-object workspace layout (during a run)

```
/tmp/cad_export/<obj_id>/
  views/
    0.png                # RGBA, 1024x1024 — written by E2, consumed by E3
    1.png
    2.png
    3.png
  views_meta.json        # written by E2 (see schema below)
  raw.glb                # written by E3 (TRELLIS output, normalized [-0.5, 0.5]^3 frame)
  registered.ply         # written by E4 (mesh in scene coords; or fallback's output from E5)
  qc.json                # written per-object by E6
```

`<obj_id>` matches `Annotation.id` from `annotations.json` (e.g. `obj_001`).

## Final per-scene output (under `artifacts/scenes/<scene_id>/cad/`)

See `11_cad_export.md` §"Outputs" — `objects/`, `scene.3mf`, `positions.json`,
`qc.json`. E6 writes this tree; E7 commits the artifacts volume.

## Hand-off schemas

### `views_meta.json` (E2 → E3 / E6)
```json
{
  "obj_id": "obj_001",
  "chosen_camera_ids": ["frame_0042", "frame_0078", "frame_0103", "frame_0190"],
  "view_diversity_deg": 47.3,
  "low_diversity_flag": false
}
```

### `positions.json` (E4 → E6)
Map of `obj_id` → registration result:
```json
{
  "obj_001": {
    "T_final": [[1,0,0,0.42], [0,1,0,0.91], [0,0,1,-1.23], [0,0,0,1]],
    "scale": 0.34,
    "rmse": 0.012,
    "accepted": true
  }
}
```

### `qc.json` (E5/E6 → manifest)
Map of `obj_id` → spec §11.5 fields:
```json
{
  "obj_001": {
    "is_watertight": true,
    "is_manifold": true,
    "vertex_count": 12480,
    "face_count": 24960,
    "hausdorff_to_cluster_m": 0.018,
    "chamfer_to_cluster_m": 0.009,
    "bbox_iou_with_annotation": 0.78,
    "path_taken": "generative",
    "view_diversity_deg": 47.3,
    "register_rmse": 0.012
  }
}
```

## Fixture seeds for fixture-driven outcomes

- **E2** consumes any baked scene under `artifacts/scenes/<scene_id>/`. The
  hero scene `demo_scene_v1` is canonical.
- **E3** consumes any 4 RGBA crops in `/tmp/cad_export/<obj_id>/views/`. To
  develop without E2 having landed, drop in any 4 hand-picked PNG crops of one
  object.
- **E4** consumes any raw `.glb`. Synthesize a fixture by applying a known
  SE(3)+scale to a unit-cube mesh and a random point cloud sampled inside the
  transformed bbox.
- **E5** consumes a cluster's positions + normals. Synthesize from a noisy
  sphere to verify Poisson; `inference/inference/poses.py:_basis_to_quat_wxyz`
  gives the rotation→normal mapping used by the real splat.
- **E6** consumes any directory of per-object `trimesh.Trimesh` instances plus
  a `path_taken` tag per object. Hand-built unit cube/sphere/cone meshes are
  enough to exercise the 3MF/OBJ/STL writers.

## What E1 ships (this commit)

- Manifest schema rows (Stage `cad_export`, `cad_scene_3mf`,
  `cad_objects_dir`, `cad_object_count`, `cad_total_face_count`).
- Package skeleton: `cli.py`, `config.py`, `__main__.py`, `pyproject.toml`.
- `just cad-export scene_id=...` recipe; CLI prints stage stub and exits 0.
- Module 11 row in `plans/ORCHESTRATOR.md` map.
- `cad/` subtree appended in `plans/modules/05_storage.md`.
- 5 `cad_export.*` spans + `modal.run_cad_export` row in
  `plans/modules/08_observability.md`.

## What E1 does NOT ship (deferred to later outcomes)

- Any of the actual stages (views, generate, register, fallback, qc, assemble).
- Modal image extension for TRELLIS / Open3D / NKSR (E3).
- The Modal `run_cad_export` HTTP endpoint (E7).
- The `modal volume put glasses-twin-weights ... trellis2/` upload step (E3).
- TS schema mirror in `shared/types/manifest.ts` and `web/app/lib/types.ts`.
