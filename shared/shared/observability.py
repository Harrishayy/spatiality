"""Logfire wiring + canonical span names.

Span names are demo evidence. Always import the constants here; never inline
span name strings.
"""

from __future__ import annotations

import json
import os
from typing import Any

import logfire

SPAN_CAPTURE_EXTRACT = "capture.extract_frames"
SPAN_INFERENCE_VGGT = "inference.vggt"
SPAN_INFERENCE_SPLAT = "inference.splat"
SPAN_SEGMENTATION_SAM3 = "segmentation.sam3"
SPAN_SEGMENTATION_VLM_PROPOSAL = "segmentation.vlm_proposal"
SPAN_SEGMENTATION_VLM = "segmentation.vlm_label"
SPAN_AGENT_LOCATE = "agent.locate"
SPAN_AGENT_CHAT = "agent.chat"
SPAN_AGENT_CHAT_TOOL = "agent.chat.tool"

# Modal-side wrapper spans — every web endpoint + spawnable wraps its body in
# one of these so the trace timeline shows wall-clock per request, including
# volume reload/commit and subprocess overhead that lives outside the named
# pipeline spans (inference.vggt, segmentation.sam3, ...).
SPAN_MODAL_PROCESS_VIDEO = "modal.process_video"
SPAN_MODAL_RUN_INFERENCE = "modal.run_inference"
SPAN_MODAL_RUN_SEGMENTATION = "modal.run_segmentation"
SPAN_MODAL_PREPARE_SCENE = "modal.prepare_scene"

# Wireframe build (segmentation post-step). Produces wireframe.ply +
# wireframe_index.json for the viewer's Wireframe view mode.
SPAN_WIREFRAME_BUILD = "wireframe.build"


_PAYLOAD_LIMIT = 16_000  # bytes; OTLP attribute limit is generous but bounded.


def _pydantic_token() -> str | None:
    """Resolve the Pydantic token. The same pylf_v... token doubles as Logfire
    trace auth and Gateway proxy auth, so we accept either var name.
    """
    return os.environ.get("LOGFIRE_TOKEN") or os.environ.get("PYDANTIC_API_KEY")


def configure_logfire(service: str) -> None:
    """Configure Logfire for a pipeline service.

    No-op (local-only) if no Pydantic token is in env, so dev runs work offline.

    Also enables `logfire.instrument_anthropic()` once the SDK is configured.
    The instrumentation hooks every `messages.create` call across the codebase
    (segmentation labeler, segmentation proposer, agent chat / locate routes
    if/when they share this module) so each call emits a span carrying the
    canonical `gen_ai.usage.cost`, `gen_ai.usage.input_tokens` and
    `gen_ai.usage.output_tokens` attributes that the agent-side
    `aggregateCost` / scenes-page CostBadge keys off.

    Best-effort: if the Anthropic SDK isn't installed in this service's image,
    skip silently rather than refusing to configure observability at all.
    """
    token = _pydantic_token()
    if not token:
        logfire.configure(send_to_logfire=False, service_name=service)
    else:
        logfire.configure(token=token, service_name=service)

    try:
        logfire.instrument_anthropic()
    except Exception:
        # Either anthropic isn't importable in this service or the
        # instrumentation API moved — neither should block the service from
        # starting. The hand-rolled `est_cost_usd` / `input_tokens` attrs
        # remain a backstop in segmentation/vlm.py.
        pass


def attach_payload(span, key: str, payload: Any) -> None:
    """Attach a JSON payload (dict / list / str) to a span attribute.

    Compact-encoded and truncated to _PAYLOAD_LIMIT so large model responses
    don't blow up OTLP attribute size. Truncated payloads get a "_truncated"
    suffix attribute carrying the original byte length.
    """
    if isinstance(payload, str):
        body = payload
    else:
        try:
            body = json.dumps(payload, default=str, separators=(",", ":"))
        except (TypeError, ValueError):
            body = repr(payload)
    raw_len = len(body)
    if raw_len > _PAYLOAD_LIMIT:
        body = body[:_PAYLOAD_LIMIT]
        span.set_attribute(f"{key}_truncated_from", raw_len)
    span.set_attribute(key, body)
