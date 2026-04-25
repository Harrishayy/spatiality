"""Capture CLI.

Default: real ffmpeg frame extraction. Falls back to stub (capture.yaml only,
no frames) when --no-extract is set or ffmpeg is unavailable — useful for
unblocking downstream stages locally.
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from pathlib import Path

import logfire

from shared.observability import SPAN_CAPTURE_EXTRACT, configure_logfire
from shared.paths import scene_dir as _scene_dir
from shared.schemas import CaptureYaml, Manifest

from .extract import FFmpegMissingError, extract, write_capture_yaml


def main() -> None:
    parser = argparse.ArgumentParser(prog="capture")
    parser.add_argument("--scene-id", required=True)
    parser.add_argument("--scene-dir", default=None, help="Override resolved scene dir")
    parser.add_argument("--video", default="samples/capture.mp4")
    parser.add_argument("--fps", type=float, default=4.0)
    parser.add_argument("--max-frames", type=int, default=400)
    parser.add_argument(
        "--camera-model",
        default="generic",
        choices=["pinhole", "meta_rayban_gen2", "fisheye", "generic"],
    )
    parser.add_argument(
        "--no-extract",
        action="store_true",
        help="Skip ffmpeg; write capture.yaml only (stub mode)",
    )
    args = parser.parse_args()

    configure_logfire("capture")
    scene = Path(args.scene_dir) if args.scene_dir else _scene_dir(args.scene_id)
    scene.mkdir(parents=True, exist_ok=True)
    (scene / "frames").mkdir(exist_ok=True)

    manifest_path = scene / "manifest.json"
    manifest = Manifest.read(manifest_path)
    manifest.stages.capture.status = "running"
    manifest.write_atomic(manifest_path)

    video = Path(args.video)
    real_run = not args.no_extract

    with logfire.span(
        SPAN_CAPTURE_EXTRACT,
        scene_id=args.scene_id,
        frame_count=0,
        source_camera=args.camera_model,
        target_fps=args.fps,
    ) as span:
        t0 = time.perf_counter()
        try:
            if real_run:
                frame_count, probe = extract(
                    video=video,
                    out_frames=scene / "frames",
                    fps=args.fps,
                    max_frames=args.max_frames,
                )
                cap = write_capture_yaml(
                    scene_dir=scene,
                    scene_id=args.scene_id,
                    video=video,
                    fps=args.fps,
                    frame_count=frame_count,
                    probe=probe,
                    camera_model=args.camera_model,
                )
                # Surface video facts on the span so the demo waterfall is
                # explanatory ("8s of 30fps Ray-Ban → 60 frames").
                span.set_attribute("video_duration_s", cap.duration_s)
                span.set_attribute("video_resolution", list(cap.resolution))
                if video.exists():
                    span.set_attribute(
                        "video_size_mb",
                        round(video.stat().st_size / (1024 * 1024), 2),
                    )
            else:
                frame_count = 0
                cap = CaptureYaml(
                    scene_id=args.scene_id,
                    source_video=str(video),
                    duration_s=0.0,
                    fps=args.fps,
                    frame_count=0,
                    resolution=(1920, 1080),
                    camera_model=args.camera_model,
                    fov_deg=None,
                    captured_at=datetime.now(timezone.utc),
                )
                cap.to_yaml(scene / "capture.yaml")
        except FFmpegMissingError as e:
            span.set_attribute("error", str(e))
            raise
        span.set_attribute("frame_count", frame_count)
        duration = time.perf_counter() - t0
        span.set_attribute("duration_s", round(duration, 3))

    manifest = Manifest.read(manifest_path)
    manifest.stages.capture.status = "complete"
    manifest.stages.capture.duration_s = round(duration, 4)
    manifest.stats.frame_count = frame_count
    manifest.write_atomic(manifest_path)
    label = "stub" if not real_run else "real"
    print(f"capture {label} complete: {args.scene_id} ({duration:.3f}s, {frame_count} frames)")
