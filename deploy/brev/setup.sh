#!/usr/bin/env bash
# One-time setup on a fresh Brev workspace (Ubuntu 22.04 + CUDA, e.g. L40 or A100).
# Usage: bash setup.sh [REPO_GIT_URL] [VGGT_WEIGHTS_URL]
# Defaults assume you've cloned the repo and are running this from `deploy/brev/`.
set -euo pipefail

WORKSPACE="${WORKSPACE:-$HOME/glasses-twin}"
REPO_URL="${1:-}"
VGGT_WEIGHTS_URL="${2:-https://huggingface.co/facebook/VGGT-1B/resolve/main/model.safetensors}"

echo "==> Workspace: $WORKSPACE"
mkdir -p "$WORKSPACE"
cd "$WORKSPACE"

# ── 1. Repo ────────────────────────────────────────────────────────────────
if [ -n "$REPO_URL" ] && [ ! -d "$WORKSPACE/repo/.git" ]; then
  git clone "$REPO_URL" repo
fi
if [ ! -d "$WORKSPACE/repo" ]; then
  echo "ERROR: pass repo git URL as arg 1, or pre-clone to $WORKSPACE/repo"; exit 1
fi
cd repo

# ── 2. System deps ─────────────────────────────────────────────────────────
echo "==> Installing apt packages"
sudo apt-get update -qq
sudo apt-get install -y -qq git build-essential ffmpeg libgl1 libglib2.0-0 \
  python3-pip python3-venv

# ── 3. Python venv ─────────────────────────────────────────────────────────
echo "==> Setting up Python venv"
python3 -m venv "$WORKSPACE/venv"
# shellcheck disable=SC1091
source "$WORKSPACE/venv/bin/activate"
pip install --upgrade pip wheel

echo "==> Installing torch + GPU stack"
# Brev workspaces ship with CUDA; pip wheels match the installed nvcc.
pip install "torch==2.4.0" "torchvision==0.19.0" "numpy<2"
pip install opencv-python-headless pillow scipy scikit-image
pip install einops huggingface-hub safetensors imageio imageio-ffmpeg
pip install ninja plyfile trimesh hydra-core omegaconf
pip install "pydantic>=2.7" "pyyaml>=6" "logfire>=0.50"
pip install "anthropic>=0.39" "scikit-learn>=1.5"

# ── 4. VGGT ────────────────────────────────────────────────────────────────
echo "==> VGGT"
mkdir -p "$WORKSPACE/external"
if [ ! -d "$WORKSPACE/external/vggt/.git" ]; then
  git clone --depth 1 https://github.com/facebookresearch/vggt.git "$WORKSPACE/external/vggt"
fi
pip install --no-build-isolation --no-deps -e "$WORKSPACE/external/vggt"

# ── 5. 3DGRUT (slow — CUDA compile) ────────────────────────────────────────
echo "==> 3DGRUT (this is the slow one — 5-15 min)"
if [ ! -d "$WORKSPACE/external/3dgrut/.git" ]; then
  git clone --depth 1 --recursive https://github.com/nv-tlabs/3dgrut.git "$WORKSPACE/external/3dgrut"
fi
pip install --no-build-isolation --no-deps -e "$WORKSPACE/external/3dgrut"

# ── 6. VGGT weights ────────────────────────────────────────────────────────
echo "==> VGGT weights"
mkdir -p "$WORKSPACE/weights"
if [ ! -s "$WORKSPACE/weights/vggt.pt" ]; then
  curl -L --fail "$VGGT_WEIGHTS_URL" -o "$WORKSPACE/weights/vggt.pt.tmp"
  mv "$WORKSPACE/weights/vggt.pt.tmp" "$WORKSPACE/weights/vggt.pt"
fi

# ── 7. Repo packages ───────────────────────────────────────────────────────
echo "==> Repo packages (editable)"
pip install -e "$WORKSPACE/repo/shared"
pip install --no-deps -e "$WORKSPACE/repo/capture"
pip install --no-deps -e "$WORKSPACE/repo/inference"
pip install --no-deps -e "$WORKSPACE/repo/segmentation"

# ── 8. Smoke ───────────────────────────────────────────────────────────────
echo "==> Smoke check"
python -c "import vggt, threedgrut, shared.schemas, inference.cli, segmentation.cli; print('imports ok')"

cat <<EOF

==> Brev workspace ready.

Next:
  source $WORKSPACE/venv/bin/activate
  export ARTIFACTS_PATH=$WORKSPACE/artifacts
  export VGGT_LOCAL_WEIGHTS=$WORKSPACE/weights/vggt.pt
  export THREEDGRUT_ROOT=$WORKSPACE/external/3dgrut
  export LOGFIRE_TOKEN=...                        # optional
  export PYDANTIC_GATEWAY_KEY=...                 # required for segmentation --real
  export PYDANTIC_GATEWAY_URL=https://gateway-eu.pydantic.dev/proxy/anthropic/

  bash $WORKSPACE/repo/deploy/brev/run.sh /path/to/capture.mp4 [scene_id]
EOF
