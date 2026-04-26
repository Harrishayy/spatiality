"""TRELLIS.2 single-object smoke test.

Invokes the deployed `cad_export_object` Modal function on a fixture
view directory staged on the artifacts volume, prints the per-object
result dict, and exits.

Pre-reqs (see /Users/harrishayyanar/.claude/plans/groovy-booping-stonebraker.md):
  1. `uv run modal deploy inference/modal_app.py` succeeded with image_cad.
  2. TRELLIS weights uploaded:
     `modal volume put glasses-twin-weights ./trellis2 trellis2`
  3. 4 RGBA crops staged on artifacts volume:
     `modal volume put glasses-twin-artifacts /tmp/trellis_smoke/views \
        scenes/trellis_smoke/cad_export_views/obj_smoke`
"""
from __future__ import annotations

import json
import sys

import modal


def main() -> int:
    f = modal.Function.from_name("glasses-twin-inference", "cad_export_object")
    payload = {
        "scene_id": "trellis_smoke",
        "obj_id": "obj_smoke",
        "view_dir": "/artifacts/scenes/trellis_smoke/cad_export_views/obj_smoke",
        "out_path": "/artifacts/scenes/trellis_smoke/cad/objects/obj_smoke/raw.glb",
    }
    print(f"invoking cad_export_object with payload:\n{json.dumps(payload, indent=2)}\n")
    result = f.remote(payload)
    print("result:")
    print(json.dumps(result, indent=2, default=str))
    if not result.get("success"):
        print(f"\nFAILED: {result.get('failure_reason')}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
