"""Inference orchestration — runs the poses + splat stages.

Real path: VGGT → per-pixel surfel synthesis → INRIA-format splat PLY.
No per-scene optimisation; all the geometric work happens in poses.py
while the depth grid is still in memory, splat.py only voxel-downsamples
the cached surfels.

Stub path: writes empty cameras.json + empty PLYs (used for local
dry-runs without CUDA).
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import logfire

from shared.observability import (
    SPAN_INFERENCE_SPLAT,
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
        help="Run real VGGT + surfel synthesis (requires CUDA + bundled deps). Default: stub.",
    )
    parser.add_argument(
        "--stage",
        choices=["all", "poses", "splat"],
        default="all",
        help="Run a single stage (modal_app commits the volume between stages); 'all' is the legacy local path.",
    )
    parser.add_argument(
        "--backend",
        choices=["vggt", "fastvggt"],
        default="vggt",
        help="Pose/depth backend. 'vggt' is the default; 'fastvggt' uses the "
             "token-merging fork (mystorm16/FastVGGT) for higher frame budgets.",
    )
    args = parser.parse_args()

    configure_logfire("inference")
    scene = Path(args.scene_dir) if args.scene_dir else _scene_dir(args.scene_id)
    manifest_path = scene / "manifest.json"

    if args.real:
        if args.backend == "fastvggt":
            from . import fastvggt as _poses
        else:
            from . import poses as _poses
        from . import splat as _splat
    else:
        _poses = _splat = None

    method = (f"{args.backend}-surfel") if args.real else "stub"
    gpu_label = _detect_gpu() if args.real else "stub"
    frames_dir = scene / "frames"
    frame_count = (
        sum(1 for _ in frames_dir.glob("*.png")) + sum(1 for _ in frames_dir.glob("*.jpg"))
        if frames_dir.exists()
        else 0
    )

    poses_dur = splat_dur = 0.0

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
            backend=args.backend,
        )

    if args.stage in ("all", "splat"):
        splat_dur = _run_splat(
            scene=scene,
            manifest_path=manifest_path,
            frames_dir=frames_dir,
            scene_id=args.scene_id,
            real=args.real,
            splat_module=_splat,
            method=method,
            gpu_label=gpu_label,
            frame_count=frame_count,
        )

    label = "real" if args.real else "stub"
    print(
        f"inference {label} {args.stage} ({args.backend}) complete: {args.scene_id} "
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
    backend: str = "vggt",
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
        backend=backend,
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
        cameras_written: int | None = None
        try:
            import json as _json
            cams = _json.loads((scene / "cameras.json").read_text())
            cameras_written = len(cams)
            span.set_attribute("cameras_written", cameras_written)
        except Exception:
            pass

    m = Manifest.read(manifest_path)
    m.stages.poses.status = "complete"
    m.stages.poses.duration_s = round(dur, 4)
    m.stages.poses.method = method
    # `stats.frame_count` is the on-disk capture count (may be hundreds more
    # than VGGT actually consumed). Surface the VGGT-consumed count on the
    # poses stage itself so the UI can show "N of M frames".
    if cameras_written is not None:
        m.stages.poses.frame_count = cameras_written
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
    method: str,
    gpu_label: str,
    frame_count: int,
) -> float:
    m = Manifest.read(manifest_path)
    m.stages.splat.status = "running"
    m.write_atomic(manifest_path)

    with logfire.span(
        SPAN_INFERENCE_SPLAT,
        scene_id=scene_id,
        gpu=gpu_label,
    ) as span:
        t0 = time.perf_counter()
        gaussian_count: int | None = None
        try:
            if real:
                result = splat_module.run(
                    frames_dir=frames_dir,
                    cameras_json=scene / "cameras.json",
                    out_ply=scene / "splat.ply",
                    scene_id=scene_id,
                )
                span.set_attribute("gaussian_count", result["gaussian_count"])
                gaussian_count = result["gaussian_count"]
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
    mf.stages.splat.method = method
    if gaussian_count is not None:
        mf.stages.splat.gaussian_count = gaussian_count
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
