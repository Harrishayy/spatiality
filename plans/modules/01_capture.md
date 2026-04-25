# Module 01 — Capture

## Goal
Take **any mp4** (Ray-Ban export, phone video, drone footage, screen recording, etc.) and produce a stable directory of frames + metadata that downstream modules can consume. The pipeline is camera-agnostic; VGGT estimates camera intrinsics + extrinsics directly from the frames in the inference stage.

## Inputs
- `samples/<name>.mp4` (during dev) or upload via /web (in production)
- Optional: `--fps` (default 2), `--max-frames` (default 60), `--camera <preset>`

## Outputs (under `artifacts/scenes/<scene_id>/`)
- `frames/0001.png` ... `frames/00NN.png` (1920×1080 max, downscaled if larger)
- `capture.yaml`:
  ```yaml
  scene_id: bedroom_v1
  source_video: samples/bedroom.mp4
  duration_s: 30.5
  fps: 2.0
  frame_count: 61
  resolution: [1920, 1080]
  camera_model: pinhole         # see "Camera presets" below
  fov_deg: null                 # set if known; auto-estimated by VGGT otherwise
  captured_at: 2026-04-25T14:23:11Z
  ```

## Camera model

`camera_model` is recorded as informational metadata only — the inference stage doesn't branch on it. VGGT estimates the per-frame intrinsics and extrinsics directly. Set `generic` for any unknown source; set a more specific value (e.g. `meta_rayban_gen2`, `fisheye`) only as a hint for human readers / later analytics.

## Tech
- Python 3.11 + ffmpeg (subprocess) + Pydantic for the yaml schema.
- One CLI script: `python capture/extract.py --video <mp4> --scene-id <id> [--fps 2]`.

## Implementation steps
1. ffmpeg extracts frames at `--fps`, output to `frames/` as zero-padded PNG.
2. Probe the video for duration + resolution + actual fps via `ffprobe -of json`.
3. Write `capture.yaml` from the probe.
4. Optional: skip frames with low motion (sharpness via Laplacian variance) to drop near-duplicates that waste VGGT compute. (Note: the inference stage already does its own Laplacian-variance pre-filter — see `inference/inference/poses.py:_select_frames`. Doing it twice doesn't hurt.)

## Acceptance criteria
- Given a 30s 1080p mp4, produces ≥ 50 PNG frames + valid `capture.yaml` in under 10 seconds.
- Idempotent: rerunning with the same `--scene-id` cleans the prior `frames/` first.
- Errors clearly if `ffmpeg`/`ffprobe` not on PATH.

## Stretch
- Detect motion blur per frame (Laplacian variance threshold) and drop blurry frames before VGGT sees them. Ray-Ban head-mount produces a lot of these and they poison the splat.
- Detect a "good orbit" segment of the video automatically (steady angular motion) and crop to it.

## Out of scope
- Live capture / streaming.
- Audio extraction (Ray-Ban records audio too — interesting future feature for narration but not v1).
- Stabilization (keep the original motion; VGGT handles it).

## File contract w/ next module (`/inference`)
`/inference` reads `frames/` and `capture.yaml` from the same scene directory. Nothing else.
