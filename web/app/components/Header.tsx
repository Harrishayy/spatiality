"use client";

import { useEffect, useState } from "react";

import { fetchGatewayHealth } from "@/lib/api";
import type { GatewayHealth, Manifest } from "@/lib/types";

interface Props {
  manifest?: Manifest;
}

export function Header({ manifest }: Props) {
  const status = manifest?.status ?? "queued";
  return (
    <header className="flex items-center justify-between border-b border-ink-800 bg-ink-900/80 px-4 py-2 backdrop-blur">
      <div className="flex items-center gap-3">
        <div className="size-6 rounded-md bg-gradient-to-br from-accent-500 to-accent-300 pin-glow" />
        <div className="flex flex-col leading-tight">
          <span className="text-sm font-semibold tracking-tight">
            Glasses → 3D Twin
          </span>
          <span className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
            {manifest?.scene_id ?? "no scene"}
          </span>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <GatewayBadge />
        <StatusBadge status={status} />
      </div>
    </header>
  );
}

// "Gateway: pylf_v…3a2 · 184ms" — visible proof every model call routes
// through Pydantic AI Gateway. Polls /api/gateway/health once on mount;
// hidden in demo mode (no agent → fetchGatewayHealth returns null).
function GatewayBadge() {
  const [health, setHealth] = useState<GatewayHealth | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let cancelled = false;
    fetchGatewayHealth()
      .then((h) => {
        if (!cancelled) setHealth(h);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  if (error || (!health && !error)) return null;
  if (!health) return null;
  const region = health.gateway_url.includes("-eu") ? "eu" : health.gateway_url.includes("-us") ? "us" : "?";
  return (
    <a
      href={health.gateway_url}
      target="_blank"
      rel="noopener noreferrer"
      title={`Routing through Pydantic AI Gateway · ${health.gateway_url}\nKey: ${health.key_fingerprint}\nProbe: ${health.probe_status ?? "n/a"} in ${health.latency_ms}ms`}
      className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-emerald-300 hover:border-emerald-400/60"
    >
      gateway:{region} · {health.key_fingerprint} · {health.latency_ms}ms
    </a>
  );
}

function StatusBadge({ status }: { status: Manifest["status"] }) {
  const tone =
    status === "ready"
      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
      : status === "failed"
        ? "border-red-500/40 bg-red-500/10 text-red-300"
        : "border-accent-400/40 bg-accent-500/10 text-accent-300";
  return (
    <span
      className={`rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider ${tone}`}
    >
      {status}
    </span>
  );
}