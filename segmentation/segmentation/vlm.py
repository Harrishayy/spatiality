"""VLM batched labeling via Pydantic AI Gateway.

Spec: plans/modules/03_segmentation.md + plans/modules/08_observability.md.

Hard rules (from CLAUDE.md):
- Every model call routes through Pydantic AI Gateway.
- Anthropic SDK uses auth_token (Bearer), NOT api_key.
- Base URL is https://gateway-eu.pydantic.dev/proxy/anthropic/

Batching: tile 4-6 cropped object thumbnails into a single grid image with
big cluster IDs overlaid; ask Claude Haiku for one JSON response keyed by
cluster ID. ~6x cheaper than per-cluster calls.

Caching: scene_dir/vlm_cache.json maps cluster_id -> result. Idempotent.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import logfire
from anthropic import Anthropic, AsyncAnthropic
from PIL import Image, ImageDraw, ImageFont

from shared.observability import attach_payload

from .lift import Cluster

GATEWAY_URL = os.environ.get(
    "PYDANTIC_GATEWAY_URL", "https://gateway-eu.pydantic.dev/proxy/anthropic/"
)
# The same pylf_v... token doubles as Gateway auth — accept either var name.
GATEWAY_KEY_ENVS = ("PYDANTIC_GATEWAY_KEY", "PYDANTIC_API_KEY")
MODEL = os.environ.get("VLM_MODEL", "claude-haiku-4-5")
BATCH_SIZE = int(os.environ.get("VLM_BATCH_SIZE", "5"))
TILE_PX = int(os.environ.get("VLM_TILE_PX", "320"))
PAD_FRAC = 0.08  # bbox padding around mask before crop
# Cap on concurrent Anthropic API calls during cluster labeling. Each batch
# sends ~5 cropped tiles in one request; 6 in flight = ~30 tiles in flight,
# well under typical Pydantic AI Gateway concurrency limits but plenty to
# saturate network round-trips and hide latency.
VLM_LABEL_CONCURRENCY = int(os.environ.get("VLM_LABEL_CONCURRENCY", "6"))


@dataclass
class Label:
    label: str
    confidence: float
    alternatives: list[str]


def client_kwargs() -> dict:
    """Pydantic AI Gateway connection params shared by sync + async clients."""
    key = next((os.environ[k] for k in GATEWAY_KEY_ENVS if os.environ.get(k)), None)
    if not key:
        raise RuntimeError(
            f"none of {GATEWAY_KEY_ENVS} set — cannot call Pydantic AI Gateway"
        )
    return {"base_url": GATEWAY_URL, "auth_token": key}


def _client() -> Anthropic:
    return Anthropic(**client_kwargs())


def _async_client() -> AsyncAnthropic:
    return AsyncAnthropic(**client_kwargs())


def _load_cache(path: Path) -> dict[str, dict]:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}
    return {}


def _save_cache(path: Path, cache: dict[str, dict]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(cache, indent=2))
    tmp.replace(path)


def _crop(scene_dir: Path, cluster: Cluster) -> Image.Image | None:
    if not cluster.anchor_frame or not cluster.anchor_mask_bbox:
        return None
    frame = Image.open(scene_dir / "frames" / cluster.anchor_frame).convert("RGB")
    x, y, w, h = cluster.anchor_mask_bbox
    pad_x = int(w * PAD_FRAC)
    pad_y = int(h * PAD_FRAC)
    box = (
        max(0, x - pad_x),
        max(0, y - pad_y),
        min(frame.width, x + w + pad_x),
        min(frame.height, y + h + pad_y),
    )
    return frame.crop(box)


def _tile(crops: list[tuple[str, Image.Image, str]]) -> Image.Image:
    """Tile (cluster_id, image, hint) tuples into a 2-col grid.

    `hint` is the proposed phrase from the VLM proposer (or "(sam)" if SAM-only).
    Drawn under the cluster id so the labeler sees the prior hypothesis.
    """
    n = len(crops)
    cols = 2 if n > 1 else 1
    rows = (n + cols - 1) // cols
    cell = TILE_PX
    pad = 12
    label_h = 60  # taller — fits id + hint
    total_w = cols * cell + (cols + 1) * pad
    total_h = rows * (cell + label_h) + (rows + 1) * pad
    grid = Image.new("RGB", (total_w, total_h), (20, 20, 20))
    draw = ImageDraw.Draw(grid)
    try:
        font_id = ImageFont.truetype("DejaVuSans-Bold.ttf", 24)
        font_hint = ImageFont.truetype("DejaVuSans.ttf", 16)
    except OSError:
        font_id = ImageFont.load_default()
        font_hint = font_id

    for i, (cid, img, hint) in enumerate(crops):
        c = i % cols
        r = i // cols
        x0 = pad + c * (cell + pad)
        y0 = pad + r * (cell + label_h + pad)
        draw.rectangle([x0, y0, x0 + cell, y0 + label_h], fill=(255, 255, 255))
        draw.text((x0 + 8, y0 + 4), cid, fill=(20, 20, 20), font=font_id)
        if hint:
            # Truncate to fit cell width.
            hint_text = hint if len(hint) <= 40 else hint[:37] + "…"
            draw.text((x0 + 8, y0 + 32), hint_text, fill=(80, 80, 80), font=font_hint)
        thumb = img.copy()
        thumb.thumbnail((cell, cell), Image.LANCZOS)
        grid.paste(thumb, (x0 + (cell - thumb.width) // 2, y0 + label_h + (cell - thumb.height) // 2))
    return grid


def _to_b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return base64.standard_b64encode(buf.getvalue()).decode()


_PROMPT = """You're labeling objects in a 3D scan of a room.

