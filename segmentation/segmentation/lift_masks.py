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

Placement-accuracy improvements over v1:

* Centroid uses the *opacity-weighted geometric median* (Weiszfeld) rather
  than the arithmetic mean. Breakdown point ~50% vs ~25% for the mean even
  after MAD trimming — a few survivor outliers no longer drag the centroid.
* Bounding box uses the *5th–95th percentile per axis* rather than absolute
  min/max. A single stray Gaussian per axis no longer blows the box up.

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
from PIL import Image

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


# ─── robust statistics ───────────────────────────────────────────────────


def _geometric_median(
    pts: np.ndarray, weights: np.ndarray | None = None, iters: int = 12, eps: float = 1e-7
) -> np.ndarray:
    """Weighted geometric median via Weiszfeld iteration.

    L1-style estimator: minimises Σ wᵢ ‖pᵢ - x‖. Breakdown point 50%, vs
    ~25% for MAD-trimmed mean — a handful of stray Gaussians can no longer
    drag the centroid the way they did with `pts.mean(axis=0)`.
    """
    if pts.shape[0] == 0:
        return np.zeros(3, dtype=np.float32)
    if pts.shape[0] == 1:
        return pts[0].astype(np.float32, copy=True)
    w = (
        np.ones(pts.shape[0], dtype=np.float64)
        if weights is None
        else np.asarray(weights, dtype=np.float64)
    )
    # Init at the weighted mean — close enough to the median that the
    # iteration converges in 5-10 steps.
    wsum = max(float(w.sum()), 1e-9)
    x = (w[:, None] * pts).sum(axis=0) / wsum
    for _ in range(iters):
        d = np.linalg.norm(pts - x, axis=1)
        # Avoid div-by-zero when a query point coincides with a sample.
        wd = w / np.maximum(d, eps)
        wd_sum = wd.sum()
        if wd_sum < 1e-12:
            break
        x_new = (wd[:, None] * pts).sum(axis=0) / wd_sum
        if np.linalg.norm(x_new - x) < eps:
            x = x_new
            break
        x = x_new
    return x.astype(np.float32)


def _percentile_aabb(
    pts: np.ndarray, lo_pct: float = 5.0, hi_pct: float = 95.0
) -> tuple[np.ndarray, np.ndarray]:
    """Robust axis-aligned bbox: use lo/hi percentiles, not min/max.

    Single stray Gaussian per axis no longer blows the bbox out 10×.
    Keeps the AABB shape (so the viewer doesn't change), but the box hugs
    the object's actual extent within the chosen percentile band.
    """
    if pts.shape[0] == 0:
        z = np.zeros(3, dtype=np.float32)
        return z, z
    if pts.shape[0] < 8:
        return pts.min(axis=0).astype(np.float32), pts.max(axis=0).astype(np.float32)
    lo = np.percentile(pts, lo_pct, axis=0).astype(np.float32)
    hi = np.percentile(pts, hi_pct, axis=0).astype(np.float32)
    return lo, hi


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


def _cache_key(
    scene_dir: Path,
    *,
    jaccard_min: float,
    opacity_min: float,
    bg_fraction: float,
    min_track_size: int,
    max_clusters: int,
    mask_count: int,
) -> dict:
    return {
        "ply_sig": _ply_signature(scene_dir / "splat.ply"),
        "jaccard_min": jaccard_min,
        "opacity_min": opacity_min,
        "bg_fraction": bg_fraction,
        "min_track_size": min_track_size,
        "max_clusters": max_clusters,
        "mask_count": mask_count,
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
                sources=tuple(c.get("sources", ())),
                proposed_phrase=c.get("proposed_phrase", ""),
                frame_ids=list(c.get("frame_ids", [])),
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
                "sources": list(c.sources),
                "proposed_phrase": c.proposed_phrase,
                "frame_ids": list(c.frame_ids),
            }
            for c in clusters
        ],
    }
    (scene_dir / _CACHE_FILENAME).write_text(json.dumps(blob))


# ─── mask persistence ─────────────────────────────────────────────────────


