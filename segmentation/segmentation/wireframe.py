"""Wireframe artifact builder.

Produces two files used by the viewer's Wireframe view mode:

- ``wireframe.ply`` — a reduced-resolution point cloud combining
  (1) a uniform 5 cm voxel-downsample of ``points.ply`` (background) and
  (2) per-annotation dense samples drawn from the points.ply points that
  spatially correspond to each annotation's splat-Gaussian cluster
  (the same ``cluster_gaussian_indices`` already produced by
  :func:`lift_masks.cluster_via_masks`).
- ``wireframe_index.json`` — maps each annotation id and the voxel
  background to ``{start, end}`` ranges into the wireframe.ply point
  array, so the viewer can color/highlight per object without re-doing
  any spatial work.

The mapping splat→points is a KDTree query at ``RADIUS`` (default 6 cm)
because the segmentation pipeline emits per-object Gaussian indices
into ``splat.ply`` (~1.3 M Gaussians, the INRIA splat) but the viewer
renders ``points.ply`` (~12 M dense pixel points). Both clouds live in
the same VGGT world frame, so a small radius pulls in every points.ply
point on the same surface as a cluster's Gaussians.

Span: ``wireframe.build``. Demo evidence per 08_observability.md.
"""

from __future__ import annotations

from pathlib import Path

import logfire
import numpy as np
from scipy.spatial import cKDTree

from shared.observability import SPAN_WIREFRAME_BUILD
from shared.schemas import AnnotationsFile, Range, WireframeIndex

from .lift_masks import _fast_load


VOXEL_SIZE = 0.05            # 5 cm grid for the background downsample
PER_OBJECT_SAMPLE = 500      # max points emitted per annotation
MATCH_RADIUS = 0.06          # splat→points spatial match radius (m)


def _load_points_ply(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Read points.ply → (xyz Float32 [N,3], rgb Uint8 [N,3]).

    points.ply is binary little-endian with float32 x/y/z and uchar
    red/green/blue (and possibly a float32 confidence field). We mmap it
    once and slice columns rather than going through plyfile which
    materializes a structured numpy array.
    """
    raw = path.read_bytes()
    end = raw.find(b"end_header\n")
    if end < 0:
        raise ValueError(f"{path}: no end_header")
    header = raw[: end + len(b"end_header\n")].decode("ascii", "replace")
    if "format binary_little_endian 1.0" not in header:
        raise ValueError(f"{path}: not little-endian binary PLY")

    n: int | None = None
    props: list[tuple[str, str]] = []  # (name, type)
    for line in header.splitlines():
        if line.startswith("element vertex "):
            n = int(line.split()[2])
        elif line.startswith("property "):
            parts = line.split()
            props.append((parts[2], parts[1]))
    if n is None:
        raise ValueError(f"{path}: missing vertex count")
    if n == 0:
        return np.zeros((0, 3), dtype=np.float32), np.zeros((0, 3), dtype=np.uint8)

    sizes = {"float": 4, "float32": 4, "uchar": 1, "uint8": 1}
    stride = sum(sizes[t] for _, t in props)
    body = raw[end + len(b"end_header\n") :]
    if len(body) < stride * n:
        raise ValueError(f"{path}: truncated body")

    # Build an offset table so we can pull columns out of a single buffer.
    offsets: dict[str, tuple[int, str]] = {}
    off = 0
    for name, t in props:
        offsets[name] = (off, t)
        off += sizes[t]

    arr = np.frombuffer(body, dtype=np.uint8, count=stride * n).reshape(n, stride)
    xyz = np.empty((n, 3), dtype=np.float32)
    for i, axis in enumerate(("x", "y", "z")):
        a_off, _ = offsets[axis]
        xyz[:, i] = arr[:, a_off : a_off + 4].copy().view(np.float32).reshape(n)
    rgb = np.empty((n, 3), dtype=np.uint8)
    for i, ch in enumerate(("red", "green", "blue")):
        c_off, _ = offsets[ch]
        rgb[:, i] = arr[:, c_off]
    return xyz, rgb


def _voxel_downsample(
    xyz: np.ndarray, rgb: np.ndarray, voxel: float
) -> tuple[np.ndarray, np.ndarray]:
    """One representative point per voxel cell.

    Keeps the *first* point that lands in each cell (np.unique on the
    integer cell key with ``return_index=True``). Cheap and stable: any
    deterministic representative reads as a uniform sparsification.
    """
    if xyz.shape[0] == 0:
        return xyz, rgb
    keys = np.floor(xyz / voxel).astype(np.int64)
    # Pack (i, j, k) into a single int64 key for unique-ing. Each axis
    # gets 21 bits (signed, biased to non-negative), supporting ±1.05 km
    # of capture extent at 5 cm — safely beyond any single VGGT scene.
    BIAS = 1 << 20
    packed = (
        ((keys[:, 0] + BIAS) & 0x1FFFFF) << 42
        | ((keys[:, 1] + BIAS) & 0x1FFFFF) << 21
        | ((keys[:, 2] + BIAS) & 0x1FFFFF)
    )
    _, idx = np.unique(packed, return_index=True)
    idx.sort()  # preserve input order so neighbouring cells stay coherent
    return xyz[idx], rgb[idx]


def _write_ply(
    path: Path, xyz: np.ndarray, rgb: np.ndarray
) -> None:
    """Binary-LE PLY writer matching the viewer's expected layout."""
    n = int(xyz.shape[0])
    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        f"element vertex {n}\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "property uchar red\n"
        "property uchar green\n"
        "property uchar blue\n"
        "end_header\n"
    ).encode("ascii")
    # Interleave xyz (float32 LE) + rgb (uchar) per vertex.
    buf = bytearray(len(header) + n * 15)
    buf[: len(header)] = header
    o = len(header)
    xyz_le = np.ascontiguousarray(xyz, dtype="<f4")
    rgb_u8 = np.ascontiguousarray(rgb, dtype=np.uint8)
    # Vectorized layout: build a (n, 15) byte block, then flatten.
    block = np.empty((n, 15), dtype=np.uint8)
    block[:, :12] = xyz_le.view(np.uint8).reshape(n, 12)
    block[:, 12:] = rgb_u8
    buf[o : o + n * 15] = block.tobytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(bytes(buf))
    tmp.replace(path)


