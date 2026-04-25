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
    parser.add_argument(
        "--stage",
        choices=["all", "poses", "splat"],
        default="all",
        help="Run a single stage (modal_app commits the volume between stages); 'all' is the legacy local path.",
    )
    args = parser.parse_args()

    configure_logfire("inference")
    scene = Path(args.scene_dir) if args.scene_dir else _scene_dir(args.scene_id)
    manifest_path = scene / "manifest.json"

    if args.real:
        from . import poses as _poses
        from . import splat as _splat
    else:
        _poses = _splat = None

    method = "vggt" if args.real else "stub"
    gpu_label = _detect_gpu() if args.real else "stub"
    frames_dir = scene / "frames"
    frame_count = (
        sum(1 for _ in frames_dir.glob("*.png")) + sum(1 for _ in frames_dir.glob("*.jpg"))
        if frames_dir.exists()
        else 0
    )

    poses_dur = splat_dur = 0.0
    iterations = args.iterations if args.real else 0

    if args.stage in ("all", "poses"):
        poses_dur = _run_poses(
            scene=scene,
            manifest_path=manifest_path,
            frames_dir=frames_dir,
            scene_id=args.scene_id,
            real=args.real,
            poses_module=_poses,
            method=method,
            gpu_label=gpu_label,
            frame_count=frame_count,
        )

    if args.stage in ("all", "splat"):
        splat_dur = _run_splat(
            scene=scene,
            manifest_path=manifest_path,
            frames_dir=frames_dir,
            scene_id=args.scene_id,
            real=args.real,
            splat_module=_splat,
            iterations=iterations,
            gpu_label=gpu_label,
            frame_count=frame_count,
        )

    label = "real" if args.real else "stub"
    print(
        f"inference {label} {args.stage} complete: {args.scene_id} "
        f"(poses {poses_dur:.2f}s, splat {splat_dur:.2f}s)"
    )


def _run_poses(
    *,
    scene: Path,
    manifest_path: Path,
    frames_dir: Path,
    scene_id: str,
    real: bool,
    poses_module,
    method: str,
    gpu_label: str,
    frame_count: int,
) -> float:
    manifest = Manifest.read(manifest_path)
    manifest.stages.poses.status = "running"
    manifest.write_atomic(manifest_path)

    import os as _os
    vggt_ckpt = _os.environ.get("VGGT_CHECKPOINT", "facebook/VGGT-1B") if real else "stub"
    with logfire.span(
        SPAN_INFERENCE_VGGT,
        scene_id=scene_id,
        frame_count=frame_count,
        gpu=gpu_label,
        model_id=vggt_ckpt,
    ) as span:
        t0 = time.perf_counter()
        try:
            if real:
                poses_module.run(frames_dir, scene)
            else:
                (scene / "cameras.json").write_text("[]\n")
                _stub_ply(scene / "points.ply")
        except Exception as exc:
            m = Manifest.read(manifest_path)
            m.stages.poses.status = "failed"
            m.errors.append(f"poses: {exc}")
            m.status = "failed"
            m.write_atomic(manifest_path)
            raise
        dur = time.perf_counter() - t0
        span.set_attribute("duration_s", round(dur, 3))
        try:
            import json as _json
            cams = _json.loads((scene / "cameras.json").read_text())
            span.set_attribute("cameras_written", len(cams))
        except Exception:
            pass

    m = Manifest.read(manifest_path)
    m.stages.poses.status = "complete"
    m.stages.poses.duration_s = round(dur, 4)
    m.stages.poses.method = method
    m.stats.frame_count = frame_count
    m.write_atomic(manifest_path)
    return dur


def _run_splat(
    *,
    scene: Path,
    manifest_path: Path,
    frames_dir: Path,
    scene_id: str,
    real: bool,
    splat_module,
    iterations: int,
    gpu_label: str,
    frame_count: int,
) -> float:
    m = Manifest.read(manifest_path)
    m.stages.splat.status = "running"
    m.write_atomic(manifest_path)

    with logfire.span(
        SPAN_INFERENCE_3DGRUT,
        scene_id=scene_id,
        iterations=iterations,
        gpu=gpu_label,
    ) as span:
        t0 = time.perf_counter()
        try:
            if real:
                milestones = splat_module.run(
                    frames_dir=frames_dir,
                    cameras_json=scene / "cameras.json",
                    out_ply=scene / "splat.ply",
                    iterations=iterations,
                    scene_id=scene_id,
                )
                span.set_attribute("milestones_emitted", milestones)
            else:
                _stub_ply(scene / "splat.ply")
        except Exception as exc:
            mf = Manifest.read(manifest_path)
            mf.stages.splat.status = "failed"
            mf.errors.append(f"splat: {exc}")
            mf.status = "failed"
            mf.write_atomic(manifest_path)
            raise
        dur = time.perf_counter() - t0
        span.set_attribute("duration_s", round(dur, 3))
        span.set_attribute(
            "splat_size_mb",
            round((scene / "splat.ply").stat().st_size / (1024 * 1024), 2),
        )

    splat_size_mb = (scene / "splat.ply").stat().st_size / (1024 * 1024)
    mf = Manifest.read(manifest_path)
    mf.stages.splat.status = "complete"
    mf.stages.splat.duration_s = round(dur, 4)
    mf.stages.splat.iterations = iterations
    mf.stats.frame_count = frame_count
    mf.stats.splat_size_mb = round(splat_size_mb, 2)
    # splat is enough for "ready" — segmentation is optional for the demo.
    if mf.stages.poses.status == "complete":
        mf.status = "ready"
    mf.write_atomic(manifest_path)
    return dur


def _detect_gpu() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return torch.cuda.get_device_name(0)
    except Exception:
        pass
    return "cpu"
