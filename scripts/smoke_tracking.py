"""Smoke test for Logfire + Pydantic AI Gateway tracking.

What this exercises:
  1. configure_logfire() with a real LOGFIRE_TOKEN
  2. Anthropic SDK -> Pydantic AI Gateway (auth_token Bearer, EU base URL)
  3. Nested logfire.span structure mirroring real pipeline traces
  4. Milestone event (logfire.info) inside the inner span — same pattern
     08_observability.md prescribes for `inference.splat`
  5. Confirms the response carries cost/token metadata Gateway attaches

Run:
  source .env && uv run python scripts/smoke_tracking.py

Output:
  - timing for the call
  - usage from Anthropic response (input/output tokens)
  - the trace ID (so you can deep-link the run)
  - the Logfire URL filter to view it

Cost: ~$0.0001 per run (one Haiku call, ~50 input + ~30 output tokens).
"""

from __future__ import annotations

import os
import sys
import time

import logfire
from anthropic import Anthropic

from shared.observability import (
    SPAN_AGENT_LOCATE,
    SPAN_SEGMENTATION_VLM,
    configure_logfire,
)

GATEWAY_URL = os.environ.get(
    "PYDANTIC_GATEWAY_URL", "https://gateway-eu.pydantic.dev/proxy/anthropic/"
)
LOGFIRE_PROJECT = os.environ.get("LOGFIRE_PROJECT", "glasses-twin-hackathon")


def _maybe_load_dotenv() -> None:
    """Pull only the keys we need from .env, tolerating malformed lines.

    Avoids `source .env` because the file may contain non-KEY=VALUE lines
    (e.g. bare tokens) that bash refuses to evaluate.
    """
    needed = {
        "LOGFIRE_TOKEN", "PYDANTIC_GATEWAY_KEY", "PYDANTIC_GATEWAY_URL",
        "PYDANTIC_API_KEY",
    }
    if (os.environ.get("LOGFIRE_TOKEN") or os.environ.get("PYDANTIC_API_KEY")) \
       and (os.environ.get("PYDANTIC_GATEWAY_KEY") or os.environ.get("PYDANTIC_API_KEY")):
        return
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(repo_root, ".env")
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip().lstrip("export ").strip()
            value = value.strip().strip("'\"")
            if key in needed and not os.environ.get(key):
                os.environ[key] = value


def _check_env() -> None:
    _maybe_load_dotenv()
    # Two distinct tokens: LOGFIRE_TOKEN for tracing, gateway key for proxy auth.
    # Spec accepts the same token for both, but in practice they're often separate.
    logfire_tok = os.environ.get("LOGFIRE_TOKEN") or os.environ.get("PYDANTIC_API_KEY")
    gateway_tok = (
        os.environ.get("PYDANTIC_GATEWAY_KEY")
        or os.environ.get("PYDANTIC_API_KEY")
        or os.environ.get("LOGFIRE_TOKEN")
    )
    if not logfire_tok:
        sys.exit("missing env: LOGFIRE_TOKEN (or PYDANTIC_API_KEY)")
    if not gateway_tok:
        sys.exit("missing env: PYDANTIC_GATEWAY_KEY (or PYDANTIC_API_KEY)")
    # Mirror into the spec-named vars so downstream code that reads only
    # those still works.
    os.environ.setdefault("LOGFIRE_TOKEN", logfire_tok)
    os.environ.setdefault("PYDANTIC_GATEWAY_KEY", gateway_tok)
    if not GATEWAY_URL.endswith("/"):
        sys.exit(f"PYDANTIC_GATEWAY_URL must end with '/', got: {GATEWAY_URL}")
    print(f"  PYDANTIC_GATEWAY_URL={GATEWAY_URL}")
    print(f"  LOGFIRE_TOKEN=<set, {len(os.environ['LOGFIRE_TOKEN'])} chars>")
    print(f"  PYDANTIC_GATEWAY_KEY=<set, {len(os.environ['PYDANTIC_GATEWAY_KEY'])} chars>")
    print(f"  same-token: {os.environ['LOGFIRE_TOKEN'] == os.environ['PYDANTIC_GATEWAY_KEY']}")


def _client() -> Anthropic:
    # Routes through shared.gateway so this smoke proves the same client path
    # the real pipeline uses (Anthropic SDK + Bearer auth_token + Gateway URL).
    from shared.gateway import anthropic_client

    return anthropic_client()


