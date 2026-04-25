# Module 10 — Kaggle offline runbook

## Goal
Run the full inference pipeline (VGGT poses + 3DGRUT splat) on a Kaggle notebook with internet **disabled** — the assumption for the RTX Pro 6000 GPU offering. Used for early testing and as a free-tier fallback if Modal/Brev fall through.

## Kaggle env (verified, April 2026)
- Python: **3.11**
- CUDA: **12.x** (`CUDA_MAJOR_VERSION=12`)
- cuDNN: `nvidia-cudnn-cu12 9.3.0.75`
- cuBLAS: `nvidia-cublas-cu12 12.5.3.2`
- PyTorch: pre-installed (verify version in pre-flight)
- Compiler stack: `nvcc`, `ninja`, `build-essential` available

(See [Kaggle/docker-python](https://github.com/Kaggle/docker-python) for the live image config.)

## Step 0 — Pre-flight verification notebook (do this first, with internet ON)

Create a throwaway Kaggle notebook with the RTX Pro 6000 selected. Run these cells and record outputs into `bundle_assumptions.md`:

```python
import sys, torch, subprocess
print("Python:", sys.version)
print("Torch:", torch.__version__, "CUDA:", torch.version.cuda, "cuDNN:", torch.backends.cudnn.version())
print(subprocess.check_output(["nvcc", "--version"]).decode())
print(subprocess.check_output(["nvidia-smi"]).decode())
print(subprocess.check_output(["pip", "list"]).decode())
```

Capture: torch version, cuda runtime, exact GPU name, all preinstalled packages. **Wheels you build locally must match these versions exactly.**

## Bundle structure

Build this on your laptop:

```
bundle/
├── wheels/                # pip-downloaded .whl files
├── src/
│   ├── vggt/              # cloned repo
│   └── 3dgrut/            # cloned repo
├── weights/
│   └── vggt.pt            # pretrained checkpoint
├── input/
│   └── capture.mp4        # test video
├── requirements.txt       # exactly what to install in notebook
├── install.sh             # idempotent install script
└── dataset-metadata.json  # for `kaggle datasets create`
```

## Step 1 — Build the wheel bundle locally

```bash
mkdir -p bundle/wheels

cat > bundle/requirements.txt <<'EOF'
opencv-python-headless==4.10.0.84
plyfile==1.1
trimesh==4.4.9
einops==0.8.0
ninja==1.11.1.1
imageio==2.35.1
imageio-ffmpeg==0.5.1
scikit-image==0.24.0
huggingface-hub==0.27.0
safetensors==0.4.5
EOF

# Match Kaggle's runtime (Python 3.11, manylinux x86_64)
pip download \
  --dest bundle/wheels \
  --platform manylinux2014_x86_64 \
  --python-version 311 \
  --implementation cp --abi cp311 \
  --only-binary=:all: \
  -r bundle/requirements.txt
```

If a wheel fails to resolve, two options: (1) drop the version pin or (2) grab the wheel manually from GitHub releases / PyPI files page and drop into `bundle/wheels/`.

**Do NOT include torch / torchvision / numpy / opencv-python** — these are already in Kaggle's image and adding them risks version conflicts.

## Step 2 — Bundle source repos

```bash
mkdir -p bundle/src
git clone --depth=1 https://github.com/facebookresearch/vggt   bundle/src/vggt
git clone --depth=1 https://github.com/nv-tlabs/3dgrut          bundle/src/3dgrut

# Strip .git to save space (40-200MB each)
rm -rf bundle/src/vggt/.git bundle/src/3dgrut/.git
```

## Step 3 — Bundle model weights

```bash
mkdir -p bundle/weights
# VGGT pretrained
wget -O bundle/weights/vggt.pt \
  https://huggingface.co/facebook/VGGT-1B/resolve/main/model.safetensors
# (Verify exact URL on the VGGT repo's HF link — they version their checkpoints.)
```

3DGRUT does not need pretrained weights — it's an optimization process. SAM 3.1 weights are only needed for segmentation; bundle them separately under `bundle/weights/sam3/`.

## Step 4 — Author the install script

`bundle/install.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail

BUNDLE_DIR="${1:-/kaggle/input/glasses-twin-bundle}"

echo "==> Installing wheels"
pip install --no-index \
  --find-links="$BUNDLE_DIR/wheels" \
  -r "$BUNDLE_DIR/requirements.txt"

echo "==> Building VGGT (no isolation, uses preinstalled torch)"
pip install --no-build-isolation --no-deps -e "$BUNDLE_DIR/src/vggt"

echo "==> Building 3DGRUT (this is the slow one — 5-15 min)"
cd "$BUNDLE_DIR/src/3dgrut"
pip install --no-build-isolation --no-deps -e .

echo "==> Smoke check"
python -c "import vggt; import threedgrut; print('OK')" || true
```

`--no-build-isolation` is mandatory: it forces setup.py to use the existing torch + nvcc instead of trying to fetch build deps over the (disabled) internet.
`--no-deps` prevents pip from trying to resolve PyPI for transitive deps that are already satisfied or already in the wheels dir.

## Step 5 — `dataset-metadata.json`

```bash
cat > bundle/dataset-metadata.json <<EOF
{
  "title": "glasses-twin-bundle",
  "id": "harrishayyanar/glasses-twin-bundle",
  "licenses": [{"name": "MIT"}]
}
EOF
```

## Step 6 — Upload as Kaggle dataset

```bash
cd bundle
kaggle datasets create -p . --dir-mode zip
# On subsequent updates:
kaggle datasets version -p . -m "added <thing>" --dir-mode zip
```

Dataset becomes available at `/kaggle/input/glasses-twin-bundle` once attached to a notebook.

## Step 7 — Author the kernel

```
kernel/
├── kernel-metadata.json
└── main.ipynb
```

`kernel-metadata.json`:
```json
{
  "id": "harrishayyanar/glasses-twin-run",
  "title": "glasses-twin-run",
  "code_file": "main.ipynb",
  "language": "python",
  "kernel_type": "notebook",
  "is_private": true,
  "enable_gpu": true,
  "enable_internet": false,
  "dataset_sources": ["harrishayyanar/glasses-twin-bundle"],
  "competition_sources": [],
  "kernel_sources": []
}
```

`main.ipynb` cells (one cell per logical block):

```python
# Cell 1 — install
!bash /kaggle/input/glasses-twin-bundle/install.sh
```

```python
# Cell 2 — extract frames from input video
import subprocess, os
os.makedirs("/kaggle/working/scene/frames", exist_ok=True)
subprocess.run([
    "ffmpeg", "-i", "/kaggle/input/glasses-twin-bundle/input/capture.mp4",
    "-vf", "fps=2",
    "/kaggle/working/scene/frames/%04d.png"
], check=True)
print("frames:", len(os.listdir("/kaggle/working/scene/frames")))
```

```python
# Cell 3 — VGGT poses + initial point cloud
from vggt.runner import run as vggt_run  # actual API may vary; verify
vggt_run(
    frames_dir="/kaggle/working/scene/frames",
    weights="/kaggle/input/glasses-twin-bundle/weights/vggt.pt",
    out_dir="/kaggle/working/scene"
)
# expects to write cameras.json + points.ply
```

```python
# Cell 4 — 3DGRUT splat training
import subprocess
subprocess.run([
    "python", "/kaggle/input/glasses-twin-bundle/src/3dgrut/scripts/train.py",
    "--frames", "/kaggle/working/scene/frames",
    "--cameras", "/kaggle/working/scene/cameras.json",
    "--out", "/kaggle/working/scene/splat.ply",
    "--iterations", "7000"
], check=True)
```

```python
# Cell 5 — verify outputs (and Kaggle output dataset)
import os
for f in ["cameras.json", "points.ply", "splat.ply"]:
    p = f"/kaggle/working/scene/{f}"
    print(f, os.path.getsize(p))
```

Outputs in `/kaggle/working/` are auto-saved as the kernel's output and downloadable via `kaggle kernels output`.

## Step 8 — Push, run, pull (from your laptop)

```bash
# Push the kernel
kaggle kernels push -p kernel/

# Poll status
watch -n 10 'kaggle kernels status harrishayyanar/glasses-twin-run'

# When complete, pull outputs
kaggle kernels output harrishayyanar/glasses-twin-run -p ./output/
```

Outputs land in `./output/` as `splat.ply`, `points.ply`, `cameras.json`.

## Step 9 — Iteration loop with Claude Code

Claude can drive the whole loop via bash:

```bash
# After you change anything in bundle/
cd bundle && kaggle datasets version -p . -m "$(date +%H:%M)" --dir-mode zip && cd ..

# After you change the kernel
kaggle kernels push -p kernel/

# Wait + pull
while true; do
  status=$(kaggle kernels status harrishayyanar/glasses-twin-run | grep -oE 'has status "[^"]+"' | cut -d'"' -f2)
  echo "$status"
  [ "$status" = "complete" ] && break
  [ "$status" = "error" ] && { echo "FAILED"; exit 1; }
  sleep 15
done
kaggle kernels output harrishayyanar/glasses-twin-run -p ./output/
```

Round-trip on a successful run: ~12–18 minutes (5 min for 3DGRUT compile + 7 min training).

## Common failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `pip install --no-index` can't resolve | wheel tags don't match Kaggle's Python/CUDA | rebuild wheels with the right `--platform` / `--python-version` |
| 3DGRUT setup.py errors during install | torch version mismatch | drop torch/torchvision from your wheels — use Kaggle's preinstalled |
| `nvcc` not found at compile | rare; image misconfigured | restart the notebook session; if persistent, file Kaggle issue |
| OOM during 3DGRUT training | iteration count too high | reduce `--iterations` to 3000 for first runs |
| VGGT runtime crashes | weight file checksum mismatch | re-download checkpoint, verify size |
| Notebook session times out at 9h | training too long | reduce iterations; or split into staged kernels |

## What stays in the bundle vs notebook

**In bundle (versioned dataset):** wheels, source repos, weights, install.sh, requirements.txt, sample input.
**In notebook:** orchestration cells, parameters, output paths.

Keep the bundle stable and bump versions sparingly — every dataset update means recomputing the install on the next run. The notebook is cheap to iterate on.

## Migration to Modal/Brev

When you graduate from Kaggle, the same `install.sh` minus `--no-index` works on Modal — Modal has internet. So the bundle is reusable as the "vendored deps" snapshot for any environment, even when internet is available.
