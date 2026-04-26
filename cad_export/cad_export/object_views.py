"""E2 — View selection (geometric core).

Spec: 11_cad_export.md §11.1.

For each annotated object, project its cluster's Gaussian centers into
every camera, score each camera by visibility / framing / proximity,
greedy-select K cameras that are *angularly diverse* (so TRELLIS gets
genuinely different angles, not four near-duplicates), and report a
diversity flag.

The SAM bbox-prompted re-masking + RGBA crop emission step (spec §11.1
points 4–5) is pluggable via the `MaskRunner` protocol in `runners.py`
(default = FlatMaskRunner; SAM box-prompt is a TODO(swap) refinement).
The geometric core in this file is pure NumPy, needs no GPU, and is
independently fixture-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import logfire
import numpy as np
from shared.observability import SPAN_CAD_VIEWS

from . import config


@dataclass
class CameraInfo:
    """One row of cameras.json plus image dimensions."""
    frame_id: str
    K: np.ndarray                  # (3, 3) intrinsic
    Rt: np.ndarray                 # (4, 4) world→camera (OpenCV convention)
    width: int
    height: int

    @property
    def viewing_direction(self) -> np.ndarray:
        """Unit vector pointing along the camera's optical axis (+Z in cam)
        expressed in world coordinates. Used for angular-diversity scoring."""
        R = self.Rt[:3, :3]
        # World→cam Rt: cam = R @ world + t, so world-frame Z axis is R[2, :].
        z_cam = R[2, :]
        return z_cam / (np.linalg.norm(z_cam) + 1e-12)


@dataclass
class CameraScore:
    cam: CameraInfo
    score: float
    visible_fraction: float
    in_frame_fraction: float
    mean_depth: float
    edge_dist_norm: float          # in [0, 1] — fraction of half-image
    eligible: bool                 # passed visibility threshold + occlusion test


@dataclass
class ViewSelection:
    obj_id: str
    chosen_camera_ids: list[str]
    view_diversity_deg: float      # min pairwise angle between chosen cams
    low_diversity_flag: bool       # True if view_diversity_deg < min_angle_deg
    eligible_count: int            # how many cameras passed the visibility gate
    scores_debug: list[CameraScore] = field(default_factory=list, repr=False)


def project_to_image(
    points_world: np.ndarray,
    cam: CameraInfo,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Project Nx3 world points through `cam`. Returns (uv, in_front, depth_z)."""
    N = len(points_world)
    if N == 0:
        return np.empty((0, 2)), np.empty((0,), bool), np.empty((0,))
    homog = np.column_stack([points_world, np.ones(N)])
    cam_xyz = (cam.Rt @ homog.T).T[:, :3]
    in_front = cam_xyz[:, 2] > 1e-6
    proj = (cam.K @ cam_xyz.T).T
    z = np.where(in_front, cam_xyz[:, 2], 1.0)
    uv = proj[:, :2] / np.maximum(proj[:, 2:3], 1e-9)
    return uv, in_front, z


