"""Inference stub — flips poses + splat stages, writes empty cameras.json + ply.

TODO(swap): Session B replaces with VGGT poses + 3DGRUT training
(plans/modules/02_inference.md).
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import logfire

from shared.observability import (
    SPAN_INFERENCE_3DGRUT,
    SPAN_INFERENCE_VGGT,
    configure_logfire,
)
from shared.paths import scene_dir as _scene_dir
from shared.schemas import Manifest


def _stub_ply(path: Path) -> None:
    path.write_bytes(
        b"ply\nformat binary_little_endian 1.0\nelement vertex 0\n"
        b"property float x\nproperty float y\nproperty float z\nend_header\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="inference")
    parser.add_argument("--scene-id", required=True)
    parser.add_argument("--scene-dir", default=None, help="Override resolved scene dir")
    parser.add_argument(
        "--real",
        action="store_true",
        help="Run real VGGT + 3DGRUT (requires bundled deps). Default: stub.",
    )
    parser.add_argument("--iterations", type=int, default=7000)
    args = parser.parse_args()

    configure_logfire("inference")
    scene = Path(args.scene_dir) if args.scene_dir else _scene_dir(args.scene_id)
    manifest_path = scene / "manifest.json"

    manifest = Manifest.read(manifest_path)
    manifest.stages.poses.status = "running"
    manifest.write_atomic(manifest_path)

    frames_dir = scene / "frames"
    frame_count = sum(1 for _ in frames_dir.glob("*.png")) + sum(
        1 for _ in frames_dir.glob("*.jpg")
    ) if frames_dir.exists() else 0

    if args.real:
        from . import poses as _poses
        from . import splat as _splat

        method = "vggt"
        gpu_label = _detect_gpu()
    else:
        _poses = _splat = None
        method = "stub"
        gpu_label = "stub"

    with logfire.span(
        SPAN_INFERENCE_VGGT,
        scene_id=args.scene_id,
        frame_count=frame_count,
        gpu=gpu_label,
    ):
        t0 = time.perf_counter()
        if args.real:
            _poses.run(frames_dir, scene)
        else:
            (scene / "cameras.json").write_text("[]\n")
            _stub_ply(scene / "points.ply")
        poses_dur = time.perf_counter() - t0

    manifest = Manifest.read(manifest_path)
    manifest.stages.poses.status = "complete"
    manifest.stages.poses.duration_s = round(poses_dur, 4)
    manifest.stages.poses.method = method
    manifest.stages.splat.status = "running"
    manifest.write_atomic(manifest_path)

    iterations = args.iterations if args.real else 0
    with logfire.span(
        SPAN_INFERENCE_3DGRUT,
        scene_id=args.scene_id,
        iterations=iterations,
        gpu=gpu_label,
    ):
        t0 = time.perf_counter()
        if args.real:
            _splat.run(
                frames_dir=frames_dir,
                cameras_json=scene / "cameras.json",
                out_ply=scene / "splat.ply",
                iterations=args.iterations,
            )
        else:
            _stub_ply(scene / "splat.ply")
        splat_dur = time.perf_counter() - t0

    splat_size_mb = (scene / "splat.ply").stat().st_size / (1024 * 1024)

    manifest = Manifest.read(manifest_path)
    manifest.stages.splat.status = "complete"
    manifest.stages.splat.duration_s = round(splat_dur, 4)
    manifest.stages.splat.iterations = iterations
    manifest.stats.frame_count = frame_count
    manifest.stats.splat_size_mb = round(splat_size_mb, 2)
    manifest.write_atomic(manifest_path)
    label = "real" if args.real else "stub"
    print(
        f"inference {label} complete: {args.scene_id} "
        f"(poses {poses_dur:.2f}s, splat {splat_dur:.2f}s, {splat_size_mb:.1f}MB)"
    )


def _detect_gpu() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return torch.cuda.get_device_name(0)
    except Exception:
        pass
    return "cpu"
