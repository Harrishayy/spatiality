#!/usr/bin/env bash
# Guard rail: every Anthropic / AsyncAnthropic instantiation in this repo MUST
# come from shared.gateway (or use shared.gateway.client_kwargs). If you see
# this script fail in CI, refactor the offending callsite to import from
# shared.gateway instead — that's the only place that holds the Pydantic AI
# Gateway base_url + auth_token (per CLAUDE.md hard rule).
#
# Allow-list is intentionally short: only files inside shared/ are exempt
# from the prohibition (they ARE the gateway abstraction).

set -euo pipefail

cd "$(dirname "$0")/.."

PATTERN='\b(Async)?Anthropic\s*\('
ALLOW_DIRS='shared/|.venv/|node_modules/|old/|.claude/'
# The gateway abstraction itself is allowed to instantiate Anthropic — it's
# the *only* place that should. Two file paths are the abstraction:
#   shared/shared/gateway.py  (Python — already covered by ALLOW_DIRS=shared/)
#   agent/src/lib/gateway.ts  (TypeScript twin)
ALLOW_FILES='agent/src/lib/gateway.ts'

violations=$(
  grep -RInE "$PATTERN" \
    --include='*.py' --include='*.ts' --include='*.tsx' \
    . 2>/dev/null \
  | grep -Ev "$ALLOW_DIRS" \
  | grep -Ev "$ALLOW_FILES" \
  | grep -Ev '\b(import|from)\b' \
  || true
)

if [[ -n "$violations" ]]; then
  echo "ERROR: direct Anthropic instantiation outside shared.gateway:" >&2
  echo "$violations" >&2
  echo >&2
  echo "Use shared.gateway.anthropic_client() / async_anthropic_client() instead." >&2
  exit 1
fi

echo "gateway-only: ok"
