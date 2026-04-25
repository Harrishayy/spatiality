"""Logfire wiring + canonical span names.

Span names are demo evidence — see plans/modules/08_observability.md table.
Always import the constants here; never inline span name strings.
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

# Modal-side wrapper spans — every web endpoint + spawnable wraps its body in
# one of these so the trace timeline shows wall-clock per request, including
# volume reload/commit and subprocess overhead that lives outside the named
# pipeline spans (inference.vggt, segmentation.sam3, ...).
SPAN_MODAL_PROCESS_VIDEO = "modal.process_video"
SPAN_MODAL_RUN_INFERENCE = "modal.run_inference"
SPAN_MODAL_RUN_SEGMENTATION = "modal.run_segmentation"
SPAN_MODAL_PREPARE_SCENE = "modal.prepare_scene"


_PAYLOAD_LIMIT = 16_000  # bytes; OTLP attribute limit is generous but bounded.


def _pydantic_token() -> str | None:
    """Resolve the Pydantic token. Per 08_observability.md the same pylf_v...
    token doubles as Logfire trace auth and Gateway proxy auth, so we accept
    either var name.
    """
    return os.environ.get("LOGFIRE_TOKEN") or os.environ.get("PYDANTIC_API_KEY")


def configure_logfire(service: str) -> None:
    """Configure Logfire for a pipeline service.

    No-op (local-only) if no Pydantic token is in env, so dev runs work offline.
    """
    token = _pydantic_token()
    if not token:
        logfire.configure(send_to_logfire=False, service_name=service)
        return
    logfire.configure(token=token, service_name=service)


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
