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
    bg_fraction: float = 0.45,
    min_track_size: int = 40,
    max_clusters: int = 30,
) -> list[Cluster]:
    """Mask-projection lift. Drop-in replacement for lift.cluster().

    Accepts SAM masks and VLM-proposal masks (built via proposals_to_masks)
    interchangeably — both implement the Mask dataclass. Provenance flows into
    each Cluster's `sources` and `proposed_phrase` fields.
    """
    mask_count_sam = sum(1 for m in masks if m.source == "sam")
    mask_count_vlm = sum(1 for m in masks if m.source == "vlm")
    with logfire.span(
        "segmentation.lift.cluster",
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

        with logfire.span("segmentation.lift.project", frame_count=len(cam_by_frame)):
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
                zbuf_by_frame[frame_name] = zbuf

        # Step 2: per-mask Gaussian set (indices into the kept array). Now
        # gated by the per-frame z-buffer so only front-layer Gaussians (the
        # ones actually visible at that pixel in that frame) make it into
        # the cluster.
        with logfire.span(
            "segmentation.lift.hits",
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

            # Robust centroid: drop residual outliers via MAD (median + 2.5σ).
            # The depth z-buffer in step 2 catches occlusion-bleed Gaussians;
            # this catches the long-tail noise from depth-prediction wisps
            # near silhouette edges. Cheap (~5 ms per cluster) and keeps the
            # centroid pinned to the dense core of the object.
            if pts.shape[0] >= 16:
                median_xyz = np.median(pts, axis=0)
                dist = np.linalg.norm(pts - median_xyz, axis=1)
                mad = float(np.median(dist))
                if mad > 1e-6:
                    sigma = mad * 1.4826
                    inliers = dist < (sigma * 2.5)
                    if inliers.sum() >= max(8, min_track_size // 2):
                        pts = pts[inliers]
                        global_idx = global_idx[inliers]

            centroid = pts.mean(axis=0)
            bbox_lo = pts.min(axis=0)
            bbox_hi = pts.max(axis=0)
            # Anchor: prefer real SAM masks for tight crops; VLM bboxes are loose
            # rectangles. Fall back to VLM if no SAM mask is in the group.
            sam_in_group = [i for i in g if filtered_masks[i].source == "sam"]
            anchor_pool = sam_in_group if sam_in_group else g
            anchor_local = max(anchor_pool, key=lambda i: filtered_masks[i].area)
            anchor = filtered_masks[anchor_local]

            sources_set = sorted({filtered_masks[i].source for i in g})
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
                    sources=tuple(sources_set),
                    proposed_phrase=proposed_phrase,
                )
            )

        span.set_attribute("cluster_count", len(clusters))
        span.set_attribute("dropped_by_min_track_size", dropped_min_track)
        span.set_attribute("dropped_by_max_clusters", dropped_max_clusters)
        span.set_attribute("cluster_count_sam_only", sourced_sam)
        span.set_attribute("cluster_count_vlm_only", sourced_vlm)
        span.set_attribute("cluster_count_both", sourced_both)
        if ck is not None:
            try:
                _cache_save(scene_dir, ck, clusters)
            except OSError:
                pass
        return clusters


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
