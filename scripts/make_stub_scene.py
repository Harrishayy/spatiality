"""Generate a complete, schema-valid stub scene at artifacts/scenes/test_scene_v0/.

This is what Devin's /web + /agent build against from hour 0. It's also what
each module CLI stub regenerates its own slice of in Sessions B/C/D.

Idempotent — safe to re-run.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from shared.paths import scene_dir as _scene_dir
from shared.schemas import (
    Annotation,
    AnnotationsFile,
    Artifacts,
    CaptureYaml,
    Manifest,
    Stage,
    Stages,
    Stats,
)

SCENE_ID = "test_scene_v0"
SCENE_DIR = _scene_dir(SCENE_ID)


def _write_min_jpeg(path: Path) -> None:
    """16×16 white JPEG placeholder. Real thumbnail comes from Session B."""
    Image.new("RGB", (16, 16), (255, 255, 255)).save(path, "JPEG", quality=80)


def _write_min_ply(path: Path, header_only: bool = True) -> None:
    """Minimal binary PLY with zero vertices. Replaced by real splat in Session B."""
    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        "element vertex 0\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "end_header\n"
    )
    path.write_bytes(header.encode("ascii"))


def _annotations() -> AnnotationsFile:
    return AnnotationsFile(
        root=[
            Annotation(
                id="obj_001",
                label="MacBook Air (M3)",
                centroid=(0.42, 0.91, -1.23),
                bbox=((0.30, 0.85, -1.40), (0.55, 0.95, -1.10)),
                color="#a8b2bd",
                confidence=0.91,
                alternatives=["laptop", "MacBook"],
                cluster_gaussian_indices=[12, 45, 78, 102],
            ),
            Annotation(
                id="obj_002",
                label="stack of books",
                centroid=(-0.31, 0.88, -1.50),
                bbox=((-0.42, 0.80, -1.62), (-0.20, 0.96, -1.38)),
                color="#7a5a3a",
                confidence=0.83,
                alternatives=["books", "pile of books"],
                cluster_gaussian_indices=[201, 202, 215, 233, 244],
            ),
        ]
    )


def _capture() -> CaptureYaml:
    return CaptureYaml(
        scene_id=SCENE_ID,
        source_video="samples/test_scene.mp4",
        duration_s=30.5,
        fps=2.0,
        frame_count=0,  # stub — Session B writes real frames
        resolution=(1920, 1080),
        camera_model="pinhole",
        fov_deg=None,
        captured_at=datetime(2026, 4, 25, 14, 23, 11, tzinfo=timezone.utc),
    )


def _manifest() -> Manifest:
    base = "/artifacts/scenes/" + SCENE_ID
    return Manifest(
        scene_id=SCENE_ID,
        created_at=datetime(2026, 4, 25, 14, 23, 11, tzinfo=timezone.utc),
        status="ready",
        stages=Stages(
            capture=Stage(status="complete", duration_s=8.0),
            poses=Stage(status="complete", duration_s=1.2, method="vggt"),
            splat=Stage(status="complete", duration_s=92.0, iterations=7000),
            segmentation=Stage(status="complete", duration_s=78.0, object_count=2),
        ),
        artifacts=Artifacts(
            splat_ply=f"{base}/splat.ply",
            annotations_json=f"{base}/annotations.json",
            thumbnail_jpg=f"{base}/thumbnail.jpg",
            cameras_json=f"{base}/cameras.json",
        ),
        stats=Stats(frame_count=0, object_count=2, splat_size_mb=0.0),
        errors=[],
    )


def main() -> None:
    SCENE_DIR.mkdir(parents=True, exist_ok=True)
    (SCENE_DIR / "frames").mkdir(exist_ok=True)
    (SCENE_DIR / "frames" / ".gitkeep").touch()

    _capture().to_yaml(SCENE_DIR / "capture.yaml")
    _annotations().write_atomic(SCENE_DIR / "annotations.json")

    # cameras.json — empty list of cameras for now; Session B fills with VGGT poses.
    (SCENE_DIR / "cameras.json").write_text("[]\n")

    _write_min_ply(SCENE_DIR / "splat.ply")
    _write_min_ply(SCENE_DIR / "points.ply")
    _write_min_jpeg(SCENE_DIR / "thumbnail.jpg")

    _manifest().write_atomic(SCENE_DIR / "manifest.json")

    print(f"stub scene written: {SCENE_DIR}")


if __name__ == "__main__":
    main()
