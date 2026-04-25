# Module 02 — Inference (the critical path)

## Goal
Take a directory of frames (from **any** video source — Ray-Ban, phone, GoPro, screen recording, drone) and produce a Gaussian splat, an extracted point cloud, and camera poses. Two run modes share the same CLI: a Kaggle-bundled offline path for early testing, and a Modal/Brev online path for the demo.

The pipeline reads `camera_model` from `capture.yaml` and selects the appropriate 3DGRUT projection. If `camera_model: generic`, VGGT estimates intrinsics and 3DGRUT runs in pinhole mode — slightly worse quality than a correct preset but robust to any input.

## Inputs
- `artifacts/scenes/<scene_id>/frames/`
- `artifacts/scenes/<scene_id>/capture.yaml`

## Outputs
- `splat.ply` — full Gaussian splat (training output of 3DGRUT)
- `points.ply` — extracted Gaussian centers as point cloud (for downstream segmentation use)
- `cameras.json` — per-frame camera poses + intrinsics in 3DGRUT-native format
- `inference.yaml`:
  ```yaml
  splat_method: 3dgrut
  pose_method: vggt
  iterations: 7000
  gpu: rtx_pro_6000
  duration_s: 142
  cost_usd: 0.42
  ```

## Tech
- **Pose estimation:** VGGT ([github.com/facebookresearch/vggt](https://github.com/facebookresearch/vggt)) — feed-forward, ~0.2s for sparse views. Subsamples ~12 keyframes from the 60-frame input.
- **Splat training:** 3DGRUT ([github.com/nv-tlabs/3dgrut](https://github.com/nv-tlabs/3dgrut)) — handles Ray-Ban's wide-angle camera natively via ray tracing.
- **GPU host:** Modal (primary) or Brev (backup). Kaggle for the early test bundle.
- **Wrapper CLI:** `python inference/train.py --scene <scene_id> [--iterations 7000]`. Same CLI on every backend; the backend is selected by env var (`INFERENCE_BACKEND=modal|kaggle|local`).

## Two run modes

### Kaggle offline (early testing, hours 1–3)
- Bundle: `bundle/wheels/`, `bundle/src/vggt/`, `bundle/src/3dgrut/`, `bundle/weights/vggt.pt`.
- Notebook installs from bundle, runs CLI, writes outputs to a Kaggle output dataset.
- Push/pull driven by `kaggle` CLI from laptop (Claude Code can drive this loop).
- See [`09_deployment.md`](./09_deployment.md) for the bundle build script.

### Modal online (production demo, hours 3+)
- `modal_app.py` defines a function `run_inference(scene_dir: str)` with `@app.function(gpu="A100", timeout=600)`.
- Image: `modal.Image.debian_slim().apt_install("git", "build-essential").pip_install_from_requirements("requirements-gpu.txt")`.
- Bind a Modal Volume for `artifacts/`. Web app calls into Modal via `modal.Function.lookup("splat-inference", "run_inference").remote(scene_id)`.
- Cold start ~30s, warm start ~5s. Keep the function warm during demo via a 60s ping cron.

## Implementation steps

1. **Hour 1:** scaffold `inference/train.py` with a stub that copies a prebaked `samples/test_scene.ply` to `splat.ply`. Downstream modules can develop against this.
2. **Hour 1.5:** wire VGGT — clone repo, write `inference/poses.py` that takes `frames/` and writes `cameras.json` + `points.ply`. Smoke-test on `samples/`.
3. **Hour 2:** wire 3DGRUT — clone repo, write `inference/splat.py` that takes `frames/` + `cameras.json` and writes `splat.ply`. Smoke-test, expect compile pain.
4. **Hour 2.5:** Kaggle bundle path — pre-download wheels, package source, push as dataset, run a smoke notebook end-to-end.
5. **Hour 3–4:** Modal app — write `modal_app.py`, deploy, smoke-test from laptop with `modal run`.
6. **Hour 4–5:** integrate into orchestrator — agent backend triggers Modal job, polls for completion, updates `manifest.json`.
7. **Hour 5+:** tune iterations for quality vs speed. Target: 5 min total wall clock from upload to splat available.

## Speed tuning
Default 3DGRUT trains for ~30k iterations. For the 5-min demo target:
- 7,000 iterations on an A100 ≈ 90s training time.
- 3,000 iterations ≈ 40s training time, viewable but rough.
- **Strategy:** train at 3,000 iterations first, expose splat to the viewer ASAP, continue training in background and stream updates. Splat file format supports this — viewer can hot-reload.

## Acceptance criteria
- Wall clock from `frames/` ready to `splat.ply` written: ≤ 3 minutes on Modal A100.
- `cameras.json` parseable by 3DGRUT viewer.
- `splat.ply` opens in [SuperSplat](https://playcanvas.com/supersplat/editor) without errors.

## Failure paths
- **VGGT poses garbage:** detect via reprojection error; fall back to COLMAP via `ns-process-data` (adds ~90s).
- **3DGRUT compile fails on Modal:** fall back to Splatfacto via Nerfstudio image. Lose Ray-Ban quality but keep pipeline.
- **Modal cold start too slow:** pre-warm by triggering one inference at hour 17 before demo.

## Out of scope
- Mesh extraction (semantic replacement is the path for Gazebo, not a real mesh).
- Per-object splats (see [`04_object_isolation.md`](./04_object_isolation.md)).
- Multi-scene compositing.

## Cost target
≤ $0.50 per scene on Modal A100. ≤ $5 total inference spend across all dev runs.
