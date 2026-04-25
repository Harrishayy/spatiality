# Module 02 — Inference (the critical path)

## Goal
Take a directory of frames (from any video source — Ray-Ban, phone, GoPro, drone) and produce a Gaussian splat + camera poses in **<15 s on a Modal A100-80GB**, no per-scene optimisation. Output is consumable by the web viewer (Spark / `@sparkjsdev/spark`) without conversion.

The splat step is **feed-forward**: VGGT's depth + camera heads give us per-pixel world points; we wrap each pixel as an oriented anisotropic Gaussian (a "surfel"), voxel-downsample to remove cross-frame redundancy, and write the standard INRIA-layout PLY. There is no gsplat / 3DGRUT / NeRF training in the loop — that path was removed because it took ~90 s on A100 and produced visibly worse output than the surfel synthesis.

## Inputs
- `artifacts/scenes/<scene_id>/frames/` — extracted by the capture stage
- `artifacts/scenes/<scene_id>/capture.yaml`

## Outputs
- `cameras.json` — list of `{frame, extrinsic 4x4, intrinsic 3x3}` (OpenCV camera-from-world). Written by the poses stage.
- `points.ply` — binary little-endian, fields `x y z (float32)  red green blue (uchar)  confidence (float32)`. Public artifact for visual debugging; the splat stage doesn't read it.
- `surfels.npz` — per-pixel surfel arrays (`xyz`, `f_dc`, `opacity`, `log_scale`, `quat`, `conf`). Internal handoff between the poses and splat stages.
- `splat.ply` — binary little-endian INRIA layout (`x y z nx ny nz f_dc_0..2 opacity scale_0..2 rot_0..3`). Consumed unchanged by `web/app/components/SplatViewer.tsx`.

## Tech
- **Pose + depth estimation:** VGGT-1B ([github.com/facebookresearch/vggt](https://github.com/facebookresearch/vggt)) — feed-forward, per-pixel depth + per-image camera + per-pixel confidence. Runs in bf16 autocast under `torch.cuda.amp.autocast`.
- **Surfel synthesis:** NumPy-only. Per pixel: unproject depth → world point; tangent scale = `depth / focal`; normal scale = `0.3 × tangent` (flat surfel); rotation from depth-gradient normal; opacity = `logit(clip(conf, 0.1, 0.99))`; SH DC band = `(rgb - 0.5) / SH_C0`.
- **Voxel downsample:** Pure NumPy hash-grid over `np.floor(p / voxel_size)`. Keeps the highest-confidence surfel per voxel. ~100ms at 8M points.
- **GPU host:** Modal A100-80GB. Headroom is what lets us feed up to 48 frames into the O(N²) cross-attention.

## Pipeline shape

```
frames/         capture.yaml
   │                │
   ▼                ▼
┌─────────────────────────────┐
│  poses.py (stage: poses)    │      VGGT forward pass + per-pixel
│  ─────────────────────────  │  ──> surfel construction. Persists
│  bf16 autocast on A100-80GB │      cameras.json, points.ply,
└─────────────────────────────┘      surfels.npz.
              │
              ▼
┌─────────────────────────────┐
│  splat.py (stage: splat)    │      Voxel-downsample surfels.npz to
│  ─────────────────────────  │  ──> ~1–2M Gaussians. Writes splat.ply
│  CPU-only, NumPy            │      in INRIA layout.
└─────────────────────────────┘
```

The two stages are separate subprocess calls in `inference/modal_app.py` so the volume can be committed between them (the web sees `cameras.json` immediately after poses finishes, then `splat.ply` after the splat stage). Both stages run on the same A100-80GB function — the splat stage is CPU-bound but co-locating avoids the volume round-trip.

## Knobs (env vars; defaults in `inference/modal_app.py:COMMON_ENV`)

| Var | Default | Purpose |
|---|---|---|
| `VGGT_FRAMES_MAX` | `48` | Cap on frames fed to VGGT (compute is O(N²); quality saturates at 16–32). |
| `VGGT_FRAMES_MIN` | `8` | Floor — never starve VGGT after blur filtering. |
| `VGGT_FPS_TARGET` | `4.0` | Target sampling rate before blur filter (best-effort, by stride). |
| `VGGT_BLUR_DROP_PCT` | `0.20` | Drop bottom percentile by Laplacian variance — kills motion-blur frames. |
| `VGGT_DEPTH_CONF_MIN` | `0.2` | Per-pixel confidence floor; pixels below are dropped before surfel synth. |
| `VGGT_DEPTH_GRAD_MAX` | `0.05` | Relative depth-gradient max — drops silhouette-edge pixels (otherwise floaters). |
| `VGGT_VOXEL_SIZE_FRAC` | `0.005` | Voxel size as fraction of scene diagonal — controls splat count vs detail. |

## Implementation notes
- `poses.py:_select_frames` does the pre-filter (stride → blur scoring → cap → spacing-preserving truncation).
- `poses.py:_load_raw_rgb` deliberately reloads via PIL so we have un-normalised RGB for color sampling — VGGT's preprocess applies ImageNet normalisation.
- `poses.py:_basis_to_quat_wxyz` is Shepperd's method, vectorised across all kept pixels. The output quaternion order is **wxyz** (matches the existing INRIA-layout writer and the Spark viewer's decode).
- `splat.py:_voxel_downsample` uses an int64-packed voxel hash so we don't pay for tuple-keyed dicts. The per-voxel argmax loop is the only Python-level cost; vectorising via `np.maximum.at` would require sentinel handling that costs more than the loop saves at our point counts.

## Acceptance criteria
- Wall clock from `frames/` ready to `splat.ply` written: **≤ 15 s on Modal A100-80GB** (typical: VGGT ~2–4s, surfel synth ~1s, voxel downsample <1s).
- `cameras.json` parseable by Spark (already used unchanged).
- `splat.ply` opens in [SuperSplat](https://playcanvas.com/supersplat/editor) without errors and renders as oriented surface patches (not isotropic blobs).

## Failure paths
- **VGGT depth degenerate** (zero surfels survive the conf gate): raise. Check input frames + weights; the floor at `VGGT_FRAMES_MIN=8` post-filter is the upstream guard.
- **VGGT model output missing `depth` / `depth_conf`**: raise with a clear message — this build of VGGT doesn't expose the depth head (extremely unlikely with `facebook/VGGT-1B`).
- **All pixels dropped at silhouettes**: lower `VGGT_DEPTH_GRAD_MAX` or accept floaters. The current default trades a few floaters for completeness.

## Out of scope
- Mesh extraction.
- Per-object splats (see [`04_object_isolation.md`](./04_object_isolation.md)).
- View-dependent shading (SH degree > 0). Surfel synthesis is degree 0 by design; higher bands would require per-scene fitting, which is the path we removed.

## Cost target
A100-80GB at ~$3.10/hr × 15s ≈ **$0.013 per scene**. Total inference spend across all dev runs <<$5.
