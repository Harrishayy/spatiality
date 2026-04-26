"""Parallel VLM object proposer.

Independent annotation source from SAM. The VLM looks at every keyframe in
parallel via asyncio.gather and returns a flat list of (frame, phrase, bbox,
confidence). The lift step turns each bbox into a rectangular mask so it
flows through cluster_via_masks side-by-side with SAM masks.

Spec: plans/modules/03_segmentation.md (revised).

Hard rules (CLAUDE.md):
- Every model call routes through Pydantic AI Gateway (auth_token, not api_key).
- Logfire spans observe each frame call + a summary span.

Cache: scene_dir/vlm_proposals.json keyed on (model, keyframe set). Re-runs
skip the proposer when inputs haven't changed.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import logfire
from anthropic import APIError
from PIL import Image

from shared.observability import attach_payload

from .vlm import MODEL, _async_client, _estimate_cost

PROPOSAL_CONCURRENCY = int(os.environ.get("VLM_PROPOSAL_CONCURRENCY", "8"))
MAX_PROPOSAL_TOKENS = int(os.environ.get("VLM_PROPOSAL_MAX_TOKENS", "1500"))


@dataclass
class Proposal:
    frame_name: str
    phrase: str  # specific name ("MacBook Air M3")
    fallback: str  # short fallback ("silver laptop")
    bbox_norm: tuple[float, float, float, float]  # (x, y, w, h) in [0, 1]
    confidence: float


_PROPOSER_PROMPT = """You're inventorying objects in a 3D scan of a real room. List EVERY distinct physical object visible in this image — including SMALL items: socks, pens, mugs, books, plush toys, figurines, remotes, cables, tape dispensers, stationery, jewellery. Small items are NOT "parts" of whatever surface they rest on; a sock on a bed is its own entry, not part of the bed.

For each object, return:
- "phrase": the most specific canonical name for the WHOLE object. Brand/model/character is encouraged when clearly visible ("MacBook Air M3", "Stitch plush toy", "Amazon Echo Dot"). Material/colour descriptors are encouraged ("white cotton sock", "plaid pajama pants", "Lilo & Stitch plush toy", "spiral notebook").
- "fallback": the bare common noun ("laptop", "plush toy", "speaker", "sock", "notebook").
- "bbox": [x, y, w, h] in normalized [0, 1] image coords, where (x, y) is the top-left corner.
- "confidence": 0..1.

CRITICAL — never combine TWO distinct objects into one entry. The phrase MUST NOT contain the connectors "with", "and", "on", "next", "near", "behind", "under", "above" used to fold one object into another's name. If you see two objects together (e.g. clothes draped over a door, or a notebook with a pen on it), return TWO entries — one for each object — never a single compound entry like "door with clothes" or "notebook with pen". Adjective chains describing ONE object are fine ("white cotton sock", "Lilo & Stitch plush toy"); compound phrases joining TWO objects are not.

Don't decompose monolithic objects into their physical parts. A door has a handle/frame/hinges — return ONE entry, "door", not three. A laptop has a keyboard and screen — return one entry. But a remote on a sofa, a sock on a bed, or a mug on a desk IS its own entry — those are physically detached.

Skip walls, floors, ceilings, windows, and large architectural surfaces. Skip people. Skip the same object twice within this image.

