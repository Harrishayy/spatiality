"""Real frame extraction via ffmpeg + ffprobe.

Spec: plans/modules/01_capture.md.
Idempotent: clears prior frames/ before re-extracting.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from shared.schemas import CameraModel, CaptureYaml


class FFmpegMissingError(RuntimeError):
    pass


def _require(binary: str) -> str:
    path = shutil.which(binary)
    if not path:
        raise FFmpegMissingError(f"{binary} not on PATH — install ffmpeg before running capture")
    return path


def _probe(video: Path) -> dict:
    ffprobe = _require("ffprobe")
    out = subprocess.check_output(
        [
            ffprobe, "-v", "error", "-print_format", "json",
            "-show_streams", "-show_format", str(video),
        ],
        stderr=subprocess.STDOUT,
    )
    return json.loads(out)


def _video_stream(probe: dict) -> dict:
    for s in probe["streams"]:
        if s.get("codec_type") == "video":
            return s
    raise RuntimeError("no video stream in input")


def _parse_fps(rate: str) -> float:
    if "/" in rate:
        num, den = rate.split("/")
        d = float(den)
        return float(num) / d if d else 0.0
    return float(rate)


def extract(
    video: Path,
    out_frames: Path,
    fps: float = 4.0,
    max_frames: int | None = 400,
    target_long_side: int = 1920,
) -> tuple[int, dict]:
    """Extract frames at `fps`, downscaled if long side > `target_long_side`.

    Returns (frame_count, probe_info).
    """
    ffmpeg = _require("ffmpeg")
    video = Path(video)
    if not video.exists():
        raise FileNotFoundError(video)

    # Idempotent: wipe prior frames.
    if out_frames.exists():
        for f in out_frames.glob("*"):
            if f.is_file():
                f.unlink()
    out_frames.mkdir(parents=True, exist_ok=True)

    probe = _probe(video)
    vs = _video_stream(probe)
    src_w = int(vs.get("width", 0))
    src_h = int(vs.get("height", 0))
    long_side = max(src_w, src_h)
    scale_filter = ""
    if long_side > target_long_side and long_side > 0:
        # Preserve aspect ratio. Pick whichever side is longer to scale.
        if src_w >= src_h:
            scale_filter = f",scale={target_long_side}:-2"
        else:
            scale_filter = f",scale=-2:{target_long_side}"

    vf = f"fps={fps}{scale_filter}"
    cmd = [ffmpeg, "-y", "-i", str(video), "-vf", vf]
    if max_frames:
        cmd += ["-frames:v", str(max_frames)]
    cmd += [str(out_frames / "%04d.png")]

    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    frames = sorted(out_frames.glob("*.png"))
    return len(frames), probe


def write_capture_yaml(
    scene_dir: Path,
    scene_id: str,
    video: Path,
    fps: float,
    frame_count: int,
    probe: dict,
    camera_model: CameraModel = "generic",
) -> CaptureYaml:
    vs = _video_stream(probe)
    duration_s = float(probe.get("format", {}).get("duration", 0.0))
    src_fps = _parse_fps(vs.get("avg_frame_rate", "0/1"))
    width = int(vs.get("width", 0))
    height = int(vs.get("height", 0))

    cap = CaptureYaml(
        scene_id=scene_id,
        source_video=str(video),
        duration_s=round(duration_s, 3),
        fps=fps,
        frame_count=frame_count,
        resolution=(width, height),
        camera_model=camera_model,
        fov_deg=None,
        captured_at=datetime.now(timezone.utc),
    )
    cap.to_yaml(scene_dir / "capture.yaml")
    # Stash original fps as a sidecar fact for later analysis.
    (scene_dir / "capture.probe.json").write_text(
        json.dumps({"src_fps": src_fps, "src_resolution": [width, height]}, indent=2)
    )
    return cap
