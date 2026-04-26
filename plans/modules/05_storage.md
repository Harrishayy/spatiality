# Module 05 — Storage + schemas

## Goal
Single source of truth for scene artifacts. Flat files, no database. Lives on a Render persistent disk attached to the `/agent` service.

## Layout

```
artifacts/
  scenes/
    <scene_id>/
      capture.yaml
      frames/
        0001.png
        ...
      cameras.json
      points.ply
      splat.ply
      annotations.json
      thumbnail.jpg
      manifest.json
      cad/                       # written by cad_export (module 11)
        objects/
          obj_001.obj            # textured mesh, scene coords
          obj_001.mtl
          obj_001.png            # baked diffuse
          obj_001.stl            # geometry-only
          ...
        scene.3mf                # assembly with named parts
        positions.json           # per-object SE(3) + scale from registration
        qc.json                  # per-object QC + path_taken
```

## `manifest.json` schema (the contract)
```json
{
  "scene_id": "bedroom_v1",
  "created_at": "2026-04-25T14:23:11Z",
  "status": "ready",
  "stages": {
    "capture":      {"status": "complete", "duration_s": 8},
    "poses":        {"status": "complete", "duration_s": 1.2, "method": "vggt"},
    "splat":        {"status": "complete", "duration_s": 92,  "iterations": 7000},
    "segmentation": {"status": "complete", "duration_s": 78,  "object_count": 6},
    "cad_export":   {"status": "complete", "duration_s": 312, "accepted_count": 5, "rejected_count": 1}
  },
  "artifacts": {
    "splat_ply":         "/artifacts/scenes/bedroom_v1/splat.ply",
    "annotations_json":  "/artifacts/scenes/bedroom_v1/annotations.json",
    "thumbnail_jpg":     "/artifacts/scenes/bedroom_v1/thumbnail.jpg",
    "cameras_json":      "/artifacts/scenes/bedroom_v1/cameras.json",
    "cad_scene_3mf":     "/artifacts/scenes/bedroom_v1/cad/scene.3mf",
    "cad_objects_dir":   "/artifacts/scenes/bedroom_v1/cad/objects"
  },
  "stats": {
    "frame_count":         61,
    "object_count":        6,
    "splat_size_mb":       42,
    "cad_object_count":    5,
    "cad_total_face_count": 412503
  },
  "errors": []
}
```

`status` values: `"queued" | "processing" | "ready" | "failed"`. Stage statuses: `"pending" | "running" | "complete" | "failed"`.

## `annotations.json` schema
```json
[
  {
    "id": "obj_001",
    "label": "MacBook Air (M3)",
    "centroid": [0.42, 0.91, -1.23],
    "bbox": [[0.30, 0.85, -1.40], [0.55, 0.95, -1.10]],
    "color": "#a8b2bd",
    "confidence": 0.91,
    "alternatives": ["laptop", "MacBook"],
    "cluster_gaussian_indices": [12, 45, 78, 102]
  }
]
```

## HTTP serving
- The `/agent` Fastify service exposes `/artifacts/*` with:
  - `Cache-Control: public, max-age=3600` for `.ply` and `.jpg`
  - `Cache-Control: no-cache` for `manifest.json`
  - CORS allow-origin: the `/web` static site domain
- All writes are atomic: write to `<file>.tmp`, then `rename`.
- Manifest is the single source of truth — never serve a partial scene; the web client polls `manifest.json` until `status === "ready"`.

## Job lifecycle
1. `/web` POSTs upload → `/agent` writes scene_id directory + `capture.yaml` + frames
2. `/agent` writes `manifest.json` with `status: "queued"`
3. `/agent` triggers Modal job for `/inference`
4. Modal job updates manifest stages as they complete (mounts the same persistent disk via Modal Volume sync)
5. `/agent` triggers `/segmentation` after splat is ready
6. Final manifest written when all stages complete

## Acceptance criteria
- Stub generator produces a valid manifest + matching files for `samples/test_scene` so the web layer can build against it.
- Manifest is always parseable even mid-job (every stage has a defined status).
- Disk usage stays under 1GB per scene; cleanup script for old scenes (>7 days) runs as a daily cron.

## Open questions
- Do we need scene listing / recovery across deploys? For v1, no — single hardcoded scene id is fine for the demo.
- Multi-tenant? Not for hackathon.
