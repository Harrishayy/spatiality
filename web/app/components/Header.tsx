"use client";

import { useEffect, useState } from "react";

import { fetchGatewayHealth } from "@/lib/api";
import type { GatewayHealth, Manifest } from "@/lib/types";

interface Props {
  manifest?: Manifest;
}

export function Header({ manifest }: Props) {
  const status = manifest?.status ?? "queued";
  const sceneId = manifest?.scene_id ?? "no scene";
  return (
    <header className="lp-app-header">
      <div className="lp-app-brand">
        <span className="lp-app-brand-mark" />
        <div className="lp-app-brand-meta">
          <span className="lp-app-brand-title">Glasses → 3D Twin</span>
          <span className="lp-app-brand-id">{sceneId}</span>
        </div>
      </div>
      <div />
      <div className="lp-app-header-meta">
        <GatewayBadge />
        <StatusBadge status={status} />
      </div>
    </header>
  );
}

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
  if (error || !health) return null;
  const keyTag = health.key_set ? "key:set" : "key:unset";
  return (
    <span
      title={`Pydantic AI Gateway · ${health.region} · probe ${health.probe_status ?? "n/a"} in ${health.latency_ms}ms`}
      className="lp-status-pill lp-status-pill--ok"
    >
      <span className="lp-status-dot lp-status-dot--ok" />
      gateway:{health.region} · {keyTag} · {health.latency_ms}ms
    </span>
  );
}

function StatusBadge({ status }: { status: Manifest["status"] }) {
  const { pillMod, dotMod } = (() => {
    switch (status) {
      case "ready":
        return { pillMod: "lp-status-pill--ok", dotMod: "lp-status-dot--ok" };
      case "failed":
        return { pillMod: "lp-status-pill--err", dotMod: "lp-status-dot--err" };
      default:
        return { pillMod: "lp-status-pill--warn", dotMod: "lp-status-dot--warn" };
    }
  })();
  return (
    <span className={`lp-status-pill ${pillMod}`}>
      <span className={`lp-status-dot ${dotMod}`} />
      {status}
    </span>
  );
}
