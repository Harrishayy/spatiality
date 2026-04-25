# Brev — manual fallback for inference + segmentation

> **STALE** — written for the old VGGT + 3DGRUT path. The current pipeline
> uses VGGT + per-pixel surfel synthesis (no training); the steps below
> reference 3DGRUT compile and `--iterations` flags that no longer exist.
> Re-derive from `inference/modal_app.py` if you actually need to run on
> Brev. Kept for historical reference only.

Used when Modal credits are exhausted or Modal misbehaves on demo day.
No web API; SSH in, run a script, scp results back.

## When to reach for this

- Modal cold-start consistently 60s+ during pre-demo bake.
- Modal A100 quota exhausted.

## Provision

1. New Brev workspace from the Ubuntu 22.04 + CUDA template.
2. Pick an L40 (cheaper, fine for ≤7k 3DGRUT iters) or A100 (faster).
3. SSH in.

## One-time setup

```bash
git clone <this-repo-url> ~/glasses-twin/repo
cd ~/glasses-twin/repo
bash deploy/brev/setup.sh ""    # arg 1 is repo URL; empty since we already cloned
```

This installs torch + VGGT + 3DGRUT + repo packages and downloads VGGT-1B weights (~5GB). Allow 15–25 min for the 3DGRUT CUDA extension compile (tiny-cuda-nn + cutlass).

Activate the venv and set required env vars (the script prints these at the end). Add to `~/.bashrc` if you'll reuse the workspace.

```bash
source ~/glasses-twin/venv/bin/activate
export ARTIFACTS_PATH=$HOME/glasses-twin/artifacts
export VGGT_LOCAL_WEIGHTS=$HOME/glasses-twin/weights/vggt.pt
export THREEDGRUT_ROOT=$HOME/glasses-twin/external/3dgrut
export LOGFIRE_TOKEN=...              # optional, for tracing
export PYDANTIC_GATEWAY_KEY=...        # required if running segmentation
export PYDANTIC_GATEWAY_URL=https://gateway-eu.pydantic.dev/proxy/anthropic/
```

## Per-scene run

Upload your video first:
```bash
# from your laptop
scp samples/capture.mp4 brev:~/inputs/capture.mp4
```

On the workspace:
```bash
bash ~/glasses-twin/repo/deploy/brev/run.sh ~/inputs/capture.mp4
```

Outputs land at `~/glasses-twin/artifacts/scenes/<scene_id>/`. Pull back:
```bash
# from your laptop
scp -r brev:~/glasses-twin/artifacts/scenes/<scene_id> ./output/
```

## Cost guardrails

- L40: ~$1/hr. A typical run (frame extract + VGGT + 7k 3DGRUT iter + segmentation) ≈ 8–12 min ⇒ ~$0.20.
- A100: ~$3/hr. Same run ≈ 4–6 min ⇒ ~$0.30.
- **Stop the workspace after each run.** Brev bills per minute; idle GPUs are silent budget killers.

## SAM weights

If you also run segmentation on Brev, either pre-stage SAM 3.1 weights into `~/glasses-twin/weights/sam3.pt`, or set `HF_TOKEN` so `segmentation/sam.py` snapshot-downloads them from the gated HF repo on first call. Update the env vars:
```bash
export SAM3_WEIGHTS=$HOME/glasses-twin/weights/sam3.pt    # optional pre-staged path
export SAM3_CONFIG=sam3_hiera_l.yaml
export SAM3_HF_REPO=facebook/sam3.1
export HF_TOKEN=hf_...
```

## Troubleshooting

- **`pip install -e /opt/3dgrut` fails with nvcc errors** — Brev's CUDA toolkit may not match torch. Run `nvcc --version` and `python -c "import torch; print(torch.version.cuda)"`. They must agree on the major version. If torch wants 12.x and nvcc is 11.x, run `conda install -c nvidia cuda-toolkit=12.4` or pick a different Brev image.
- **VGGT loads but inference crashes with `CUDA out of memory`** — drop `--max-frames` to 30 (in capture). VGGT-1B + 60 frames + 3DGRUT can OOM L40 (24GB).
- **3DGRUT CLI args don't match `inference/inference/splat.py` candidates** — set `INFERENCE_3DGRUT_CMD` to a JSON list of the right invocation; the wrapper uses it verbatim.

## Don't bother with Brev if

- Modal already worked once for this scene. It's strictly the slower fallback path.
- You're iterating on segmentation only — segmentation runs fine on the Modal endpoint without GPU constraint pressure.
