"""Annotation schema — labeled objects in a scene.

Mirror in shared/types/annotations.ts. Spec: plans/modules/05_storage.md.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, Field, RootModel

Vec3 = Annotated[tuple[float, float, float], Field()]
BBox = Annotated[tuple[tuple[float, float, float], tuple[float, float, float]], Field()]


class Annotation(BaseModel):
    id: str
    label: str
    centroid: Vec3
    bbox: BBox
    color: str
    confidence: float
    alternatives: list[str] = Field(default_factory=list)
    cluster_gaussian_indices: list[int] = Field(default_factory=list)


class AnnotationsFile(RootModel[list[Annotation]]):
    def write_atomic(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(self.model_dump_json(indent=2))
        os.replace(tmp, path)

    @classmethod
    def read(cls, path: Path) -> "AnnotationsFile":
        return cls.model_validate_json(Path(path).read_text())