Each tile shows one cropped region with its ID labeled in white (e.g. "obj_001"). A small grey hint under the ID is the prior guess from a wide-angle pass — confirm it, refine it, or override it based on the cropped image.

For each tile return ONE of:
1. A specific label. Use brand or model where visible (e.g. "MacBook Air M3", "Yeti microphone"); otherwise a short descriptive phrase ("stack of hardcover books"). Confidence is 0..1.
2. "none" — if the crop shows wall, floor, ceiling, window, blur, empty space, or nothing identifiable. Set confidence to 0.
3. A duplicate flag — if two tiles clearly show the same physical object, keep the higher-confidence one as a real label and on the OTHER tile set "alternatives": ["duplicate_of:obj_XXX"] (replace with the surviving ID). The duplicate's "label" can be the same string as the survivor; the alternatives flag is what matters.

Reply with ONE JSON object keyed by ID, no prose, no code fence:
{
  "obj_001": {"label": "MacBook Air M3", "confidence": 0.91, "alternatives": ["laptop"]},
  "obj_002": {"label": "none", "confidence": 0.0, "alternatives": []},
  "obj_003": {"label": "MacBook Air M3", "confidence": 0.55, "alternatives": ["duplicate_of:obj_001"]}
}"""


def _parse(text: str) -> dict[str, Label]:
    s = text.strip()
    if s.startswith("```"):
        # Strip code fence if model returns one despite instructions.
        s = s.strip("`").lstrip("json").strip()
    data = json.loads(s)
    out: dict[str, Label] = {}
    for cid, v in data.items():
        out[cid] = Label(
            label=str(v.get("label", "unknown")),
            confidence=float(v.get("confidence", 0.0)),
            alternatives=[str(a) for a in v.get("alternatives", []) or []],
        )
    return out


def _call_batch(
    client: Anthropic, batch: list[tuple[str, Image.Image, str]]
) -> dict[str, Label]:
    grid = _tile(batch)
    b64 = _to_b64(grid)
    cluster_ids = [cid for cid, _, _ in batch]
    hints = {cid: hint for cid, _, hint in batch}
    with logfire.span(
        "segmentation.vlm_label.batch",
        model_id=MODEL,
        batch_size=len(batch),
        cluster_ids=cluster_ids,
    ) as span:
        attach_payload(span, "tile_hints", hints)
        t0 = time.perf_counter()
        resp = client.messages.create(
            model=MODEL,
            max_tokens=600,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
                        },
                        {"type": "text", "text": _PROMPT},
                    ],
                }
            ],
        )
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        text = "".join(block.text for block in resp.content if getattr(block, "type", None) == "text")
        span.set_attribute("latency_ms", latency_ms)
        span.set_attribute("input_tokens", resp.usage.input_tokens)
        span.set_attribute("output_tokens", resp.usage.output_tokens)
        span.set_attribute("model_response_id", resp.id)
        span.set_attribute("stop_reason", str(getattr(resp, "stop_reason", "")))
        # Gateway also auto-attaches cost; this is a backstop estimate.
        span.set_attribute("est_cost_usd", _estimate_cost(resp.usage.input_tokens, resp.usage.output_tokens))
        # Raw + parsed VLM output as span attrs — this is the "what did the
        # VLM actually say" evidence the demo cites. Truncated by attach_payload
        # so a runaway response can't blow the OTLP attribute budget.
        attach_payload(span, "vlm_response_raw", text)
        try:
            parsed = _parse(text)
            labels_payload = {
                cid: {
                    "label": l.label,
                    "confidence": l.confidence,
                    "alternatives": l.alternatives,
                }
                for cid, l in parsed.items()
            }
            attach_payload(span, "vlm_labels", labels_payload)
            span.set_attribute("parsed_count", len(parsed))
        except Exception as exc:
            span.set_attribute("parse_error", str(exc)[:200])
            raise
    return parsed


# Claude Haiku 4.5 published pricing (per 1M tokens). Update if pricing changes.
_HAIKU_INPUT_PER_M = 1.0
_HAIKU_OUTPUT_PER_M = 5.0


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return round(
        (input_tokens / 1_000_000) * _HAIKU_INPUT_PER_M
        + (output_tokens / 1_000_000) * _HAIKU_OUTPUT_PER_M,
        6,
    )


async def _label_batches_concurrent(
    batches: list[list[tuple[str, Image.Image, str]]],
) -> list[dict[str, Label] | BaseException]:
    """Run every batch's Anthropic call in parallel, capped by a semaphore.

    Uses `asyncio.to_thread(_call_batch, ...)` — the sync `Anthropic` client
    is thread-safe and re-using it across coroutines avoids the overhead of
    spinning up a separate `AsyncAnthropic` per task. Returns a list aligned
    with `batches`; entries are either parsed dicts or the raised exception
    (caller handles fallback labelling)."""
    if not batches:
        return []
    client = _client()
    sem = asyncio.Semaphore(VLM_LABEL_CONCURRENCY)

    async def _one(batch: list[tuple[str, Image.Image, str]]):
        async with sem:
            return await asyncio.to_thread(_call_batch, client, batch)

    return await asyncio.gather(*(_one(b) for b in batches), return_exceptions=True)


def label_clusters(scene_dir: Path, clusters: list[Cluster]) -> dict[str, Label]:
    """Label every cluster (using cache for idempotency). Returns id -> Label.

    Each tile carries a `hint` — the cluster's `proposed_phrase` from the VLM
    proposer (when sourced from VLM), otherwise "(sam)" so the labeler knows
    the region came from SAM enumeration without a prior phrase.

    Batches are dispatched **concurrently** via asyncio.gather + a semaphore
    capped at VLM_LABEL_CONCURRENCY. The previous sequential batch loop paid
    full network round-trip latency per batch (~2-3 s × N batches). Now N
    batches go in parallel, so wall time ≈ slowest single batch.
    """
    cache_path = scene_dir / "vlm_cache.json"
    cache = _load_cache(cache_path)
    results: dict[str, Label] = {
        cid: Label(**v) for cid, v in cache.items() if isinstance(v, dict)
    }

    todo: list[tuple[str, Image.Image, str]] = []
    for c in clusters:
        if c.id in results:
            continue
        crop = _crop(scene_dir, c)
        if crop is None:
            results[c.id] = Label(label="unknown", confidence=0.0, alternatives=[])
            continue
        hint = c.proposed_phrase or "(sam)"
        todo.append((c.id, crop, hint))

    if todo:
        batches = [todo[i : i + BATCH_SIZE] for i in range(0, len(todo), BATCH_SIZE)]
        batch_results = asyncio.run(_label_batches_concurrent(batches))
        for batch, batch_outcome in zip(batches, batch_results):
            if isinstance(batch_outcome, Exception):
                err = str(batch_outcome)[:64]
                for cid, _, _ in batch:
                    results[cid] = Label(
                        label="unknown", confidence=0.0, alternatives=[err]
                    )
                continue
            for cid, _, _ in batch:
                results[cid] = batch_outcome.get(
                    cid, Label(label="unknown", confidence=0.0, alternatives=[])
                )

    # Summary telemetry: count rejection / duplicate flags so the funnel is
    # visible in logfire alongside the per-batch spans.
    rejected_none = sum(1 for l in results.values() if l.label.lower() == "none")
    dropped_dup = sum(
        1
        for l in results.values()
        if l.alternatives and str(l.alternatives[0]).startswith("duplicate_of:")
    )
    kept = len(results) - rejected_none - dropped_dup
    sourced_sam = sum(1 for c in clusters if tuple(c.sources) == ("sam",))
    sourced_vlm = sum(1 for c in clusters if tuple(c.sources) == ("vlm",))
    sourced_both = sum(1 for c in clusters if set(c.sources) == {"sam", "vlm"})
    with logfire.span(
        "segmentation.vlm_label.summary",
        cluster_count=len(clusters),
        rejected_none_count=rejected_none,
        dropped_duplicate_count=dropped_dup,
        kept_count=kept,
        sourced_sam=sourced_sam,
        sourced_vlm=sourced_vlm,
        sourced_both=sourced_both,
    ) as span:
        attach_payload(
            span,
            "labels",
            {
                cid: {
                    "label": l.label,
                    "confidence": l.confidence,
                    "alternatives": l.alternatives,
                }
                for cid, l in results.items()
            },
        )

    _save_cache(
        cache_path,
        {cid: {"label": l.label, "confidence": l.confidence, "alternatives": l.alternatives}
         for cid, l in results.items()},
    )
    return results
