"""Mask-projection lifting: SAM masks -> 3D Gaussian tracks (no DBSCAN).

Replaces the DBSCAN-on-Gaussian-centers pipeline in lift.py. Same output
contract (list[Cluster]) so vlm.py and cli.py don't need to change.

Algorithm:

1. Project every Gaussian center into every keyframe using cameras.json
   (one numpy matmul per frame, fully vectorized).
2. For each SAM mask, the Gaussians "inside" it are the ones whose
   projection lands on a True pixel of mask.segmentation. That's a single
   fancy-index per mask: ~ms even for 500k Gaussians.
3. Mask A in frame 1 and mask B in frame 42 are the same physical object
   when their Gaussian sets overlap heavily (Jaccard > merge threshold).
   Build that graph, union-find -> tracks.
4. Each track becomes one Cluster: union of member Gaussian sets, best
   member mask as the VLM anchor (largest area).

Background masks (walls, floor, ceiling) absorb a huge fraction of the
splat. Track Gaussian sets above `bg_fraction` are dropped before the VLM
ever sees them.

The Cluster dataclass is reused from lift.py so the rest of the pipeline
(vlm.label_clusters, cli._to_annotations) is untouched.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import logfire
import numpy as np
import scipy.sparse as sp

from .lift import Cluster
from .sam import Mask
from .splat_io import load_centers


# ─── PLY-load helpers ─────────────────────────────────────────────────────


def _load_centers_with_opacity(path: Path) -> tuple[np.ndarray, np.ndarray | None]:
    """xyz centers + optional opacity. Falls back to plyfile via splat_io."""
    try:
        return _fast_load(path)
    except Exception:
        return load_centers(path), None


def _fast_load(path: Path) -> tuple[np.ndarray, np.ndarray | None]:
    """mmap + np.frombuffer reader for binary_little_endian float PLY."""
    raw = path.read_bytes()
    end = raw.find(b"end_header\n")
    if end < 0:
        raise ValueError("no end_header")
    header = raw[: end + len(b"end_header\n")].decode("ascii", "replace")
    if "format binary_little_endian 1.0" not in header:
        raise ValueError("not little-endian binary PLY")
    n = None
    props: list[str] = []
    for line in header.splitlines():
        if line.startswith("element vertex "):
            n = int(line.split()[2])
        elif line.startswith("property float "):
            props.append(line.split()[2])
    if n is None or n == 0:
        return np.zeros((0, 3), dtype=np.float32), None
    body_off = end + len(b"end_header\n")
    arr = np.frombuffer(raw, dtype="<f4", count=n * len(props), offset=body_off)
    arr = arr.reshape(n, len(props))
    idx = {name: i for i, name in enumerate(props)}
    if not all(k in idx for k in ("x", "y", "z")):
        raise ValueError(f"missing xyz in props: {props}")
    centers = arr[:, [idx["x"], idx["y"], idx["z"]]].astype(np.float32, copy=True)
    opacity = arr[:, idx["opacity"]].astype(np.float32, copy=True) if "opacity" in idx else None
    return centers, opacity


# ─── projection ──────────────────────────────────────────────────────────


def _project_all(
    centers: np.ndarray, ext: np.ndarray, intr: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Project (N, 3) into pixel coords. Returns (u, v, z_cam) — int32 u/v."""
    n = centers.shape[0]
    homo = np.concatenate([centers, np.ones((n, 1), dtype=np.float32)], axis=1)
    cam = homo @ ext.T  # (N, 4)
    z_cam = cam[:, 2]
    safe_z = np.where(z_cam > 1e-6, z_cam, 1.0)
    pix = (cam[:, :3] / safe_z[:, None]) @ intr.T
    u = np.rint(pix[:, 0]).astype(np.int32)
    v = np.rint(pix[:, 1]).astype(np.int32)
    return u, v, z_cam


# ─── Jaccard / union-find ────────────────────────────────────────────────


