"use client";

import type { Manifest } from "@/lib/types";

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
        <StatusBadge status={status} />
      </div>
    </header>
  );
}

function StatusBadge({ status }: { status: Manifest["status"] }) {
  // Steady "ready" is the silent default — no pill in the corner once the
  // scene loads. Only surface the badge while something is in-flight or has
  // gone wrong, where the user actually needs the signal.
  if (status === "ready") return null;
  const { pillMod, dotMod, label } =
    status === "failed"
      ? { pillMod: "lp-status-pill--err", dotMod: "lp-status-dot--err", label: "Failed" }
      : { pillMod: "lp-status-pill--warn", dotMod: "lp-status-dot--warn", label: "Loading" };
  return (
    <span className={`lp-status-pill ${pillMod}`}>
      <span className={`lp-status-dot ${dotMod}`} />
      {label}
    </span>
  );
}
