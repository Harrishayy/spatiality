"""Manifest schema — single source of truth for scene state.

Mirror in shared/types/manifest.ts. Spec: plans/modules/05_storage.md.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

StageStatus = Literal["pending", "running", "complete", "failed"]
ManifestStatus = Literal["queued", "processing", "ready", "failed"]


class Stage(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: StageStatus
    duration_s: float | None = None


class Stages(BaseModel):
    capture: Stage
    poses: Stage
    splat: Stage
    segmentation: Stage
    cad_export: Stage = Stage(status="pending")


class Artifacts(BaseModel):
    splat_ply: str
    annotations_json: str
    thumbnail_jpg: str
    cameras_json: str
    cad_scene_3mf: str | None = None
    cad_objects_dir: str | None = None


class Stats(BaseModel):
    frame_count: int
    object_count: int
    splat_size_mb: float
    cad_object_count: int = 0
    cad_total_face_count: int = 0


class Manifest(BaseModel):
    scene_id: str
    created_at: datetime
    status: ManifestStatus
    stages: Stages
    artifacts: Artifacts
    stats: Stats
    errors: list[str] = Field(default_factory=list)

    def write_atomic(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(self.model_dump_json(indent=2))
        os.replace(tmp, path)

    @classmethod
    def read(cls, path: Path) -> "Manifest":
        return cls.model_validate_json(Path(path).read_text())