def _score_one_camera(
    cluster_centers: np.ndarray,
    full_splat_centers: np.ndarray,
    cam: CameraInfo,
    *,
    min_visible_frac: float,
    occlusion_z_margin: float = 0.05,
) -> CameraScore:
    uv, in_front, depth = project_to_image(cluster_centers, cam)
    n = len(cluster_centers)

    # In-frame mask on cluster points.
    in_x = (uv[:, 0] >= 0) & (uv[:, 0] < cam.width)
    in_y = (uv[:, 1] >= 0) & (uv[:, 1] < cam.height)
    in_frame = in_front & in_x & in_y

    in_frame_fraction = float(in_frame.sum()) / max(n, 1)

    # Occlusion test: at each cluster pixel, compare cluster depth to the
    # nearest full-splat point projecting into the same pixel. If the splat
    # has any point substantially closer to camera (margin > occlusion_z_margin
    # × cluster_depth), this cluster point is occluded.
    visible_fraction = 0.0
    if in_frame.any() and len(full_splat_centers) > 0:
        uv_splat, in_front_s, depth_s = project_to_image(full_splat_centers, cam)
        in_x_s = (uv_splat[:, 0] >= 0) & (uv_splat[:, 0] < cam.width)
        in_y_s = (uv_splat[:, 1] >= 0) & (uv_splat[:, 1] < cam.height)
        ok_s = in_front_s & in_x_s & in_y_s
        # Build a per-pixel min-depth z-buffer (coarse — bin to int pixels).
        H, W = cam.height, cam.width
        zbuf = np.full((H, W), np.inf, dtype=np.float64)
        if ok_s.any():
            ux = uv_splat[ok_s, 0].astype(np.int64).clip(0, W - 1)
            uy = uv_splat[ok_s, 1].astype(np.int64).clip(0, H - 1)
            ds = depth_s[ok_s]
            np.minimum.at(zbuf, (uy, ux), ds)
        # Visible: cluster point's depth ≤ z-buffer + margin.
        idx_visible = np.zeros(n, dtype=bool)
        if in_frame.any():
            uxc = uv[in_frame, 0].astype(np.int64).clip(0, W - 1)
            uyc = uv[in_frame, 1].astype(np.int64).clip(0, H - 1)
            dc = depth[in_frame]
            occluded = dc > zbuf[uyc, uxc] * (1.0 + occlusion_z_margin)
            sub = ~occluded
            in_frame_indices = np.flatnonzero(in_frame)
            idx_visible[in_frame_indices[sub]] = True
        visible_fraction = float(idx_visible.sum()) / max(n, 1)
    else:
        visible_fraction = in_frame_fraction

    # Mean depth over visible (or in-frame as fallback) cluster points.
    mask_for_depth = in_frame
    mean_depth = float(np.mean(depth[mask_for_depth])) if mask_for_depth.any() else float("inf")

    # Min distance from cluster's image-space centroid to image edge,
    # normalized to half-image-min-side.
    if in_frame.any():
        c = uv[in_frame].mean(axis=0)
        edge_dist = min(c[0], cam.width - c[0], c[1], cam.height - c[1])
        edge_dist_norm = float(edge_dist) / max(0.5 * min(cam.width, cam.height), 1.0)
    else:
        edge_dist_norm = 0.0

    eligible = visible_fraction >= min_visible_frac

    if not eligible or mean_depth <= 0:
        score = 0.0
    else:
        score = (
            visible_fraction
            * in_frame_fraction
            * (1.0 / mean_depth)
            * np.sqrt(max(edge_dist_norm, 0.0))
        )

    return CameraScore(
        cam=cam,
        score=float(score),
        visible_fraction=visible_fraction,
        in_frame_fraction=in_frame_fraction,
        mean_depth=mean_depth,
        edge_dist_norm=edge_dist_norm,
        eligible=eligible,
    )


def _angle_between_deg(a: np.ndarray, b: np.ndarray) -> float:
    """Smallest angle between two unit-ish vectors in degrees."""
    cos = float(np.clip(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12), -1.0, 1.0))
    return float(np.degrees(np.arccos(cos)))


def _greedy_select_with_diversity(
    sorted_scored: list[CameraScore],
    k: int,
    min_angle_deg: float,
) -> list[CameraScore]:
    """Greedy: highest-scoring camera first, then pick the next-best whose
    viewing direction is ≥ min_angle_deg away from every already-chosen
    camera. If we can't fill K under the diversity constraint, return what
    we have — the caller flags low_diversity."""
    chosen: list[CameraScore] = []
    for cs in sorted_scored:
        if not cs.eligible:
            continue
        if all(
            _angle_between_deg(cs.cam.viewing_direction, c.cam.viewing_direction)
            >= min_angle_deg
            for c in chosen
        ):
            chosen.append(cs)
            if len(chosen) >= k:
                break
    return chosen


def _min_pairwise_angle_deg(chosen: list[CameraScore]) -> float:
    if len(chosen) < 2:
        return 0.0
    angles = [
        _angle_between_deg(a.cam.viewing_direction, b.cam.viewing_direction)
        for i, a in enumerate(chosen) for b in chosen[i + 1:]
    ]
    return min(angles) if angles else 0.0