# Mask area floor for the per-cluster on-disk PNGs. Frames whose mask falls
# below this are dropped at write-time AND filtered out of the cluster's
# frame_ids list, so the web evidence gallery never asks for a 404.
_EVIDENCE_MIN_AREA_PX = 64


def _write_cluster_masks(
    scene_dir: Path,
    mask_groups: list[tuple[str, list[Mask]]],
    *,
    min_area_px: int = _EVIDENCE_MIN_AREA_PX,
) -> None:
    """Persist per-cluster SAM masks under masks/<cluster_id>/<frame_stem>.png.

    Drives the web "evidence gallery" (what the model saw on each keyframe).
    One PNG per (cluster, frame): if multiple masks in the cluster came from
    the same frame, keeps the largest-area one — the gallery shows one
    overlay per frame, not a per-prompt heat map.

    Format: 8-bit grayscale, 0=background / 255=object. The web layer binds
    these as CSS mask-image and tints them with annotation.color, so a
    single-channel image is sufficient and tiny on the wire.
    """
    if not mask_groups:
        return
    masks_root = scene_dir / "masks"
    try:
        masks_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    for cluster_id, masks in mask_groups:
        # Best mask per frame = largest area (the SAM dedup pass already
        # collapsed within-frame near-duplicates, so this is mostly a tie-break
        # for the rare case where two distinct prompts in one frame both
        # survive).
        by_frame: dict[str, Mask] = {}
        for m in masks:
            if m.area < min_area_px:
                continue
            cur = by_frame.get(m.frame_name)
            if cur is None or m.area > cur.area:
                by_frame[m.frame_name] = m
        if not by_frame:
            continue
        out_dir = masks_root / cluster_id
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        for frame_name, m in by_frame.items():
            stem = Path(frame_name).stem
            try:
                arr = (m.segmentation.astype(np.uint8) * 255)
                Image.fromarray(arr, mode="L").save(
                    out_dir / f"{stem}.png", optimize=True
                )
            except OSError:
                continue


# ─── public API ───────────────────────────────────────────────────────────


