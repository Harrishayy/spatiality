#!/usr/bin/env bash
# Runs INSIDE the Kaggle kernel. Internet is OFF; installs from bundled wheels + source.
set -euo pipefail

BUNDLE_DIR="${1:-/kaggle/input/glasses-twin-bundle}"

echo "==> Verifying bundle layout"
ls "$BUNDLE_DIR" | sort
test -d "$BUNDLE_DIR/wheels"
test -d "$BUNDLE_DIR/src/vggt"
test -d "$BUNDLE_DIR/src/3dgrut"
test -f "$BUNDLE_DIR/weights/vggt.pt"

echo "==> Installing wheels (offline)"
pip install --quiet --no-index \
  --find-links="$BUNDLE_DIR/wheels" \
  -r "$BUNDLE_DIR/requirements.txt"

echo "==> Installing VGGT (no isolation, uses preinstalled torch)"
pip install --quiet --no-build-isolation --no-deps -e "$BUNDLE_DIR/src/vggt"

echo "==> Installing 3DGRUT (5-15 min — CUDA extension compile)"
pip install --no-build-isolation --no-deps -e "$BUNDLE_DIR/src/3dgrut"

echo "==> Installing repo packages (shared, inference) — also offline"
pip install --quiet --no-index --no-deps -e "$BUNDLE_DIR/repo/shared"
pip install --quiet --no-index --no-deps -e "$BUNDLE_DIR/repo/inference"

echo "==> Smoke check"
python - <<'PY'
import importlib
for mod in ["vggt", "shared.schemas", "inference.cli"]:
    try:
        importlib.import_module(mod)
        print(f"  ok: {mod}")
    except Exception as e:
        print(f"  FAIL: {mod}: {e}")
try:
    import threedgrut
    print("  ok: threedgrut")
except Exception as e:
    print(f"  WARN: threedgrut import failed (may still work via subprocess): {e}")
PY

echo "==> install.sh complete"