Reply with ONE JSON array, no prose, no code fence:
[{"phrase": "MacBook Air M3", "fallback": "laptop", "bbox": [0.41, 0.62, 0.18, 0.10], "confidence": 0.86}, ...]"""


def _frame_to_b64(path: Path) -> str:
    with Image.open(path) as im:
        im = im.convert("RGB")
        # Cap long side to keep the request small; the gateway charges by tokens
        # and Haiku doesn't benefit from > ~1200px input.
        max_side = 1280
        if max(im.size) > max_side:
            im.thumbnail((max_side, max_side), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
    return base64.standard_b64encode(buf.getvalue()).decode()


def _parse(text: str, frame_name: str) -> list[Proposal]:
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`")
        # Drop a leading "json" tag if present.
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[Proposal] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        bbox = item.get("bbox")
        if not (isinstance(bbox, (list, tuple)) and len(bbox) == 4):
            continue
        try:
            bx, by, bw, bh = (float(v) for v in bbox)
        except (TypeError, ValueError):
            continue
        # Reject obviously bogus bboxes.
        if not (0.0 <= bx <= 1.0 and 0.0 <= by <= 1.0):
            continue
        if bw <= 0.0 or bh <= 0.0 or bw > 1.0 or bh > 1.0:
            continue
        if bx + bw > 1.001 or by + bh > 1.001:
            continue
        phrase = str(item.get("phrase", "")).strip()
        if not phrase:
            continue
        out.append(
            Proposal(
                frame_name=frame_name,
                phrase=phrase,
                fallback=str(item.get("fallback", "")).strip(),
                bbox_norm=(bx, by, min(bw, 1.0 - bx), min(bh, 1.0 - by)),
                confidence=float(item.get("confidence", 0.0)),
            )
        )
    return out


async def _propose_one(
    client,
    semaphore: asyncio.Semaphore,
    frame_path: Path,
    scene_id: str = "",
) -> list[Proposal]:
    async with semaphore:
        b64 = await asyncio.to_thread(_frame_to_b64, frame_path)
        with logfire.span(
            "segmentation.vlm_proposal.frame",
            scene_id=scene_id,
            model_id=MODEL,
            frame_name=frame_path.name,
        ) as span:
            t0 = time.perf_counter()
            try:
                resp = await client.messages.create(
                    model=MODEL,
                    max_tokens=MAX_PROPOSAL_TOKENS,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/jpeg",
                                        "data": b64,
                                    },
                                },
                                {"type": "text", "text": _PROPOSER_PROMPT},
                            ],
                        }
                    ],
                )
            except APIError as e:
                span.set_attribute("error", str(e)[:200])
                span.set_attribute("proposal_count", 0)
                return []
            latency_ms = round((time.perf_counter() - t0) * 1000, 1)
            text = "".join(
                block.text for block in resp.content if getattr(block, "type", None) == "text"
            )
            proposals = _parse(text, frame_path.name)
            span.set_attribute("latency_ms", latency_ms)
            span.set_attribute("input_tokens", resp.usage.input_tokens)
            span.set_attribute("output_tokens", resp.usage.output_tokens)
            span.set_attribute("model_response_id", resp.id)
            span.set_attribute("stop_reason", str(getattr(resp, "stop_reason", "")))
            span.set_attribute(
                "est_cost_usd",
                _estimate_cost(resp.usage.input_tokens, resp.usage.output_tokens),
            )
            span.set_attribute("proposal_count", len(proposals))
            # Raw + parsed proposer output. The raw response is the unfiltered
            # VLM JSON; vlm_proposals is what survived bbox-validation in _parse.
            attach_payload(span, "vlm_response_raw", text)
            attach_payload(
                span,
                "vlm_proposals",
                [
                    {
                        "phrase": p.phrase,
                        "fallback": p.fallback,
                        "bbox_norm": list(p.bbox_norm),
                        "confidence": p.confidence,
                    }
                    for p in proposals
                ],
            )
            return proposals


def _cache_path(scene_dir: Path) -> Path:
    return scene_dir / "vlm_proposals.json"


def _cache_load(scene_dir: Path, key: dict) -> list[Proposal] | None:
    p = _cache_path(scene_dir)
    if not p.exists():
        return None
    try:
        blob = json.loads(p.read_text())
    except Exception:
        return None
    if blob.get("key") != key:
        return None
    return [Proposal(**item) for item in blob.get("proposals", [])]


def _cache_save(scene_dir: Path, key: dict, proposals: list[Proposal]) -> None:
    blob = {
        "key": key,
        "proposals": [
            {**asdict(p), "bbox_norm": list(p.bbox_norm)} for p in proposals
        ],
    }
    p = _cache_path(scene_dir)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(blob, indent=2))
    tmp.replace(p)


async def propose(
    scene_dir: Path,
    keyframe_indices: list[int],
    scene_id: str | None = None,
) -> list[Proposal]:
    """Run the VLM proposer on each keyframe in parallel.

    Resolves frame paths via cameras.json (matches sam.run's logic). Caches the
    full result list keyed on (model, frame_names) so re-runs skip the calls.
    """
    sid = scene_id or scene_dir.name
    cameras = json.loads((scene_dir / "cameras.json").read_text())
    frame_dir = scene_dir / "frames"

    # Resolve actual file paths (cameras.json + on-disk fallback).
    sorted_frames = (
        sorted(frame_dir.glob("*.png")) + sorted(frame_dir.glob("*.jpg"))
    )
    frame_paths: list[Path] = []
    for idx in keyframe_indices:
        if 0 <= idx < len(cameras):
            cam = cameras[idx]
            fp = frame_dir / cam.get("frame", "")
            if fp.exists():
                frame_paths.append(fp)
                continue
        if 0 <= idx < len(sorted_frames):
            frame_paths.append(sorted_frames[idx])

    cache_key = {
        "model": MODEL,
        "frame_names": [p.name for p in frame_paths],
    }
    cached = _cache_load(scene_dir, cache_key)
    if cached is not None:
        with logfire.span(
            "segmentation.vlm_proposal.summary",
            scene_id=sid,
            cache="hit",
            frame_count=len(frame_paths),
            proposal_count_total=len(cached),
            parallelism=PROPOSAL_CONCURRENCY,
        ):
            pass
        return cached

    if not frame_paths:
        return []

    client = _async_client()
    semaphore = asyncio.Semaphore(PROPOSAL_CONCURRENCY)
    try:
        results = await asyncio.gather(
            *(_propose_one(client, semaphore, fp, sid) for fp in frame_paths)
        )
    finally:
        await client.close()

    proposals: list[Proposal] = []
    per_frame_counts: list[int] = []
    for r in results:
        per_frame_counts.append(len(r))
        proposals.extend(r)

    with logfire.span(
        "segmentation.vlm_proposal.summary",
        scene_id=sid,
        cache="miss",
        frame_count=len(frame_paths),
        proposal_count_total=len(proposals),
        parallelism=PROPOSAL_CONCURRENCY,
    ) as span:
        span.set_attribute("proposal_count_per_frame", per_frame_counts)
        # Compact inventory of every phrase the proposer returned across all
        # keyframes, paired with its frame + bbox + confidence. This is the
        # row-level evidence the demo cites alongside the per-frame spans.
        attach_payload(
            span,
            "proposals",
            [
                {
                    "frame": p.frame_name,
                    "phrase": p.phrase,
                    "fallback": p.fallback,
                    "bbox_norm": list(p.bbox_norm),
                    "confidence": p.confidence,
                }
                for p in proposals
            ],
        )

    try:
        _cache_save(scene_dir, cache_key, proposals)
    except OSError:
        pass

    return proposals
