"""Single source of truth for Pydantic AI Gateway client construction.

Hard rule from CLAUDE.md:
    Every model call in this project routes through Pydantic AI Gateway.
    Anthropic SDK uses `auth_token` (Bearer header), NOT `api_key`.
    Base URL is https://gateway-eu.pydantic.dev/proxy/anthropic/.

Centralising client construction here lets us:
  1. Enforce the rule (a startup assertion + a CI grep — see scripts/check_gateway.sh)
     so it's impossible to land code that bypasses the Gateway.
  2. Surface a Gateway-health probe to the UI (used by /api/gateway/health) so
     the running build can prove it's hitting the proxy, not Anthropic direct.
  3. Make swapping models trivial — only this module reads MODEL/env, callers
     just import `anthropic_client()` / `async_anthropic_client()`.

Two env vars:
  PYDANTIC_GATEWAY_URL  default https://gateway-eu.pydantic.dev/proxy/anthropic/
  PYDANTIC_GATEWAY_KEY  the pylf_v... token; PYDANTIC_API_KEY also accepted

Set PYDANTIC_GATEWAY_REQUIRED=0 to disable the URL assertion (only for local
unit tests that mock the SDK). On Modal + /agent it's always implicitly on.
"""

from __future__ import annotations

import os
from typing import Any

# The exact prefix every Gateway URL must start with. Region (-eu, -us) is
# the only legal variation per 08_observability.md.
GATEWAY_HOST_PREFIX = "https://gateway-"
GATEWAY_HOST_SUFFIX = ".pydantic.dev/"

GATEWAY_KEY_ENVS = ("PYDANTIC_GATEWAY_KEY", "PYDANTIC_API_KEY")
DEFAULT_GATEWAY_URL = "https://gateway-eu.pydantic.dev/proxy/anthropic/"


class GatewayConfigurationError(RuntimeError):
    """Raised when client construction would bypass the Gateway."""


def gateway_url() -> str:
    return os.environ.get("PYDANTIC_GATEWAY_URL", DEFAULT_GATEWAY_URL)


def gateway_key() -> str:
    """Return the Gateway auth token. Raises if no env var is set."""
    for k in GATEWAY_KEY_ENVS:
        v = os.environ.get(k)
        if v:
            return v
    raise GatewayConfigurationError(
        f"none of {GATEWAY_KEY_ENVS} set — cannot route through Pydantic AI Gateway"
    )


def _assert_gateway_url(url: str) -> None:
    """Fail fast if `url` would bypass the Gateway.

    The assertion is on by default. Disable only in unit tests with
    PYDANTIC_GATEWAY_REQUIRED=0.
    """
    if os.environ.get("PYDANTIC_GATEWAY_REQUIRED", "1") == "0":
        return
    if not (url.startswith(GATEWAY_HOST_PREFIX) and GATEWAY_HOST_SUFFIX in url):
        raise GatewayConfigurationError(
            f"Anthropic client base_url {url!r} does not point at Pydantic AI Gateway "
            f"(expected prefix {GATEWAY_HOST_PREFIX}<region>{GATEWAY_HOST_SUFFIX}). "
            "Every model call must route through the Gateway — see CLAUDE.md."
        )


def client_kwargs() -> dict[str, Any]:
    """Anthropic client kwargs pointed at the Gateway."""
    url = gateway_url()
    _assert_gateway_url(url)
    return {"base_url": url, "auth_token": gateway_key()}


def anthropic_client():
    """Synchronous Anthropic client routed through the Gateway."""
    from anthropic import Anthropic

    return Anthropic(**client_kwargs())


def async_anthropic_client():
    """Async Anthropic client routed through the Gateway."""
    from anthropic import AsyncAnthropic

    return AsyncAnthropic(**client_kwargs())


def gateway_fingerprint() -> dict[str, str]:
    """Non-secret summary for the UI footer / /api/gateway/health.

    Returns the gateway URL plus a masked tail of the auth token so the
    running build can prove which token it's holding without leaking it.
    """
    try:
        key = gateway_key()
        masked = f"{key[:6]}…{key[-4:]}" if len(key) >= 12 else "set"
    except GatewayConfigurationError:
        masked = "unset"
    return {"gateway_url": gateway_url(), "key_fingerprint": masked}
