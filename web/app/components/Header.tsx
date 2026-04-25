"use client";

import type { Manifest } from "@/lib/types";

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
      <StatusBadge status={status} />
    </header>
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