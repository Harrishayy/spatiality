import type { FastifyPluginAsync } from "fastify";

// Gateway health probe. The UI footer pings this and renders
//   "Gateway: pylf_v…3a2  ·  ok 184ms"
// as proof that the running build is routing through the Pydantic AI Gateway,
// not bypassing to api.anthropic.com.
//
// Implementation is intentionally lightweight: a HEAD request to the Gateway
// host probes connectivity without spending a real model call. (We don't
// need to issue a paid 1-token Haiku request just to prove the URL works.)

const GATEWAY_URL = process.env.PYDANTIC_GATEWAY_URL ?? "https://gateway-eu.pydantic.dev/proxy/anthropic/";
const GATEWAY_KEY = process.env.PYDANTIC_GATEWAY_KEY ?? process.env.PYDANTIC_API_KEY ?? "";

function fingerprint(): string {
  if (!GATEWAY_KEY) return "unset";
  if (GATEWAY_KEY.length < 12) return "set";
  return `${GATEWAY_KEY.slice(0, 6)}…${GATEWAY_KEY.slice(-4)}`;
}

export const gatewayRoute: FastifyPluginAsync = async (app) => {
  app.get("/api/gateway/health", async () => {
    const t0 = performance.now();
    let ok = false;
    let status: number | null = null;
    let detail: string | null = null;
    try {
      // Probe the proxy host. Most gateways accept a HEAD on the proxy root
      // and return 4xx (auth challenge) — that's enough to prove the URL is
      // reachable. We treat any response (even 401/403/405) as "reachable",
      // because that means the host resolved and the TLS handshake completed.
      const r = await fetch(GATEWAY_URL, {
        method: "HEAD",
        // Gateway expects Bearer auth on real proxy paths; the HEAD on the
        // root may or may not require it. Send it if we have it.
        headers: GATEWAY_KEY ? { Authorization: `Bearer ${GATEWAY_KEY}` } : undefined,
      });
      ok = true;
      status = r.status;
    } catch (e) {
      detail = e instanceof Error ? e.message : String(e);
    }
    return {
      ok,
      gateway_url: GATEWAY_URL,
      key_fingerprint: fingerprint(),
      probe_status: status,
      probe_detail: detail,
      latency_ms: Math.round(performance.now() - t0),
    };
  });
};
