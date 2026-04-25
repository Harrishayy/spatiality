"""Capture stub — flips manifest.stages.capture to complete + writes capture.yaml.

TODO(swap): Session B replaces this with real ffmpeg frame extraction
(plans/modules/01_capture.md).
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


def main() -> None:
    parser = argparse.ArgumentParser(prog="capture")
    parser.add_argument("--scene-id", required=True)
    parser.add_argument("--scene-dir", default=None, help="Override resolved scene dir")
    parser.add_argument("--video", default="samples/test_scene.mp4")
    parser.add_argument("--fps", type=float, default=2.0)
    args = parser.parse_args()

    configure_logfire("capture")
    scene = Path(args.scene_dir) if args.scene_dir else _scene_dir(args.scene_id)
    scene.mkdir(parents=True, exist_ok=True)
    (scene / "frames").mkdir(exist_ok=True)

    manifest_path = scene / "manifest.json"
    manifest = Manifest.read(manifest_path)
    manifest.stages.capture.status = "running"
    manifest.write_atomic(manifest_path)

    with logfire.span(
        SPAN_CAPTURE_EXTRACT,
        scene_id=args.scene_id,
        frame_count=0,
        source_camera="pinhole",
    ):
        t0 = time.perf_counter()
        # TODO(swap): real ffmpeg extraction. Stub writes capture.yaml only.
        CaptureYaml(
            scene_id=args.scene_id,
            source_video=args.video,
            duration_s=0.0,
            fps=args.fps,
            frame_count=0,
            resolution=(1920, 1080),
            camera_model="pinhole",
            fov_deg=None,
            captured_at=datetime.now(timezone.utc),
        ).to_yaml(scene / "capture.yaml")
        duration = time.perf_counter() - t0

    manifest = Manifest.read(manifest_path)
    manifest.stages.capture.status = "complete"
    manifest.stages.capture.duration_s = round(duration, 4)
    manifest.write_atomic(manifest_path)
    print(f"capture stub complete: {args.scene_id} ({duration:.3f}s)")