def select_views_for_object(
    obj_id: str,
    cluster_centers: np.ndarray,
    cluster_bbox: np.ndarray,
    full_splat_centers: np.ndarray,
    cameras: list[CameraInfo],
    *,
    scene_id: str = "",
    k: int = config.VIEW_K,
    min_angle_deg: float = config.VIEW_MIN_ANGLE_DEG,
    min_visible_frac: float = config.VIEW_MIN_VISIBLE_FRAC,
) -> ViewSelection:
    """Score every camera, greedy-select K diverse views, flag low diversity.

    `cluster_bbox` is accepted but not yet consumed here — the SAM bbox-prompt
    step in `emit_crops_for_views` (the TODO(swap) seam below) is what uses it.
    """
    scored = [
        _score_one_camera(
            cluster_centers, full_splat_centers, cam,
            min_visible_frac=min_visible_frac,
        )
        for cam in cameras
    ]
    eligible_count = sum(1 for s in scored if s.eligible)
    sorted_scored = sorted(scored, key=lambda s: s.score, reverse=True)
    chosen = _greedy_select_with_diversity(sorted_scored, k=k, min_angle_deg=min_angle_deg)
    diversity = _min_pairwise_angle_deg(chosen)
    low_diversity = (len(chosen) < k) or (diversity < min_angle_deg)
    return ViewSelection(
        obj_id=obj_id,
        chosen_camera_ids=[c.cam.frame_id for c in chosen],
        view_diversity_deg=diversity,
        low_diversity_flag=low_diversity,
        eligible_count=eligible_count,
        scores_debug=scored,
    )


def select_views_for_scene(
    scene_id: str,
    objects: list[tuple[str, np.ndarray, np.ndarray]],
    full_splat_centers: np.ndarray,
    cameras: list[CameraInfo],
) -> list[ViewSelection]:
    """Run E2 over every annotation. Emits the cad_export.views span.

    `objects` is a list of (obj_id, cluster_centers, cluster_bbox) tuples.
    The full splat is taken once for the occlusion test and shared across
    objects (it is independent of which annotation is being scored)."""
    with logfire.span(SPAN_CAD_VIEWS, scene_id=scene_id) as span:
        results = [
            select_views_for_object(
                obj_id=obj_id,
                cluster_centers=centers,
                cluster_bbox=bbox,
                full_splat_centers=full_splat_centers,
                cameras=cameras,
                scene_id=scene_id,
            )
            for obj_id, centers, bbox in objects
        ]
        diversities = [r.view_diversity_deg for r in results if not r.low_diversity_flag]
        mean_div = float(np.mean(diversities)) if diversities else 0.0
        low_div_count = sum(1 for r in results if r.low_diversity_flag)
        span.set_attribute("object_count", len(results))
        span.set_attribute("mean_view_diversity_deg", mean_div)
        span.set_attribute("low_diversity_count", low_div_count)
        return results


# ─── E2.2 — re-masking + crop emission ──────────────────────────────────────


def _project_bbox_to_2d(bbox_world: np.ndarray, cam: CameraInfo) -> np.ndarray:
    """Project a 3D bbox's 8 corners to 2D and return the enclosing image
    bbox in xyxy pixel coords (clamped to the image)."""
    mn, mx = bbox_world[0], bbox_world[1]
    corners = np.array([
        [mn[0], mn[1], mn[2]], [mx[0], mn[1], mn[2]],
        [mn[0], mx[1], mn[2]], [mx[0], mx[1], mn[2]],
        [mn[0], mn[1], mx[2]], [mx[0], mn[1], mx[2]],
        [mn[0], mx[1], mx[2]], [mx[0], mx[1], mx[2]],
    ])
    uv, in_front, _ = project_to_image(corners, cam)
    pts = uv[in_front]
    if len(pts) == 0:
        return np.array([0.0, 0.0, 0.0, 0.0])
    x0, y0 = pts[:, 0].min(), pts[:, 1].min()
    x1, y1 = pts[:, 0].max(), pts[:, 1].max()
    x0 = max(0.0, min(cam.width, x0))
    x1 = max(0.0, min(cam.width, x1))
    y0 = max(0.0, min(cam.height, y0))
    y1 = max(0.0, min(cam.height, y1))
    return np.array([x0, y0, x1, y1])