def smoke_one_call(client: Anthropic) -> dict:
    """Inside a fake `segmentation.vlm_label` span, make a single Haiku call.

    Mirrors the structure of the real VLM batched call so the trace shape
    in Logfire matches what the demo will emit.
    """
    with logfire.span(
        SPAN_SEGMENTATION_VLM,
        scene_id="smoke_test",
        cluster_count=1,
    ) as span:
        t0 = time.perf_counter()
        # Milestone event — same pattern as the inference.splat stage marker.
        logfire.info("vlm_call_start", model="claude-haiku-4-5", batch_size=1)
        resp = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=32,
            messages=[
                {
                    "role": "user",
                    "content": "Reply with exactly the word: ack",
                }
            ],
        )
        latency = time.perf_counter() - t0
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        usage = {
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
        }
        # Attach attrs the demo waterfall will display.
        span.set_attribute("latency_ms", round(latency * 1000, 1))
        span.set_attribute("input_tokens", usage["input_tokens"])
        span.set_attribute("output_tokens", usage["output_tokens"])
        span.set_attribute("model_id", resp.model)
        span.set_attribute("response_text", text)
    return {"text": text, "latency_s": latency, "usage": usage, "model": resp.model}


def smoke_nested_call(client: Anthropic) -> dict:
    """Same call, but nested under a fake `agent.locate` span — proves the
    parent-child span hierarchy renders correctly in Logfire."""
    with logfire.span(SPAN_AGENT_LOCATE, scene_id="smoke_test") as parent:
        result = smoke_one_call(client)
        parent.set_attribute("downstream_latency_ms", round(result["latency_s"] * 1000, 1))
        return result


def main() -> None:
    print("==> Pre-flight")
    _check_env()

    print("==> Configuring Logfire (service=smoke-tracking)")
    configure_logfire("smoke-tracking")

    # Step 1: prove Logfire-side tracing works WITHOUT the Gateway. This emits
    # a synthetic span tree that mirrors the demo waterfall shape.
    print("==> Logfire-only spans (no Gateway)")
    with logfire.span("smoke.parent", scene_id="smoke_test"):
        for stage in ("capture", "inference", "segmentation"):
            with logfire.span(f"smoke.{stage}", scene_id="smoke_test", stage=stage):
                logfire.info(
                    "smoke_milestone",
                    scene_id="smoke_test",
                    stage=stage,
                    note="Logfire wiring verified",
                )
    print("   ✓ emitted parent + 3 child spans + 3 info events")

    # Step 2: try a real Gateway call. If the key isn't a Gateway proxy key
    # (common: pylf_v... can be Logfire-only), surface a clear actionable
    # message and exit non-zero — Logfire spans above still ship.
    print("==> Gateway call (Anthropic SDK -> Pydantic AI Gateway)")
    try:
        client = _client()
        r1 = smoke_one_call(client)
        print(
            f"   ✓ call 1: text={r1['text']!r}  "
            f"latency={r1['latency_s']*1000:.0f}ms  "
            f"in={r1['usage']['input_tokens']} out={r1['usage']['output_tokens']}  "
            f"model={r1['model']}"
        )
        r2 = smoke_nested_call(client)
        print(
            f"   ✓ call 2 (nested): in={r2['usage']['input_tokens']} "
            f"out={r2['usage']['output_tokens']}"
        )
    except Exception as e:
        print(f"   ✗ gateway call failed: {type(e).__name__}: {str(e)[:120]}")
        print()
        print("   Likely cause: PYDANTIC_GATEWAY_KEY isn't a Gateway proxy key.")
        print("   pylf_... tokens come in two flavours:")
        print("     • Logfire write token  → for tracing only (your LOGFIRE_TOKEN)")
        print("     • Gateway proxy key    → for routing model calls")
        print("   Generate a Gateway proxy key at:")
        print("     Logfire dashboard → AI Gateway → API Keys → Create new")
        print("   Save it as PYDANTIC_GATEWAY_KEY (or PYDANTIC_API_KEY) in .env.")
        sys.exit(2)

    print()
    print("==> Done. Verify in Logfire:")
    print(f"   {os.environ.get('LOGFIRE_PROJECT_URL', 'https://logfire-eu.pydantic.dev/spatial/3d')}")
    print(f"   filter:  scene_id=\"smoke_test\"")
    print()
    print("Expected:")
    print("   - smoke.parent with 3 children (smoke.capture, smoke.inference, smoke.segmentation)")
    print("   - segmentation.vlm_label (top-level)")
    print("   - agent.locate containing one segmentation.vlm_label child")
    print("   - Anthropic-SDK auto-instrumented child spans with model/tokens/cost")


if __name__ == "__main__":
    main()