def cluster_via_masks(
    scene_dir: Path,
    masks: list[Mask],
    *,
    opacity_min: float = 0.05,
    min_votes: int = 1,
    jaccard_min: float = 0.30,
    bg_fraction: float = 0.45,
    min_track_size: int = 40,
    max_clusters: int = 30,
    scene_id: str | None = None,
) -> list[Cluster]:
    """Mask-projection lift. Drop-in replacement for lift.cluster().

    Accepts SAM masks and VLM-proposal masks (built via proposals_to_masks)
    interchangeably — both implement the Mask dataclass. Provenance flows into
    each Cluster's `sources` and `proposed_phrase` fields.
    """
    sid = scene_id or scene_dir.name
    mask_count_sam = sum(1 for m in masks if m.source == "sam")
    mask_count_vlm = sum(1 for m in masks if m.source == "vlm")
    with logfire.span(
        "segmentation.lift.cluster",
        scene_id=sid,
        method="masks",
        mask_count=len(masks),
        mask_count_sam=mask_count_sam,
        mask_count_vlm=mask_count_vlm,
        jaccard_min=jaccard_min,
        bg_fraction=bg_fraction,
        max_clusters=max_clusters,
    ) as span:
        # Cache hit: same splat.ply + same merge thresholds → replay last result.
        try:
            ck = _cache_key(
                scene_dir,
                jaccard_min=jaccard_min,
                opacity_min=opacity_min,
                bg_fraction=bg_fraction,
                min_track_size=min_track_size,
                max_clusters=max_clusters,
                mask_count=len(masks),
            )
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

        # Step 1: project once per frame, AND build a per-frame z-buffer of
        # the front-most Gaussian depth at every pixel. Used in step 2 to
        # gate cluster membership to the front layer — without this, when a
        # SAM mask covers a foreground object (e.g. a plush toy), every
        # Gaussian on the wall behind that toy *also* projects into the same
        # 2D pixels and gets wrongly added to the cluster, dragging the
        # centroid halfway to the back of the room. The z-buffer approach
        # is the standard fix and adds only ~5 ms per frame.
        scene_extent = float(np.linalg.norm(centers_k.max(axis=0) - centers_k.min(axis=0)))
        # Depth tolerance for "this Gaussian is on the visible surface, not
        # behind it". Scene-relative so it scales with capture extent, with a
        # 10 cm floor so thick-but-frontmost objects (a couch, a desk) keep
        # their back-side Gaussians.
        depth_eps = max(0.10, 0.02 * scene_extent)

        with logfire.span("segmentation.lift.project", scene_id=sid, frame_count=len(cam_by_frame)):
            proj_by_frame: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
            zbuf_by_frame: dict[str, np.ndarray] = {}
            # Cache (h, w) per frame from any mask in that frame.
            hw_by_frame: dict[str, tuple[int, int]] = {}
            for m in masks:
                hw_by_frame.setdefault(m.frame_name, m.segmentation.shape)

            for frame_name, cam in cam_by_frame.items():
                ext = np.asarray(cam["extrinsic"], dtype=np.float32)
                intr = np.asarray(cam["intrinsic"], dtype=np.float32)
                u, v, z = _project_all(centers_k, ext, intr)
                proj_by_frame[frame_name] = (u, v, z)
                hw = hw_by_frame.get(frame_name)
                if hw is None:
                    continue
                h, w = hw
                # np.minimum.at handles duplicate (v, u) indices correctly,
                # accumulating the per-pixel min(z) across all in-bounds
                # Gaussians. Inf for empty pixels.
                zbuf = np.full((h, w), np.inf, dtype=np.float32)
                in_bounds = (u >= 0) & (u < w) & (v >= 0) & (v < h) & (z > 1e-6)
                if in_bounds.any():
                    bidx = np.flatnonzero(in_bounds)
                    np.minimum.at(zbuf, (v[bidx], u[bidx]), z[bidx])
                # splat.ply is voxel-downsampled (~1.3 M Gaussians) so most
                # mask pixels don't have a Gaussian projecting onto them —
                # the raw zbuf is nearly all `inf` between the few dense
                # foreground hits. Dilate (min-filter) so foreground depth
                # propagates into gaps; without this the per-pixel "is this
                # the front?" test becomes trivially true for any
                # background Gaussian at a gap pixel, and the cluster
                # picks up the entire wall behind a small object.
                from scipy.ndimage import minimum_filter
                zbuf = minimum_filter(zbuf, size=7)
                zbuf_by_frame[frame_name] = zbuf

        # Step 2: per-mask Gaussian set (indices into the kept array). Now
        # gated by the per-frame z-buffer so only front-layer Gaussians (the
        # ones actually visible at that pixel in that frame) make it into
        # the cluster.
        with logfire.span(
            "segmentation.lift.hits",
            scene_id=sid,
            mask_count=len(masks),
            depth_eps=depth_eps,
        ):
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
                zbuf = zbuf_by_frame.get(m.frame_name)
                if zbuf is not None:
                    zhit = zbuf[v[idx], u[idx]]
                    visible = z[idx] <= (zhit + depth_eps)
                    members = idx[seg_hits & visible]
                else:
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
            scene_id=sid,
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
        # Per-cluster member masks, kept so we can persist them to disk for
        # the evidence-gallery UI. Indexed by the same iteration order as
        # `clusters` and `ranked`.
        cluster_masks: list[tuple[str, list[Mask]]] = []
        dropped_min_track = 0
        dropped_max_clusters = max(0, len(ranked) - max_clusters)
        sourced_sam = sourced_vlm = sourced_both = 0
        for cid_zero, (_, g) in enumerate(ranked[:max_clusters]):
            union = np.unique(np.concatenate([filtered[i] for i in g]))
            if union.size < min_track_size:
                dropped_min_track += 1
                continue
            global_idx = kept_idx[union]
            pts = centers[global_idx]

            # Anchor frame's camera = the viewpoint the SAM mask came from.
            # Pick the frame with the largest mask area (this is also the
            # cluster's anchor used for the VLM crop later).
            sam_in_group_pre = [i for i in g if filtered_masks[i].source == "sam"]
            anchor_pool_pre = sam_in_group_pre if sam_in_group_pre else g
            anchor_local_pre = max(
                anchor_pool_pre, key=lambda i: filtered_masks[i].area
            )
            anchor_pre = filtered_masks[anchor_local_pre]
            anchor_cam = cam_by_frame.get(anchor_pre.frame_name)

            # Depth-mode filter (along anchor camera ray) — the actual fix
            # for multimodal clusters where SAM masks accidentally chain
            # foreground + background through occlusion. Histogram the
            # cluster's depths from the anchor viewpoint, find the dense
            # peak, keep only points within depth_eps of that peak.
            if anchor_cam is not None and pts.shape[0] >= 16:
                ext = np.asarray(anchor_cam["extrinsic"], dtype=np.float32)
                homo = np.concatenate(
                    [pts, np.ones((pts.shape[0], 1), dtype=pts.dtype)], axis=1
                )
                cam_pts = homo @ ext.T
                depths = cam_pts[:, 2]
                # Restrict to points actually in front of anchor camera.
                front = depths > 1e-6
                if front.any():
                    front_depths = depths[front]
                    # 50-bin depth histogram → find densest layer.
                    bins = max(20, min(60, front_depths.size // 8))
                    hist, edges = np.histogram(front_depths, bins=bins)
                    mode_bin = int(np.argmax(hist))
                    mode_depth = float(0.5 * (edges[mode_bin] + edges[mode_bin + 1]))
                    # Keep points within depth_eps of the mode (in metres,
                    # same scale as the per-frame depth_eps from step 2).
                    inliers = (
                        front
                        & (np.abs(depths - mode_depth) < depth_eps)
                    )
                    n_in = int(inliers.sum())
                    if n_in >= max(8, min_track_size // 2) and n_in < pts.shape[0]:
                        pts = pts[inliers]
                        global_idx = global_idx[inliers]

            # Final iterative MAD pass: trims silhouette wisps still present
            # after the depth-mode filter.
            if pts.shape[0] >= 16:
                for _round in range(2):
                    median_xyz = np.median(pts, axis=0)
                    dist = np.linalg.norm(pts - median_xyz, axis=1)
                    mad = float(np.median(dist))
                    if mad <= 1e-6:
                        break
                    sigma = mad * 1.4826
                    inliers = dist < (sigma * 2.0)
                    n_in = int(inliers.sum())
                    if n_in == pts.shape[0] or n_in < max(8, min_track_size // 2):
                        break
                    pts = pts[inliers]
                    global_idx = global_idx[inliers]

            # Bbox-diagonal sanity cap. Cheap O(1) safety net for runaway
            # leaks: any cluster whose 3D AABB diagonal exceeds 2.5m is
            # almost certainly leaked (a door is ~2.2m diag, a bed ~2.2m,
            # a curtain ~2.5m). Drop it rather than emit a centroid
            # floating in empty space.
            if pts.shape[0] >= 16:
                diag = float(
                    np.linalg.norm(pts.max(axis=0) - pts.min(axis=0))
                )
                if diag > 2.5:
                    dropped_min_track += 1
                    continue

            # Opacity-weighted geometric median centroid. If opacity is
            # available, weight by sigmoid(opacity) so dense surface
            # Gaussians dominate over transparent wisps that survived the
            # depth-mode + MAD filters; otherwise weight uniformly.
            if opacity is not None:
                op_kept = opacity[global_idx]
                w_centroid = 1.0 / (1.0 + np.exp(-op_kept.astype(np.float64)))
            else:
                w_centroid = None
            centroid = _geometric_median(pts, w_centroid)
            bbox_lo, bbox_hi = _percentile_aabb(pts, lo_pct=5.0, hi_pct=95.0)
            # Anchor: prefer real SAM masks for tight crops; VLM bboxes are loose
            # rectangles. Fall back to VLM if no SAM mask is in the group.
            sam_in_group = [i for i in g if filtered_masks[i].source == "sam"]
            anchor_pool = sam_in_group if sam_in_group else g
            anchor_local = max(anchor_pool, key=lambda i: filtered_masks[i].area)
            anchor = filtered_masks[anchor_local]

            sources_set = sorted({filtered_masks[i].source for i in g})
            # Frames where this object was observed. Mirror the writer's
            # area filter so we never advertise a frame whose mask wasn't
            # persisted (the gallery would 404). Capped at 6 — the chat
            # agent only inlines a few per request and Anthropic image budget
            # is finite. Sorted for deterministic output.
            frame_ids_seen = sorted({
                filtered_masks[i].frame_name
                for i in g
                if filtered_masks[i].area >= _EVIDENCE_MIN_AREA_PX
            })[:6]
            # Best VLM phrase in the group: highest proposal_confidence.
            vlm_members = [filtered_masks[i] for i in g if filtered_masks[i].source == "vlm"]
            proposed_phrase = ""
            if vlm_members:
                best = max(vlm_members, key=lambda m: m.proposal_confidence)
                proposed_phrase = best.phrase

            if "sam" in sources_set and "vlm" in sources_set:
                sourced_both += 1
            elif "sam" in sources_set:
                sourced_sam += 1
            elif "vlm" in sources_set:
                sourced_vlm += 1

            cluster_id = f"obj_{cid_zero + 1:03d}"
            clusters.append(
                Cluster(
                    id=cluster_id,
                    gaussian_indices=global_idx.tolist(),
                    centroid=centroid,
                    bbox_3d=(
                        (float(bbox_lo[0]), float(bbox_lo[1]), float(bbox_lo[2])),
                        (float(bbox_hi[0]), float(bbox_hi[1]), float(bbox_hi[2])),
                    ),
                    anchor_frame=anchor.frame_name,
                    anchor_mask_bbox=anchor.bbox,
                    anchor_area=int(anchor.area),
                    sources=tuple(sources_set),
                    proposed_phrase=proposed_phrase,
                    frame_ids=frame_ids_seen,
                )
            )
            cluster_masks.append(
                (cluster_id, [filtered_masks[i] for i in g])
            )

        span.set_attribute("cluster_count", len(clusters))
        span.set_attribute("dropped_by_min_track_size", dropped_min_track)
        span.set_attribute("dropped_by_max_clusters", dropped_max_clusters)
        span.set_attribute("cluster_count_sam_only", sourced_sam)
        span.set_attribute("cluster_count_vlm_only", sourced_vlm)
        span.set_attribute("cluster_count_both", sourced_both)
        # Drop masks for clusters we kept (mirrors clusters[]); skipped
        # clusters at the tail of cluster_masks are inert. The downstream
        # merge passes may rename or absorb cluster ids — masks under those
        # ids stay on disk under their original ids, and the surviving
        # annotation's id is always one of those ids (anchor.id), so the
        # gallery's primary view is always present.
        kept_ids = {c.id for c in clusters}
        kept_groups = [(cid, ms) for cid, ms in cluster_masks if cid in kept_ids]
        try:
            _write_cluster_masks(scene_dir, kept_groups)
        except Exception as e:  # noqa: BLE001 — telemetry-only, do not fail the lift
            logfire.warn(
                "mask persistence failed",
                scene_id=sid,
                error=str(e)[:200],
            )
        if ck is not None:
            try:
                _cache_save(scene_dir, ck, clusters)
            except OSError:
                pass
        return clusters


# ─── Post-cluster dedup: merge near-duplicate clusters ───────────────────


_MERGE_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "with", "of", "on", "in", "to", "for",
    "is", "at", "by", "from", "this", "that",
})


def _label_tokens(label: str) -> set[str]:
    """Lowercased content tokens length >= 3, minus stopwords."""
    import re
    return {
        w for w in re.findall(r"\w+", label.lower())
        if len(w) >= 3 and w not in _MERGE_STOPWORDS
    }


def _label_similar(a: str, b: str, *, jaccard_min: float = 0.40) -> bool:
    """Two cluster labels refer to the same object class.

    Match if EITHER:
      - Token-Jaccard ≥ jaccard_min (e.g. "white door frame" vs "white door
        with handle" share {white, door} → 2/4 = 0.5).
      - One label is a substring of the other (case-insensitive).
    """
    if not a or not b:
        return False
    al, bl = a.lower().strip(), b.lower().strip()
    if al == bl or al in bl or bl in al:
        return True
    ta, tb = _label_tokens(a), _label_tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= jaccard_min


def merge_duplicate_clusters(
    scene_dir: Path,
    clusters: list[Cluster],
    *,
    proximity_m: float = 0.6,
    label_jaccard_min: float = 0.40,
) -> dict:
    """Merge clusters that are duplicate views of the same object.

    Two clusters merge iff:
      1. Their proposed_phrases are similar (token-Jaccard >= label_jaccard_min,
         OR one is a substring of the other), AND
      2. ‖A.centroid − B.centroid‖ < proximity_m.

    Both conditions must hold — proximity alone over-merges adjacent objects
    (laptop + monitor on same desk), and label alone over-merges instances
    of the same class in different rooms.

    The merge is transitive (union-find): if A ~ B and B ~ C, all three
    collapse into one cluster.

    Per merged group, the surviving cluster has:
      - gaussian_indices: union of all members' indices (deduped)
      - centroid: opacity-weighted geometric median of the union's positions
      - bbox_3d: 5/95 percentile AABB of the union's positions
      - id: the largest-anchor member's id (preserves stable IDs)
      - proposed_phrase: highest-confidence member's phrase
      - sources / anchor_frame / anchor_mask_bbox / anchor_area: from the
        member with the largest anchor area (best crop for VLM labeling)

    Mutates `clusters` in place — replaces its contents. Returns a stats
    dict for observability.
    """
    n = len(clusters)
    if n < 2:
        return {"input": n, "output": n, "merged_groups": 0, "merges": 0}

    centroids = np.stack([np.asarray(c.centroid, dtype=np.float32) for c in clusters], axis=0)

    # Pairwise centroid distances + label-similarity → union-find.
    uf = _UF(n)
    pair_count = 0
    for i in range(n):
        for j in range(i + 1, n):
            d = float(np.linalg.norm(centroids[i] - centroids[j]))
            if d >= proximity_m:
                continue
            if not _label_similar(
                clusters[i].proposed_phrase,
                clusters[j].proposed_phrase,
                jaccard_min=label_jaccard_min,
            ):
                continue
            uf.union(i, j)
            pair_count += 1

    # Group by union root.
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(uf.find(i), []).append(i)

    if all(len(g) == 1 for g in groups.values()):
        return {"input": n, "output": n, "merged_groups": 0, "merges": 0}

    # Need centers + opacity for re-computing the merged centroid.
    centers, opacity = _load_centers_with_opacity(scene_dir / "splat.ply")
    n_centers = int(centers.shape[0])

    merged: list[Cluster] = []
    merges_applied = 0
    for root, members in sorted(groups.items()):
        if len(members) == 1:
            merged.append(clusters[members[0]])
            continue
        merges_applied += 1

        # Union of Gaussian indices. Defensive clip — stale clusters could
        # carry indices from a different splat.
        idx_pool = np.concatenate([
            np.asarray(clusters[m].gaussian_indices, dtype=np.int64)
            for m in members
        ])
        idx_pool = np.unique(idx_pool[(idx_pool >= 0) & (idx_pool < n_centers)])

        pts = centers[idx_pool]
        if opacity is not None:
            w = 1.0 / (1.0 + np.exp(-opacity[idx_pool].astype(np.float64)))
        else:
            w = None

        new_centroid = _geometric_median(pts, w)
        new_lo, new_hi = _percentile_aabb(pts, lo_pct=5.0, hi_pct=95.0)

        # Anchor: pick the member with the largest anchor area for the best
        # crop downstream (VLM labeling reads this anchor frame + mask).
        anchor_member = max(members, key=lambda m: clusters[m].anchor_area)
        anchor = clusters[anchor_member]

        # Phrase: pick the member with the highest-confidence proposed_phrase.
        # We don't have per-cluster confidence directly; use anchor_area as
        # a reasonable proxy for "this view actually saw it big and clear."
        phrase_member = max(
            members, key=lambda m: (clusters[m].anchor_area, len(clusters[m].proposed_phrase))
        )
        phrase = clusters[phrase_member].proposed_phrase

        union_sources: set[str] = set()
        union_frames: set[str] = set()
        for m in members:
            union_sources.update(clusters[m].sources)
            union_frames.update(clusters[m].frame_ids)

        merged.append(
            Cluster(
                id=anchor.id,
                gaussian_indices=idx_pool.tolist(),
                centroid=new_centroid,
                bbox_3d=(
                    (float(new_lo[0]), float(new_lo[1]), float(new_lo[2])),
                    (float(new_hi[0]), float(new_hi[1]), float(new_hi[2])),
                ),
                anchor_frame=anchor.anchor_frame,
                anchor_mask_bbox=anchor.anchor_mask_bbox,
                anchor_area=anchor.anchor_area,
                sources=tuple(sorted(union_sources)),
                proposed_phrase=phrase,
                frame_ids=sorted(union_frames)[:6],
            )
        )

    clusters[:] = merged
    return {
        "input": n,
        "output": len(clusters),
        "merged_groups": merges_applied,
        "merges": pair_count,
    }


def merge_annotations_by_label(
    annotations,  # list[Annotation]
    *,
    proximity_m: float = 0.6,
    label_jaccard_min: float = 0.30,
):
    """Second-stage dedup operating on FINAL VLM labels (post-labeling).

    The pre-VLM `merge_duplicate_clusters` gates on each cluster's
    `proposed_phrase` — the proposer's per-keyframe hint, which varies wildly
    across views ("doorway" vs "white frame" vs "door with hook"). The same
    physical door produces dissimilar proposed_phrases, escapes that merge,
    then receives 7 different VLM labels that all share the literal token
    "door". This pass catches that residual.

    Two annotations merge iff:
      1. Their final labels are similar (token-Jaccard >= label_jaccard_min,
         or one is a substring of the other), AND
      2. ‖A.centroid − B.centroid‖ < proximity_m.

    The merge is transitive (union-find): if A ~ B and B ~ C, all three
    collapse into one annotation.

    Per merged group, the survivor:
      - bbox = AABB enclosing all component bboxes
      - centroid = MIDPOINT of that AABB (NOT geometric median over partial
        face Gaussians — partial views bias the median to whichever face had
        the largest anchor area)
      - id, label, color, confidence, alternatives = highest-confidence member,
        with any leading "duplicate_of:..." alternatives stripped (the survivor
        is canonical)
      - cluster_gaussian_indices = unique union
      - provenance = sorted union

    Returns (merged_list, stats_dict).
    """
    n = len(annotations)
    stats = {"input": n, "output": n, "merged_groups": 0, "merges": 0}
    if n < 2:
        return list(annotations), stats

    centroids = np.stack(
        [np.asarray(a.centroid, dtype=np.float32) for a in annotations], axis=0
    )

    uf = _UF(n)
    pair_count = 0
    for i in range(n):
        for j in range(i + 1, n):
            d = float(np.linalg.norm(centroids[i] - centroids[j]))
            if d >= proximity_m:
                continue
            if not _label_similar(
                annotations[i].label,
                annotations[j].label,
                jaccard_min=label_jaccard_min,
            ):
                continue
            uf.union(i, j)
            pair_count += 1

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(uf.find(i), []).append(i)

    if all(len(g) == 1 for g in groups.values()):
        return list(annotations), stats

    merged = []
    merges_applied = 0
    for root, members in sorted(groups.items()):
        if len(members) == 1:
            merged.append(annotations[members[0]])
            continue
        merges_applied += 1

        # Bbox-midpoint centroid: union AABB of all component bboxes, midpoint.
        los = np.stack(
            [np.asarray(annotations[m].bbox[0], dtype=np.float32) for m in members]
        )
        his = np.stack(
            [np.asarray(annotations[m].bbox[1], dtype=np.float32) for m in members]
        )
        lo = los.min(axis=0)
        hi = his.max(axis=0)
        new_centroid = ((lo + hi) * 0.5).tolist()
        new_bbox = (
            (float(lo[0]), float(lo[1]), float(lo[2])),
            (float(hi[0]), float(hi[1]), float(hi[2])),
        )

        # Survivor = highest-confidence member.
        survivor_idx = max(members, key=lambda m: annotations[m].confidence)
        survivor = annotations[survivor_idx]

        # Union of Gaussian indices (deduped).
        idx_pool: list[int] = []
        seen: set[int] = set()
        for m in members:
            for v in annotations[m].cluster_gaussian_indices:
                if v not in seen:
                    seen.add(v)
                    idx_pool.append(int(v))

        # Provenance: sorted union.
        prov_set: set[str] = set()
        frame_set: set[str] = set()
        for m in members:
            prov_set.update(annotations[m].provenance)
            frame_set.update(getattr(annotations[m], "frame_ids", []) or [])

        # Strip any leading "duplicate_of:" alternatives from the survivor —
        # the survivor IS the canonical now.
        alts = [
            a for a in survivor.alternatives if not str(a).startswith("duplicate_of:")
        ]

        merged_ann = type(survivor)(
            id=survivor.id,
            label=survivor.label,
            centroid=(float(new_centroid[0]), float(new_centroid[1]), float(new_centroid[2])),
            bbox=new_bbox,
            color=survivor.color,
            confidence=survivor.confidence,
            alternatives=alts,
            cluster_gaussian_indices=idx_pool,
            provenance=sorted(prov_set),
            frame_ids=sorted(frame_set)[:6],
        )
        merged.append(merged_ann)

    stats = {
        "input": n,
        "output": len(merged),
        "merged_groups": merges_applied,
        "merges": pair_count,
    }
    return merged, stats


# ─── VLM proposal bridge ──────────────────────────────────────────────────


def proposals_to_masks(
    proposals,  # list[proposer.Proposal] — typed loosely to avoid import cycle
    scene_dir: Path,
) -> list[Mask]:
    """Convert each VLM (frame, normalized-bbox) proposal into a rectangular
    boolean Mask in image-pixel coords so it flows through cluster_via_masks
    like a SAM mask. Sets Mask.source='vlm', Mask.phrase, Mask.proposal_confidence.

    Image dimensions are read from the actual frame on disk (not cameras.json,
    whose intrinsics may have been rescaled). Reads each frame at most once.
    """
    frame_dir = scene_dir / "frames"
    dim_cache: dict[str, tuple[int, int]] = {}  # frame_name -> (W, H)
    out: list[Mask] = []
    for j, p in enumerate(proposals):
        if p.frame_name not in dim_cache:
            fp = frame_dir / p.frame_name
            if not fp.exists():
                continue
            with Image.open(fp) as im:
                dim_cache[p.frame_name] = (im.width, im.height)
        W, H = dim_cache[p.frame_name]
        bx, by, bw, bh = p.bbox_norm
        x = max(0, int(round(bx * W)))
        y = max(0, int(round(by * H)))
        w = max(1, min(W - x, int(round(bw * W))))
        h = max(1, min(H - y, int(round(bh * H))))
        if w <= 0 or h <= 0:
            continue
        seg = np.zeros((H, W), dtype=bool)
        seg[y : y + h, x : x + w] = True
        out.append(
            Mask(
                frame_idx=-1,
                frame_name=p.frame_name,
                mask_id=j,
                segmentation=seg,
                bbox=(x, y, w, h),
                area=int(w * h),
                confidence=float(p.confidence),
                source="vlm",
                prompt="",
                phrase=p.phrase,
                proposal_confidence=float(p.confidence),
            )
        )
    return out
