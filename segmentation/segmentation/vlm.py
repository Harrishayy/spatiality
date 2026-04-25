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

import base64
import io
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import logfire
from anthropic import Anthropic
from PIL import Image, ImageDraw, ImageFont

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


@dataclass
class Label:
    label: str
    confidence: float
    alternatives: list[str]


def _client() -> Anthropic:
    key = next((os.environ[k] for k in GATEWAY_KEY_ENVS if os.environ.get(k)), None)
    if not key:
        raise RuntimeError(
            f"none of {GATEWAY_KEY_ENVS} set — cannot call Pydantic AI Gateway"
        )
    return Anthropic(base_url=GATEWAY_URL, auth_token=key)


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


def _tile(crops: list[tuple[str, Image.Image]]) -> Image.Image:
    """Tile (cluster_id, image) pairs into a 2-col grid with big id labels."""
    n = len(crops)
    cols = 2 if n > 1 else 1
    rows = (n + cols - 1) // cols
    cell = TILE_PX
    pad = 12
    label_h = 40
    total_w = cols * cell + (cols + 1) * pad
    total_h = rows * (cell + label_h) + (rows + 1) * pad
    grid = Image.new("RGB", (total_w, total_h), (20, 20, 20))
    draw = ImageDraw.Draw(grid)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 28)
    except OSError:
        font = ImageFont.load_default()

    for i, (cid, img) in enumerate(crops):
        c = i % cols
        r = i // cols
        x0 = pad + c * (cell + pad)
        y0 = pad + r * (cell + label_h + pad)
        draw.rectangle([x0, y0, x0 + cell, y0 + label_h], fill=(255, 255, 255))
        draw.text((x0 + 8, y0 + 4), cid, fill=(20, 20, 20), font=font)
        thumb = img.copy()
        thumb.thumbnail((cell, cell), Image.LANCZOS)
        grid.paste(thumb, (x0 + (cell - thumb.width) // 2, y0 + label_h + (cell - thumb.height) // 2))
    return grid


def _to_b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return base64.standard_b64encode(buf.getvalue()).decode()


_PROMPT = """You're labeling objects in a 3D scan of a room.

Each tile in the attached image shows one cropped object with its ID
labeled in white at the top (e.g. "obj_001"). Identify each object as
precisely as possible — use brand or model where visible (e.g. "MacBook Air
M3", "Yeti microphone"), otherwise a short descriptive phrase ("stack of
hardcover books"). Confidence is 0..1.

Reply with ONE JSON object keyed by ID, no prose, no code fence:
{
  "obj_001": {"label": "...", "confidence": 0.91, "alternatives": ["laptop", "MacBook"]},
  "obj_002": {"label": "...", "confidence": 0.74, "alternatives": []}
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


def _call_batch(client: Anthropic, batch: list[tuple[str, Image.Image]]) -> dict[str, Label]:
    grid = _tile(batch)
    b64 = _to_b64(grid)
    cluster_ids = [cid for cid, _ in batch]
    with logfire.span(
        "segmentation.vlm_label.batch",
        model_id=MODEL,
        batch_size=len(batch),
        cluster_ids=cluster_ids,
    ) as span:
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
        # Gateway also auto-attaches cost; this is a backstop estimate.
        span.set_attribute("est_cost_usd", _estimate_cost(resp.usage.input_tokens, resp.usage.output_tokens))
    return _parse(text)


# Claude Haiku 4.5 published pricing (per 1M tokens). Update if pricing changes.
_HAIKU_INPUT_PER_M = 1.0
_HAIKU_OUTPUT_PER_M = 5.0


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return round(
        (input_tokens / 1_000_000) * _HAIKU_INPUT_PER_M
        + (output_tokens / 1_000_000) * _HAIKU_OUTPUT_PER_M,
        6,
    )


def label_clusters(scene_dir: Path, clusters: list[Cluster]) -> dict[str, Label]:
    """Label every cluster (using cache for idempotency). Returns id -> Label."""
    cache_path = scene_dir / "vlm_cache.json"
    cache = _load_cache(cache_path)
    results: dict[str, Label] = {
        cid: Label(**v) for cid, v in cache.items() if isinstance(v, dict)
    }

    todo: list[tuple[str, Image.Image]] = []
    for c in clusters:
        if c.id in results:
            continue
        crop = _crop(scene_dir, c)
        if crop is None:
            results[c.id] = Label(label="unknown", confidence=0.0, alternatives=[])
            continue
        todo.append((c.id, crop))

    if not todo:
        return results

    client = _client()
    for i in range(0, len(todo), BATCH_SIZE):
        batch = todo[i : i + BATCH_SIZE]
        try:
            batch_labels = _call_batch(client, batch)
        except Exception as e:
            for cid, _ in batch:
                results[cid] = Label(label="unknown", confidence=0.0, alternatives=[str(e)[:64]])
            continue
        for cid, _ in batch:
            results[cid] = batch_labels.get(
                cid, Label(label="unknown", confidence=0.0, alternatives=[])
            )

    _save_cache(
        cache_path,
        {cid: {"label": l.label, "confidence": l.confidence, "alternatives": l.alternatives}
         for cid, l in results.items()},
    )
    return results
