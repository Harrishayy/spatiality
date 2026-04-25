#!/usr/bin/env bash
# Builds the Kaggle dataset bundle: wheels + VGGT/3DGRUT source + VGGT weights + repo code.
# Run from REPO ROOT: ./bundle/build_bundle.sh [optional: path/to/capture.mp4]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUNDLE_DIR="$REPO_ROOT/bundle"
WHEELS_DIR="$BUNDLE_DIR/wheels"
SRC_DIR="$BUNDLE_DIR/src"
WEIGHTS_DIR="$BUNDLE_DIR/weights"
INPUT_DIR="$BUNDLE_DIR/input"
REPO_COPY_DIR="$BUNDLE_DIR/repo"

# Match Kaggle's runtime exactly. Verified 2026-04-25: Python 3.12, torch 2.10, CUDA 12.8.
# Override via env if Kaggle bumps again: PY=313 PLATFORM=manylinux2014_x86_64 ABI=cp313 ./build_bundle.sh
PYTHON_VERSION="${PY:-312}"
PLATFORM="${PLATFORM:-manylinux2014_x86_64}"
ABI="${ABI:-cp312}"

echo "==> Building bundle at $BUNDLE_DIR"
mkdir -p "$WHEELS_DIR" "$SRC_DIR" "$WEIGHTS_DIR" "$INPUT_DIR" "$REPO_COPY_DIR"

# ── 1. Wheels ─────────────────────────────────────────────────────────────
echo ""
echo "==> [1/5] Downloading wheels (pip download, target cp${PYTHON_VERSION} ${PLATFORM})"
# Main pull: platform-constrained wheels for compiled deps. hydra-core/antlr handled
# separately because antlr4-python3-runtime 4.9.* is sdist-only and pip refuses
# --no-binary together with --platform.
grep -vE '^(hydra-core|omegaconf|antlr4-python3-runtime)' "$BUNDLE_DIR/requirements.txt" \
  > "$BUNDLE_DIR/.requirements.main.txt"
python3 -m pip download \
  --dest "$WHEELS_DIR" \
  --platform "$PLATFORM" \
  --python-version "$PYTHON_VERSION" \
  --implementation cp --abi "$ABI" \
  --only-binary=:all: \
  -r "$BUNDLE_DIR/.requirements.main.txt"
rm -f "$BUNDLE_DIR/.requirements.main.txt"

# Pure-Python: hydra-core wheel + antlr4-python3-runtime sdist (no wheel exists for 4.9.*)
echo "    + pure-python: hydra-core (wheel) + antlr4-python3-runtime (sdist)"
python3 -m pip download \
  --dest "$WHEELS_DIR" \
  --no-deps \
  "hydra-core==1.3.2" "omegaconf==2.3.0" "antlr4-python3-runtime==4.9.3"
echo "    wheels: $(ls "$WHEELS_DIR" | wc -l | tr -d ' ') files"

# ── 2. VGGT source ────────────────────────────────────────────────────────
echo ""
echo "==> [2/5] Syncing VGGT source"
VGGT_DIR="$SRC_DIR/vggt"
if [ -d "$VGGT_DIR/.git" ]; then
  git -C "$VGGT_DIR" pull --ff-only
elif [ -d "$VGGT_DIR" ] && [ -n "$(ls -A "$VGGT_DIR" 2>/dev/null)" ]; then
  echo "    already populated (no .git from prior run); leaving as-is"
else
  git clone --depth 1 https://github.com/facebookresearch/vggt.git "$VGGT_DIR"
fi
rm -rf "$VGGT_DIR/.git"

# ── 3. 3DGRUT source ──────────────────────────────────────────────────────
echo ""
echo "==> [3/5] Syncing 3DGRUT source"
GRUT_DIR="$SRC_DIR/3dgrut"
if [ -d "$GRUT_DIR/.git" ]; then
  git -C "$GRUT_DIR" pull --ff-only
elif [ -d "$GRUT_DIR" ] && [ -n "$(ls -A "$GRUT_DIR" 2>/dev/null)" ]; then
  echo "    already populated (no .git from prior run); leaving as-is"
else
  git clone --depth 1 --recursive https://github.com/nv-tlabs/3dgrut.git "$GRUT_DIR"
fi
rm -rf "$GRUT_DIR/.git"
# Cutlass docs/ contains filenames with `[` which the Kaggle web uploader rejects.
# Header-only CUDA lib — only `include/` is used at build time.
rm -rf "$GRUT_DIR/thirdparty/tiny-cuda-nn/dependencies/cutlass/docs"

# ── 4. VGGT weights ───────────────────────────────────────────────────────
echo ""
echo "==> [4/5] Fetching VGGT weights"
VGGT_WEIGHT="$WEIGHTS_DIR/vggt.pt"
if [ -s "$VGGT_WEIGHT" ]; then
  echo "    already present: $(du -h "$VGGT_WEIGHT" | cut -f1)"
else
  # VGGT-1B is ~5GB. Update the URL if Facebook revs the checkpoint.
  curl -L --fail \
    "https://huggingface.co/facebook/VGGT-1B/resolve/main/model.safetensors" \
    -o "$VGGT_WEIGHT.tmp"
  mv "$VGGT_WEIGHT.tmp" "$VGGT_WEIGHT"
  echo "    downloaded: $(du -h "$VGGT_WEIGHT" | cut -f1)"
fi

# ── 5. Repo code (shared + inference) for offline pip install ─────────────
echo ""
echo "==> [5/5] Snapshotting repo code (shared + inference)"
rm -rf "$REPO_COPY_DIR"
mkdir -p "$REPO_COPY_DIR"
cp -R "$REPO_ROOT/shared" "$REPO_COPY_DIR/"
cp -R "$REPO_ROOT/inference" "$REPO_COPY_DIR/"
# Strip the workspace source link so Kaggle pip doesn't try to walk back to a workspace.
sed -i.bak '/\[tool.uv.sources\]/,/^$/d' "$REPO_COPY_DIR/inference/pyproject.toml"
rm -f "$REPO_COPY_DIR/inference/pyproject.toml.bak"

# ── Optional: input video ─────────────────────────────────────────────────
echo ""
VIDEO_SRC="${1:-$REPO_ROOT/samples/capture.mp4}"
if [ -f "$VIDEO_SRC" ]; then
  cp "$VIDEO_SRC" "$INPUT_DIR/capture.mp4"
  echo "==> Copied $VIDEO_SRC -> bundle/input/capture.mp4"
else
  echo "==> No input video at $VIDEO_SRC — skipping. Drop one in samples/ before pushing."
fi

# ── Required for Kaggle dataset push ──────────────────────────────────────
test -f "$BUNDLE_DIR/dataset-metadata.json" || {
  echo "ERROR: missing $BUNDLE_DIR/dataset-metadata.json" >&2; exit 1;
}

echo ""
echo "==> Bundle ready: $BUNDLE_DIR"
du -sh "$BUNDLE_DIR"
echo ""
echo "Next:"
echo "  just push-bundle    # creates or versions harrishayyanar/glasses-twin-bundle"
echo "  just push-kernel    # uploads the kernel that runs against the bundle"
echo "  just run-kernel     # waits for the kernel to finish + pulls outputs"
