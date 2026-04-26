"use client";

import type { Manifest, Stage, StageStatus } from "@/lib/types";
import { useUI, type DrillStage } from "@/store/ui";

// Visible stages in the panel. The internal "splat" stage (voxel-downsample
// of VGGT surfels into the small splat.ply that segmentation clusters over)
// is hidden — the viewer doesn't render that output and it's confusing to
// surface to a user. Pipeline manifest still tracks it; we just don't show it.
const STAGE_ORDER: DrillStage[] = ["capture", "poses", "segmentation"];

const LABEL: Record<keyof Manifest["stages"], string> = {
  capture: "Capture",
  poses: "Reconstruction (VGGT)",
  splat: "Splat (cluster)",
  segmentation: "Segmentation",
};

function formatPointCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)} M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)} K`;
  return n.toLocaleString();
}

export function PipelineProgress({ manifest }: { manifest: Manifest }) {
  const cloudStats = useUI((s) => s.cloudStats);
  const setOpenStage = useUI((s) => s.setOpenStage);
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
            className={i > 0 ? "border-t border-ink-800" : ""}
          >
            <button
              type="button"
              onClick={() => setOpenStage(key)}
              className="group flex w-full items-center justify-between gap-3 px-3 py-2 text-left transition hover:bg-ink-800/40"
              title="View live trace for this stage"
            >
              <div className="flex items-center gap-3">
                <StatusDot status={manifest.stages[key].status} />
                <span className="text-sm text-ink-200">{LABEL[key]}</span>
                <span className="font-mono text-[10px] text-ink-700 opacity-0 transition group-hover:opacity-100">
                  view trace ↗
                </span>
              </div>
              <DurationOrExtra stage={manifest.stages[key]} />
            </button>
          </li>
        ))}
      </ol>
      <Stats manifest={manifest} cloudStats={cloudStats} />
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
  // The `gaussian_count` field is the count of cluster-source primitives in
  // splat.ply (input to segmentation), NOT the count rendered in the viewer.
  // Rendered points come from points.ply and live in the cloudStats store.
  if (typeof stage["gaussian_count"] === "number") {
    parts.push(`${formatPointCount(stage["gaussian_count"] as number)} clusters`);
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

function Stats({
  manifest,
  cloudStats,
}: {
  manifest: Manifest;
  cloudStats: { count: number; sizeMb: number } | null;
}) {
  // Frame cell: VGGT consumes a frame-budgeted subset of what capture extracts.
  // Show "used / captured" once VGGT has stamped its consumed count on the
  // poses stage; before that, fall back to the on-disk capture count.
  const captured = manifest.stats.frame_count;
  const usedRaw = manifest.stages.poses["frame_count"];
  const used = typeof usedRaw === "number" ? usedRaw : null;
  const frameValue =
    used !== null && used !== captured
      ? `${used} / ${captured}`
      : `${captured}`;

  // Splat cell: prefer the viewer's live cloud count; fall back to the splat
  // stage's gaussian_count (set as soon as splat completes); only fall back
  // to size-on-disk when neither is available yet.
  const splatGaussiansRaw = manifest.stages.splat["gaussian_count"];
  const splatGaussians =
    typeof splatGaussiansRaw === "number" ? splatGaussiansRaw : null;
  let cloudLabel: string;
  let cloudValue: string;
  if (cloudStats) {
    cloudLabel = "points";
    cloudValue = `${formatPointCount(cloudStats.count)}`;
  } else if (splatGaussians !== null) {
    cloudLabel = "points";
    cloudValue = `${formatPointCount(splatGaussians)}`;
  } else {
    cloudLabel = "splat";
    cloudValue = `${manifest.stats.splat_size_mb.toFixed(0)} MB`;
  }

  return (
    <div className="grid grid-cols-3 overflow-hidden rounded-lg border border-ink-800 bg-ink-900/40 text-center">
      <Cell label="frames" value={frameValue} />
      <Cell label="objects" value={manifest.stats.object_count} divider />
      <Cell label={cloudLabel} value={cloudValue} divider />
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