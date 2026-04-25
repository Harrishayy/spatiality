"""Round-trip every artifact in a scene through the pydantic schemas.

Usage: uv run python shared/scripts/validate.py artifacts/scenes/<scene_id>
Exits non-zero on any schema violation.
"""

from __future__ import annotations

import sys
from pathlib import Path

from shared.schemas import AnnotationsFile, CaptureYaml, Manifest


def main(scene_dir: str) -> int:
    root = Path(scene_dir)
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2

    manifest = Manifest.read(root / "manifest.json")
    print(f"manifest OK: scene_id={manifest.scene_id} status={manifest.status}")

    annotations = AnnotationsFile.read(root / "annotations.json")
    print(f"annotations OK: {len(annotations.root)} object(s)")

    capture = CaptureYaml.from_yaml(root / "capture.yaml")
    print(f"capture OK: camera_model={capture.camera_model} frames={capture.frame_count}")

    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: validate.py <scene_dir>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
