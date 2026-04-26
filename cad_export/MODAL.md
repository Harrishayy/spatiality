# cad_export — Modal deployment guide

Operational notes for deploying module 11 (CAD export) to Modal. The full
module spec lives at [`11_cad_export.md`](../11_cad_export.md); the
decentralised outcome plan lives at
`/Users/harrishayyanar/.claude/plans/sorted-seeking-cascade.md`. This file
covers only the Modal-specific bits: what gets added to the existing
`inference/modal_app.py`, how to deploy it, and how to smoke-test.

## What this branch adds

`inference/modal_app.py` is touched in **one** appended block at the end of
the file. Nothing above it is modified — `image`, `COMMON_ENV`,
`run_inference`, `_inference_async`, `run_segmentation`, `process_video`,
`prepare_scene`, and `get_artifact` are byte-identical to main.

Three new top-level definitions:

| Name | Type | Notes |
|------|------|-------|
| `image_cad` | Modal Image | **Derived** from `image` via `.pip_install(...).run_commands(...)`. Adds Open3D + trimesh + lxml + networkx + TRELLIS.2 (git-clone install) + the `cad_export` package itself. NKSR is intentionally not included — see "Failure modes" below. |
| `COMMON_ENV_CAD` | dict | `{**COMMON_ENV, ...}`. Adds `TRELLIS_WEIGHTS_DIR=/weights/trellis2`, `HF_HOME=/weights/trellis2/.hf`, `CAD_FALLBACK=poisson`, plus the spec §"Knobs" defaults. |
| `cad_export_object` | `@app.function` | Per-object work unit on H100. Loads K=4 RGBA crops from `view_dir`, runs TRELLIS.2-4B `run_multi_image`, writes `raw.glb`, returns the result dict. Designed for `.map(return_exceptions=True)` fan-out. |
| `run_cad_export` | `@app.function` + `@modal.fastapi_endpoint` | Top-level HTTP endpoint. Composes E2 → E3 (`cad_export_object.map`) → E4 → E5 → E6 in one call. Reads inputs from the artifacts volume, writes `cad/` outputs, mutates `manifest.json`. |

Both new endpoints reference `image=image_cad`. The original endpoints
continue to reference `image=image` and are unaffected if `image_cad`
fails to build.

## One-time setup

### 1. TRELLIS.2 weights → Modal Volume

```bash
# From any machine with bandwidth + ~16 GB free disk:
huggingface-cli download microsoft/TRELLIS.2-4B --local-dir ./trellis2

# Push to the existing weights Volume (alongside vggt.pt + sam3-snapshot/):
modal volume put glasses-twin-weights ./trellis2 trellis2
```

`COMMON_ENV_CAD` points `TRELLIS_WEIGHTS_DIR=/weights/trellis2` and
`HF_HOME=/weights/trellis2/.hf` so this directory is what `from_pretrained`
reads from. Skipping this step is technically OK (HF cache will pull on
first cold-start) but adds ~15 min to the first invocation.

### 2. Secrets

`run_cad_export` needs the same `logfire` + `r2-credentials` secrets that
the inference endpoints already use. No new Modal Secret is required.
`cad_export_object` needs `logfire` only.

If TRELLIS's HF repo ever becomes gated, attach `HF_SECRET` to
`cad_export_object` as well — the existing one defined in `modal_app.py`
already covers this case.

### 3. Deploy

```bash
just modal-deploy
# or directly:
uv run modal deploy inference/modal_app.py
```

**Expected first deploy time: 30–60 min.** Breakdown:
- Existing `image` rebuild: same as before (~3–5 min, layer-cached after first).
- `image_cad` net-new layers:
  - Open3D + trimesh + lxml + networkx pip install: ~1–2 min.
  - TRELLIS.2 git clone + `pip install --no-build-isolation -e`: typically
    25–45 min because the install pulls + compiles flash-attn and/or xformers.
    This is the single biggest unknown — see "Failure modes".
  - `cad_export` editable install: <30 s.

Subsequent deploys with no `cad_export/` source changes hit the layer cache
and finish in <2 min. Edits to `cad_export/` only invalidate the final two
layers (the local-dir copy and the editable pip install).

After deploy, the CLI prints the URL for both new endpoints. Capture
`run-cad-export`'s URL — that's what you POST to.

## Smoke test (post-deploy)

Minimal sanity check that the endpoint is reachable and the orchestrator
loads cleanly. Replace `<URL>` with the value Modal logged on deploy.

```bash
# Confirm the endpoint exists and the cad_export package imports cleanly
# inside the container. This will fail with a clear error if the orchestrator
# can't load the scene's annotations.json — that's the expected outcome
# until you have a real scene to point it at.
curl -fsS -X POST "<URL>" \
  -H 'content-type: application/json' \
  -d '{"scene_id": "demo_scene_v1"}'
```

Expected good response (after a real scene is staged on the artifacts volume):

```json
{
  "scene_id": "demo_scene_v1",
  "accepted_count": 5,
  "rejected_count": 1,
  "skipped_no_fallback": [],
  "triggered_by": {"obj_001": "generative", "obj_002": "low_view_diversity:auto_nksr", ...},
  "scene_3mf_path": "/artifacts/scenes/demo_scene_v1/cad/scene.3mf",
  "qc_json_path": "/artifacts/scenes/demo_scene_v1/cad/qc.json",
  "total_face_count": 412503
}
```