class _UF:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def _merge_masks(
    mask_indices: list[np.ndarray],
    n_gaussians: int,
    jaccard_min: float,
) -> list[list[int]]:
    """Group masks whose Gaussian sets share Jaccard >= jaccard_min.

    Uses a CSR sparse membership matrix so we don't materialize an (M, N) bool
    matrix — for M=500 masks × N=500k Gaussians the dense version was 250 MB.
    Pairwise intersection counts come from a single sparse matmul.
    """
    m = len(mask_indices)
    if m == 0:
        return []
    sizes = np.array([s.size for s in mask_indices], dtype=np.int64)

    # Build CSR: rows = masks, cols = Gaussian ids, data = 1.
    rows = np.repeat(np.arange(m, dtype=np.int64), sizes)
    cols = np.concatenate(mask_indices) if m else np.empty(0, dtype=np.int64)
    data = np.ones(rows.shape[0], dtype=np.int8)
    membership = sp.csr_matrix((data, (rows, cols)), shape=(m, n_gaussians))

    # Intersection counts (M, M); dense at this size since M is small (~hundreds).
    inter = (membership @ membership.T).toarray()

    # Vectorized Jaccard: J(i,j) = |i∩j| / (|i|+|j|-|i∩j|)
    denom = sizes[:, None] + sizes[None, :] - inter
    with np.errstate(divide="ignore", invalid="ignore"):
        jac = np.where(denom > 0, inter / denom, 0.0)

    uf = _UF(m)
    iu, ju = np.where(np.triu(jac >= jaccard_min, k=1))
    for a, b in zip(iu.tolist(), ju.tolist()):
        uf.union(a, b)

    groups: dict[int, list[int]] = {}
    for i in range(m):
        groups.setdefault(uf.find(i), []).append(i)
    return list(groups.values())


# ─── caching ──────────────────────────────────────────────────────────────


_CACHE_FILENAME = "lift_cache.json"


def _ply_signature(path: Path) -> str:
    """Fast fingerprint: size + first/last 4KB. Avoids hashing 30 MB."""
    sz = path.stat().st_size
    head = path.open("rb").read(4096)
    with path.open("rb") as f:
        f.seek(max(0, sz - 4096))
        tail = f.read(4096)
    h = hashlib.md5(head + tail + str(sz).encode()).hexdigest()
    return f"{sz}-{h[:16]}"


def _cache_key(scene_dir: Path, *, jaccard_min: float, opacity_min: float) -> dict:
    return {
        "ply_sig": _ply_signature(scene_dir / "splat.ply"),
        "jaccard_min": jaccard_min,
        "opacity_min": opacity_min,
    }


def _cache_load(scene_dir: Path, key: dict) -> list[Cluster] | None:
    p = scene_dir / _CACHE_FILENAME
    if not p.exists():
        return None
    try:
        blob = json.loads(p.read_text())
    except Exception:
        return None
    if blob.get("key") != key:
        return None
    out: list[Cluster] = []
    for c in blob.get("clusters", []):
        out.append(
            Cluster(
                id=c["id"],
                gaussian_indices=c["gaussian_indices"],
                centroid=np.asarray(c["centroid"], dtype=np.float32),
                bbox_3d=(tuple(c["bbox_3d"][0]), tuple(c["bbox_3d"][1])),
                anchor_frame=c["anchor_frame"],
                anchor_mask_bbox=tuple(c["anchor_mask_bbox"]) if c["anchor_mask_bbox"] else None,
                anchor_area=c["anchor_area"],
            )
        )
    return out


def _cache_save(scene_dir: Path, key: dict, clusters: list[Cluster]) -> None:
    blob = {
        "key": key,
        "clusters": [
            {
                "id": c.id,
                "gaussian_indices": list(c.gaussian_indices),
                "centroid": [float(v) for v in c.centroid.tolist()],
                "bbox_3d": [list(c.bbox_3d[0]), list(c.bbox_3d[1])],
                "anchor_frame": c.anchor_frame,
                "anchor_mask_bbox": list(c.anchor_mask_bbox) if c.anchor_mask_bbox else None,
                "anchor_area": int(c.anchor_area),
            }
            for c in clusters
        ],
    }
    (scene_dir / _CACHE_FILENAME).write_text(json.dumps(blob))


# ─── public API ───────────────────────────────────────────────────────────


