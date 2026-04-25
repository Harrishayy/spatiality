"use client";

import type { Manifest, Stage, StageStatus } from "@/lib/types";

const STAGE_ORDER: (keyof Manifest["stages"])[] = [
  "capture",
  "poses",
  "splat",
  "segmentation",
];

const LABEL: Record<keyof Manifest["stages"], string> = {
  capture: "Capture",
  poses: "Poses (VGGT)",
  splat: "Splat (3DGRUT)",
  segmentation: "Segmentation",
};

export function PipelineProgress({ manifest }: { manifest: Manifest }) {
  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <h3 className="text-xs uppercase tracking-wider text-ink-400">
          Pipeline
        </h3>
        <span className="font-mono text-[11px] text-ink-400">
          {manifest.scene_id}
        </span>
      </div>
      <ol className="overflow-hidden rounded-lg border border-ink-800 bg-ink-900/40">
        {STAGE_ORDER.map((key, i) => (
          <li
            key={key}
            className={[
              "flex items-center justify-between gap-3 px-3 py-2",
              i > 0 ? "border-t border-ink-800" : "",
            ].join(" ")}
          >
            <div className="flex items-center gap-3">
              <StatusDot status={manifest.stages[key].status} />
              <span className="text-sm text-ink-200">{LABEL[key]}</span>
            </div>
            <DurationOrExtra stage={manifest.stages[key]} />
          </li>
        ))}
      </ol>
      <Stats manifest={manifest} />
    </div>
  );
}

function StatusDot({ status }: { status: StageStatus }) {
  if (status === "complete")
    return <span className="size-2 rounded-full bg-emerald-400" />;
  if (status === "running")
    return (
      <span className="size-2 animate-[pulse_900ms_ease-in-out_infinite] rounded-full bg-accent-400" />
    );
  if (status === "failed")
    return <span className="size-2 rounded-full bg-red-400" />;
  return <span className="size-2 rounded-full bg-ink-600" />;
}

function DurationOrExtra({ stage }: { stage: Stage }) {
  const parts: string[] = [];
  if (typeof stage.duration_s === "number") {
    parts.push(`${stage.duration_s.toFixed(1)}s`);
  }
  if (typeof stage["iterations"] === "number") {
    parts.push(`${stage["iterations"]} iter`);
  }
  if (typeof stage["object_count"] === "number") {
    parts.push(`${stage["object_count"]} obj`);
  }
  return (
    <span className="font-mono text-xs tabular-nums text-ink-400">
      {parts.join(" · ") || "—"}
    </span>
  );
}

function Stats({ manifest }: { manifest: Manifest }) {
  return (
    <div className="grid grid-cols-3 overflow-hidden rounded-lg border border-ink-800 bg-ink-900/40 text-center">
      <Cell label="frames" value={manifest.stats.frame_count} />
      <Cell label="objects" value={manifest.stats.object_count} divider />
      <Cell
        label="splat"
        value={`${manifest.stats.splat_size_mb.toFixed(0)} MB`}
        divider
      />
    </div>
  );
}

function Cell({
  label,
  value,
  divider = false,
}: {
  label: string;
  value: number | string;
  divider?: boolean;
}) {
  return (
    <div className={`px-3 py-2 ${divider ? "border-l border-ink-800" : ""}`}>
      <div className="font-mono text-base tabular-nums">{value}</div>
      <div className="text-[10px] uppercase tracking-wider text-ink-500">
        {label}
      </div>
    </div>
  );
}