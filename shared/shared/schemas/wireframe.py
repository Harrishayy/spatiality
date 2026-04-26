"""Wireframe index schema — maps annotation ids to point ranges in wireframe.ply.

Mirror in shared/types/wireframe.ts.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


class Range(BaseModel):
    start: int
    end: int


class WireframeIndex(BaseModel):
    point_count: int
    voxel_range: Range
    annotations: dict[str, Range] = Field(default_factory=dict)

    def write_atomic(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(self.model_dump_json(indent=2))
        os.replace(tmp, path)

    @classmethod
    def read(cls, path: Path) -> "WireframeIndex":
        return cls.model_validate_json(Path(path).read_text())
