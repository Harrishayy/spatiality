import type { FastifyPluginAsync } from "fastify";

// Gateway health probe. The UI footer pings this and renders
//   "gateway:eu · ok 184ms"
// as proof that the running build is routing through the Pydantic AI Gateway,
// not bypassing to api.anthropic.com.
//
// IMPORTANT: this endpoint is unauthenticated and reachable from the browser.
// Do NOT include the gateway URL or any chars of the key in the response —
// `key_set` and a derived `region` are the only signals the UI needs.

const GATEWAY_URL =
  process.env.PYDANTIC_GATEWAY_URL ?? "https://gateway-eu.pydantic.dev/proxy/anthropic/";
const GATEWAY_KEY = process.env.PYDANTIC_GATEWAY_KEY ?? process.env.PYDANTIC_API_KEY ?? "";

function region(): "eu" | "us" | "unknown" {
  if (GATEWAY_URL.includes("-eu")) return "eu";
  if (GATEWAY_URL.includes("-us")) return "us";
  return "unknown";
}

export const gatewayRoute: FastifyPluginAsync = async (app) => {
  app.get("/api/gateway/health", async () => {
    const t0 = performance.now();
    let ok = false;
    let status: number | null = null;
    try {
      const r = await fetch(GATEWAY_URL, {
        method: "HEAD",
        headers: GATEWAY_KEY ? { Authorization: `Bearer ${GATEWAY_KEY}` } : undefined,
      });
      ok = true;
      status = r.status;
    } catch {
      // Swallow — `ok` already signals reachability. Echoing network-error
      // strings to the browser doesn't help debug and risks leaking host info.
    }
    return {
      ok,
      key_set: GATEWAY_KEY.length > 0,
      region: region(),
      probe_status: status,
      latency_ms: Math.round(performance.now() - t0),
    };
  });
};