Inspect Logfire after the run — every spec-required `cad_export.*` span
should appear:
`cad_export.views`, `cad_export.generate` (one per object via `.map`),
`cad_export.register`, `cad_export.fallback`, `cad_export.assemble`, plus
the `modal.run_cad_export` wrapper span.

## Failure modes

### TRELLIS install fails on Modal

Most likely cause: flash-attn or xformers fail to compile against the
existing CUDA 12.4 / torch 2.4.0 base. **What it looks like**:
`modal deploy` prints a build error during the
`pip install --no-build-isolation -e /opt/trellis2` step. The deploy
*partially* succeeds — `image` (vanilla) builds and serves, only `image_cad`
is unhealthy.

Remediation in order of preference:
1. Read the actual compile error in the deploy log. Often it's a single
   missing apt package; the existing image already has `git`,
   `build-essential`, `clang`, but TRELLIS may want `cmake`, `ninja-build`,
   or specific `libstdc++` versions.
2. Pin TRELLIS to a known-good commit instead of `--depth 1` HEAD:
   `git clone https://github.com/microsoft/TRELLIS.2.git /opt/trellis2 && cd /opt/trellis2 && git checkout <known-good-sha>`
3. If the failure is in flash-attn or xformers specifically, consider
   adding `pip install flash-attn xformers` to a layer above the TRELLIS
   clone (so they're cached separately) and pin compatible versions.
4. Last resort: comment out the TRELLIS-related pip install in `image_cad`
   and rely entirely on `LocalGenerateStub` (every object goes through
   Poisson fallback). Output is honest-but-low-fidelity but the pipeline
   ships. This is the "scoped retreat" path.

The original `image`, `run_inference`, `run_segmentation`, etc. are
**not** affected by `image_cad` build failures — they're independent Image
objects.

### NKSR not installed

By design. The CUDA-kernel build is brittle on CUDA 12.4 (per spec §"Failure
paths"). `image_cad` does not include NKSR; `cad_export.fallback._try_nksr`
returns `None` cleanly when the import fails; `COMMON_ENV_CAD` pins
`CAD_FALLBACK=poisson` so the auto-mode probe is skipped entirely. This is
expected behaviour — the trace will show `cad_export.fallback.method=poisson`
on every fallback object. Only relevant if someone insists on `nksr` for
a fidelity-critical demo scene; in that case wire the kernel build into
`image_cad` and re-deploy.

### `run_cad_export` returns 500 with `RuntimeError: cad_export produced 0 assets`

Means every object was skipped. Most common causes:
1. `--no-fallback` (i.e. `payload.fallback == "none"`) was passed and the
   generative path failed on every object. Drop the flag, redeploy if it
   was set in env, or pass `"fallback": "auto"` in the payload.
2. The annotations file is empty or `object_filter` didn't match any id.
3. TRELLIS hit a uniform failure (e.g. weights missing, OOM) AND
   `CAD_FALLBACK=none` is set in env. Check Logfire for the per-object
   `cad_export.generate` spans.

### Cold-start weight download

If you skipped the `modal volume put` step, the first call to TRELLIS
will pull weights from HuggingFace into `/weights/trellis2/.hf`. Adds
~15 min one-time. Subsequent calls hit the cache. Pre-uploading is
strongly preferred.

### Volume drift between deploys

Modal Volumes persist across deploys; `image_cad` does **not** rewrite
`/weights/trellis2`. Re-deploying just rebuilds the image; the weights
stay put.

## Rollback / disabling

If you need to disable `cad_export` quickly without rolling back the
inference deploy:

- **Option A** — comment out the two `@app.function`-decorated blocks
  (`cad_export_object` and `run_cad_export`) at the bottom of
  `modal_app.py`, then `modal deploy`. The endpoints disappear; the
  inference endpoints stay healthy. `image_cad` still builds (it's still
  referenced), but if you also want to skip the build, comment out the
  `image_cad = ( ... )` block too.
- **Option B** — leave the code in place, just stop calling the endpoint.
  The function exists but consumes no resources unless invoked.

Reverting the schema changes in `shared/shared/schemas/manifest.py` is
**not** necessary for rollback — the new fields are all defaulted, so
removing them later doesn't break existing manifests.

## Cost notes

H100 on Modal is ~$4/hr. Per-scene CAD export budget:
- TRELLIS generation: ~30–60 s/object × N objects, parallelised 4-wide via
  `.map()`. For 8 objects: ~2 min wall clock.
- E2 + E4 + E5 + E6 are CPU-bound and cheap.
- Estimated **~$0.13 per scene**.
- One-time TRELLIS weight upload: ~16 GB of network ingress to Modal.
- No Pydantic Gateway / VLM cost in this module — TRELLIS runs purely
  local on H100, no model API calls.

## TS schema mirror

`shared/types/manifest.ts` and `web/app/lib/types.ts` need the same fields appended:

```typescript
// In the Stages interface:
cadExport?: Stage;            // optional; default Stage(status='pending') in Python

// In Artifacts:
cadScene3mf?: string;
cadObjectsDir?: string;

// In Stats:
cadObjectCount?: number;
cadTotalFaceCount?: number;
```

Use whatever naming convention the rest of the TypeScript side already uses
(Python uses snake_case; TS may use camelCase + a serializer in agent/) and
keep both mirrors consistent.
