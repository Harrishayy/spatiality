"""Capture schema — per-scene capture metadata written by /capture.

Spec: plans/modules/01_capture.md (camera presets) + plans/modules/05_storage.md.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

CameraModel = Literal["pinhole", "meta_rayban_gen2", "fisheye", "generic"]


class CaptureYaml(BaseModel):
    scene_id: str
    source_video: str
    duration_s: float
    fps: float
    frame_count: int
    resolution: tuple[int, int]
    camera_model: CameraModel
    fov_deg: float | None = None
    captured_at: datetime

    def to_yaml(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.model_dump(mode="json")
        # Preserve resolution as a flow-style list, not a YAML tuple.
        data["resolution"] = list(self.resolution)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(yaml.safe_dump(data, sort_keys=False))
        tmp.replace(path)

    @classmethod
    def from_yaml(cls, path: Path) -> "CaptureYaml":
        return cls.model_validate(yaml.safe_load(Path(path).read_text()))
