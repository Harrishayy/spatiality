"""Local CLI for cad_export.

Runs the full E2 → E3 → E4 → E5 → E6 orchestrator against a scene under
`artifacts/scenes/<scene_id>/`. Locally, the TRELLIS step is replaced
with `LocalGenerateStub` (forces the Open3D Poisson fallback path on
every object) so the pipeline runs without GPU + weights. On Modal the
HTTP endpoint `run_cad_export` swaps in a real TRELLIS generate runner
that fans out via `cad_export_object.map(return_exceptions=True)`.

Usage:
    just cad-export scene_id="demo_scene_v1"
    uv run python -m cad_export --scene-id demo_scene_v1
    uv run python -m cad_export --scene-id demo_scene_v1 --object obj_001
    uv run python -m cad_export --scene-id demo_scene_v1 --no-fallback
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .orchestrator import orchestrate
from .runners import FlatMaskRunner, LocalGenerateStub


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="cad_export", description=__doc__.splitlines()[0])
    p.add_argument("--scene-id", required=True, help="Scene id under artifacts/scenes/.")
    p.add_argument(
        "--object",
        action="append",
        dest="object_filter",
        default=None,
        help="Run a single annotation id end-to-end. Repeatable.",
    )
    p.add_argument(
        "--no-fallback",
        action="store_true",
        help="Disable the E5 fallback path; objects whose generative path "
             "fails are dropped from the assembly.",
    )
    p.add_argument(
        "--scenes-root",
        default="artifacts/scenes",
        help="Override the default artifacts/scenes/ root.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    scene_root = Path(args.scenes_root) / args.scene_id
    if not scene_root.exists():
        print(f"[cad_export] scene_root does not exist: {scene_root}", file=sys.stderr)
        return 2

    print(f"[cad_export] scene_id={args.scene_id} scene_root={scene_root}")
    print(
        "[cad_export] mode=local — TRELLIS is stubbed; every object is "
        "routed through Poisson fallback. Run via Modal endpoint "
        "`run_cad_export` for the full generative path."
    )
    if args.object_filter:
        print(f"[cad_export] --object filter: {args.object_filter}")

    fallback_mode = "none" if args.no_fallback else None
    result = orchestrate(
        scene_id=args.scene_id,
        scene_root=scene_root,
        object_filter=args.object_filter,
        fallback_mode=fallback_mode,  # type: ignore[arg-type]
        mask_runner=FlatMaskRunner(),
        generate_runner=LocalGenerateStub(),
    )
    print(
        f"[cad_export] done — accepted={result.assemble.accepted_count}, "
        f"rejected={result.assemble.rejected_count}, "
        f"skipped_no_fallback={len(result.skipped_no_fallback)}"
    )
    print(f"[cad_export]   3MF: {result.assemble.scene_3mf_path}")
    print(f"[cad_export]   objects/: {result.assemble.objects_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