def build_wireframe(scene_dir: Path, scene_id: str) -> Path:
    """Build wireframe.ply + wireframe_index.json under ``scene_dir``.

    Returns the path to wireframe.ply. Idempotent: rewrites both files
    every call from the current points.ply / splat.ply / annotations.json.
    """
    points_path = scene_dir / "points.ply"
    splat_path = scene_dir / "splat.ply"
    annotations_path = scene_dir / "annotations.json"
    out_ply = scene_dir / "wireframe.ply"
    out_index = scene_dir / "wireframe_index.json"

    with logfire.span(SPAN_WIREFRAME_BUILD, scene_id=scene_id) as span:
        if not points_path.exists():
            span.set_attribute("skipped", "missing_points")
            return out_ply

        xyz, rgb = _load_points_ply(points_path)
        span.set_attribute("input_point_count", int(xyz.shape[0]))
        if xyz.shape[0] == 0:
            span.set_attribute("skipped", "empty_points")
            return out_ply

        # 1) Voxel-downsampled background.
        voxel_xyz, voxel_rgb = _voxel_downsample(xyz, rgb, VOXEL_SIZE)
        span.set_attribute("voxel_count", int(voxel_xyz.shape[0]))

        # 2) Per-annotation dense samples — only available when both
        # splat.ply and annotations.json are present.
        per_object_xyz_chunks: list[np.ndarray] = []
        per_object_rgb_chunks: list[np.ndarray] = []
        ranges: dict[str, Range] = {}
        offset = int(voxel_xyz.shape[0])

        if splat_path.exists() and annotations_path.exists():
            try:
                gaussian_centers, _opacity = _fast_load(splat_path)
            except Exception as e:
                span.set_attribute("splat_load_error", str(e)[:200])
                gaussian_centers = np.zeros((0, 3), dtype=np.float32)

            anns = AnnotationsFile.read(annotations_path).root
            span.set_attribute("annotation_count", len(anns))

            if gaussian_centers.shape[0] > 0 and anns:
                # KDTree over points.ply lets us turn each annotation's
                # ``cluster_gaussian_indices`` into a points.ply point
                # set: query the tree at every Gaussian's center, take
                # the union of returned points within MATCH_RADIUS.
                tree = cKDTree(xyz)
                rng = np.random.default_rng(0xC0FFEE)
                for a in anns:
                    g_idx = np.asarray(a.cluster_gaussian_indices, dtype=np.int64)
                    if g_idx.size == 0:
                        continue
                    g_idx = g_idx[(g_idx >= 0) & (g_idx < gaussian_centers.shape[0])]
                    if g_idx.size == 0:
                        continue
                    seeds = gaussian_centers[g_idx]
                    matches_per_seed = tree.query_ball_point(seeds, r=MATCH_RADIUS)
                    members: set[int] = set()
                    for m in matches_per_seed:
                        members.update(m)
                    if not members:
                        continue
                    member_arr = np.fromiter(members, dtype=np.int64, count=len(members))
                    if member_arr.size > PER_OBJECT_SAMPLE:
                        sel = rng.choice(member_arr, PER_OBJECT_SAMPLE, replace=False)
                    else:
                        sel = member_arr
                    sel.sort()
                    per_object_xyz_chunks.append(xyz[sel])
                    per_object_rgb_chunks.append(rgb[sel])
                    ranges[a.id] = Range(start=offset, end=offset + int(sel.size))
                    offset += int(sel.size)
        else:
            span.set_attribute("annotations_present", False)

        # Concatenate voxel + per-object points and write artifacts.
        if per_object_xyz_chunks:
            all_xyz = np.concatenate([voxel_xyz, *per_object_xyz_chunks], axis=0)
            all_rgb = np.concatenate([voxel_rgb, *per_object_rgb_chunks], axis=0)
        else:
            all_xyz = voxel_xyz
            all_rgb = voxel_rgb

        _write_ply(out_ply, all_xyz, all_rgb)
        index = WireframeIndex(
            point_count=int(all_xyz.shape[0]),
            voxel_range=Range(start=0, end=int(voxel_xyz.shape[0])),
            annotations=ranges,
        )
        index.write_atomic(out_index)

        span.set_attribute("point_count", int(all_xyz.shape[0]))
        span.set_attribute("object_count", len(ranges))
        return out_ply