def cluster_via_masks(
    scene_dir: Path,
    masks: list[Mask],
    *,
    opacity_min: float = 0.05,
    min_votes: int = 1,
    jaccard_min: float = 0.30,
    bg_fraction: float = 0.30,
    min_track_size: int = 80,
    max_clusters: int = 12,
) -> list[Cluster]:
    """Mask-projection lift. Drop-in replacement for lift.cluster()."""
    with logfire.span(
        "segmentation.lift.cluster",
        method="masks",
        mask_count=len(masks),
        jaccard_min=jaccard_min,
        bg_fraction=bg_fraction,
        max_clusters=max_clusters,
    ) as span:
        # Cache hit: same splat.ply + same merge thresholds → replay last result.
        try:
            ck = _cache_key(scene_dir, jaccard_min=jaccard_min, opacity_min=opacity_min)
            cached = _cache_load(scene_dir, ck)
        except FileNotFoundError:
            ck, cached = None, None
        if cached is not None:
            span.set_attribute("cache", "hit")
            span.set_attribute("cluster_count", len(cached))
            return cached
        span.set_attribute("cache", "miss")

        centers, opacity = _load_centers_with_opacity(scene_dir / "splat.ply")
        n_total = int(centers.shape[0])
        span.set_attribute("gaussian_count", n_total)
        if n_total == 0 or not masks:
            span.set_attribute("cluster_count", 0)
            return []

        # Drop low-opacity floaters when opacity is available; mkkellogg-style
        # PLYs encode opacity pre-sigmoid, so threshold sigmoid(opacity).
        keep = np.ones(n_total, dtype=bool)
        if opacity is not None:
            keep = 1.0 / (1.0 + np.exp(-opacity)) >= opacity_min
        kept_idx = np.flatnonzero(keep)
        centers_k = centers[kept_idx]
        n = centers_k.shape[0]
        span.set_attribute("gaussian_count_kept", int(n))
        if n == 0:
            span.set_attribute("cluster_count", 0)
            return []

        cameras = json.loads((scene_dir / "cameras.json").read_text())
        cam_by_frame = {c["frame"]: c for c in cameras if "frame" in c}

        # Step 1: project once per frame.
        with logfire.span("segmentation.lift.project", frame_count=len(cam_by_frame)):
            proj_by_frame: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
            for frame_name, cam in cam_by_frame.items():
                ext = np.asarray(cam["extrinsic"], dtype=np.float32)
                intr = np.asarray(cam["intrinsic"], dtype=np.float32)
                u, v, z = _project_all(centers_k, ext, intr)
                proj_by_frame[frame_name] = (u, v, z)

        # Step 2: per-mask Gaussian set (indices into the kept array).
        with logfire.span("segmentation.lift.hits", mask_count=len(masks)):
            mask_member_lists: list[np.ndarray] = []
            kept_masks: list[Mask] = []
            for m in masks:
                proj = proj_by_frame.get(m.frame_name)
                if proj is None:
                    continue
                u, v, z = proj
                h, w = m.segmentation.shape
                in_bounds = (u >= 0) & (u < w) & (v >= 0) & (v < h) & (z > 1e-6)
                idx = np.flatnonzero(in_bounds)
                if idx.size == 0:
                    mask_member_lists.append(np.empty(0, dtype=np.int64))
                    kept_masks.append(m)
                    continue
                seg_hits = m.segmentation[v[idx], u[idx]]
                members = idx[seg_hits]
                mask_member_lists.append(members.astype(np.int64))
                kept_masks.append(m)

        # Step 3: drop masks that swallow most of the splat (background).
        bg_threshold = int(bg_fraction * n)
        filtered: list[np.ndarray] = []
        filtered_masks: list[Mask] = []
        for s, m in zip(mask_member_lists, kept_masks):
            if 0 < s.size < bg_threshold and s.size >= min_votes:
                filtered.append(s)
                filtered_masks.append(m)
        span.set_attribute("foreground_mask_count", len(filtered))
        if not filtered:
            span.set_attribute("cluster_count", 0)
            return []

        # Step 4: cross-frame mask grouping by Jaccard over Gaussian sets.
        with logfire.span(
            "segmentation.lift.merge",
            mask_count=len(filtered),
            jaccard_min=jaccard_min,
        ):
            groups = _merge_masks(filtered, n, jaccard_min)

        # Step 5: rank tracks (largest member-mask area first), build Cluster.
        ranked: list[tuple[int, list[int]]] = []
        for g in groups:
            anchor_area = max(filtered_masks[i].area for i in g)
            ranked.append((anchor_area, g))
        ranked.sort(key=lambda t: t[0], reverse=True)

        clusters: list[Cluster] = []
        for cid_zero, (_, g) in enumerate(ranked[:max_clusters]):
            union = np.unique(np.concatenate([filtered[i] for i in g]))
            if union.size < min_track_size:
                continue
            global_idx = kept_idx[union]
            pts = centers[global_idx]
            centroid = pts.mean(axis=0)
            bbox_lo = pts.min(axis=0)
            bbox_hi = pts.max(axis=0)
            anchor_local = max(g, key=lambda i: filtered_masks[i].area)
            anchor = filtered_masks[anchor_local]
            clusters.append(
                Cluster(
                    id=f"obj_{cid_zero + 1:03d}",
                    gaussian_indices=global_idx.tolist(),
                    centroid=centroid,
                    bbox_3d=(
                        (float(bbox_lo[0]), float(bbox_lo[1]), float(bbox_lo[2])),
                        (float(bbox_hi[0]), float(bbox_hi[1]), float(bbox_hi[2])),
                    ),
                    anchor_frame=anchor.frame_name,
                    anchor_mask_bbox=anchor.bbox,
                    anchor_area=int(anchor.area),
                )
            )

        span.set_attribute("cluster_count", len(clusters))
        if ck is not None:
            try:
                _cache_save(scene_dir, ck, clusters)
            except OSError:
                pass
        return clusters