def _square_pad_to(rgba: np.ndarray, side: int) -> np.ndarray:
    """Square-pad an HxWx4 RGBA crop with transparent pixels, then resize
    to `side`x`side`. The output is always RGBA uint8."""
    from PIL import Image
    h, w = rgba.shape[:2]
    s = max(h, w)
    canvas = np.zeros((s, s, 4), dtype=np.uint8)
    y_off = (s - h) // 2
    x_off = (s - w) // 2
    canvas[y_off:y_off + h, x_off:x_off + w] = rgba
    img = Image.fromarray(canvas, mode="RGBA").resize((side, side), Image.LANCZOS)
    return np.asarray(img)


def emit_crops_for_views(
    obj_id: str,
    selection: ViewSelection,
    cameras_by_id: dict[str, CameraInfo],
    cluster_bbox_world: np.ndarray,
    frames_dir: Path,
    out_dir: Path,
    *,
    mask_runner=None,                # MaskRunner from runners.py; default = FlatMaskRunner
    crop_size: int = 1024,
    margin_frac: float = 0.08,
) -> dict:
    """Emit K RGBA crops for the chosen cameras.

    For each chosen camera:
      1. Load the corresponding RGB frame from `frames_dir`.
      2. Project the 3D `cluster_bbox_world` to a 2D bbox in image space.
      3. Ask `mask_runner` for an alpha mask given (image, bbox).
      4. Apply mask → alpha-matte to RGBA, expand by `margin_frac`,
         square-pad and resize to `crop_size` × `crop_size`.
      5. Write `out_dir/{i}.png`.

    Returns a per-object dict suitable for views_meta.json — mirrors the
    schema defined in cad_export/STUB.md.

    The mask runner is pluggable: `FlatMaskRunner` (default) is fine for
    TRELLIS multi-view since the crop is square-padded and silhouette
    fidelity is a quality refinement (TODO(swap) for SAM box-prompt).
    """
    from PIL import Image

    if mask_runner is None:
        from .runners import FlatMaskRunner
        mask_runner = FlatMaskRunner()

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for i, frame_id in enumerate(selection.chosen_camera_ids):
        cam = cameras_by_id.get(frame_id)
        if cam is None:
            continue
        frame_path = frames_dir / cam.frame_id
        if not frame_path.exists():
            # Try with .png/.jpg suffixed if the frame_id is a stem.
            for ext in (".png", ".jpg", ".jpeg"):
                candidate = frames_dir / f"{cam.frame_id}{ext}"
                if candidate.exists():
                    frame_path = candidate
                    break
        if not frame_path.exists():
            continue

        img_rgb = np.asarray(Image.open(frame_path).convert("RGB"))
        bbox_xyxy = _project_bbox_to_2d(cluster_bbox_world, cam)
        if bbox_xyxy[2] <= bbox_xyxy[0] or bbox_xyxy[3] <= bbox_xyxy[1]:
            continue

        mask = mask_runner.mask_for_bbox(img_rgb, bbox_xyxy)

        # Tight crop with margin.
        ys, xs = np.where(mask)
        if ys.size == 0:
            continue
        x0, x1 = int(xs.min()), int(xs.max() + 1)
        y0, y1 = int(ys.min()), int(ys.max() + 1)
        w, h = x1 - x0, y1 - y0
        mx = max(1, int(w * margin_frac))
        my = max(1, int(h * margin_frac))
        x0 = max(0, x0 - mx); y0 = max(0, y0 - my)
        x1 = min(img_rgb.shape[1], x1 + mx); y1 = min(img_rgb.shape[0], y1 + my)

        rgb_crop = img_rgb[y0:y1, x0:x1]
        mask_crop = mask[y0:y1, x0:x1]
        rgba = np.zeros((y1 - y0, x1 - x0, 4), dtype=np.uint8)
        rgba[..., :3] = rgb_crop
        rgba[..., 3] = (mask_crop.astype(np.uint8) * 255)

        squared = _square_pad_to(rgba, crop_size)
        out_path = out_dir / f"{i}.png"
        Image.fromarray(squared, mode="RGBA").save(out_path)
        written.append(str(out_path))

    meta = {
        "obj_id": obj_id,
        "chosen_camera_ids": selection.chosen_camera_ids,
        "view_diversity_deg": selection.view_diversity_deg,
        "low_diversity_flag": selection.low_diversity_flag,
        "written": written,
    }
    (out_dir.parent / "views_meta.json").write_text(__import__("json").dumps(meta, indent=2))
    return meta
