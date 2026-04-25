"""Logfire wiring + canonical span names.

Span names are demo evidence — see plans/modules/08_observability.md table.
Always import the constants here; never inline span name strings.
"""

from __future__ import annotations

import os

import logfire

SPAN_CAPTURE_EXTRACT = "capture.extract_frames"
SPAN_INFERENCE_VGGT = "inference.vggt"
SPAN_INFERENCE_3DGRUT = "inference.3dgrut"
SPAN_SEGMENTATION_SAM3 = "segmentation.sam3"
SPAN_SEGMENTATION_VLM = "segmentation.vlm_label"
SPAN_AGENT_LOCATE = "agent.locate"


def configure_logfire(service: str) -> None:
    """Configure Logfire for a pipeline service.

    No-op (local-only) if LOGFIRE_TOKEN is unset, so dev runs work offline.
    """
    token = os.environ.get("LOGFIRE_TOKEN")
    if not token:
        logfire.configure(send_to_logfire=False, service_name=service)
        return
    logfire.configure(token=token, service_name=service)
