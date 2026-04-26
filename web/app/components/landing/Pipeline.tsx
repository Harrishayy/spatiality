"use client";

import { useEffect, useRef, useState } from "react";
import { SectionHeader } from "./SectionHeader";

type Stage = {
  key: string;
  label: string;
  sub: string;
  duration: string;
  extra: string;
  hidden?: boolean;
};

const STAGES: Stage[] = [
  {
    key: "capture",
    label: "Capture",
    sub: "wearable video → keyframes",
    duration: "4.1s",
    extra: "120 frames",
  },
  {
    key: "poses",
    label: "Reconstruction",
    sub: "metric geometry + camera poses",
    duration: "38.7s",
    extra: "2.41M points",
  },
  {
    key: "splat",
    label: "Compaction",
    sub: "GPU-streamable mesh + splats",
    duration: "6.3s",
    extra: "48 MB",
    hidden: true,
  },
  {
    key: "segmentation",
    label: "Understanding",
    sub: "instance masks + semantic labels",
    duration: "11.2s",
    extra: "27 objects",
  },
];

type LogLevel = "info" | "ok" | "warn" | "err";
type SpanRow = readonly [string, LogLevel, string, string];

const SPAN_LOG: SpanRow[] = [
  ["00.00", "info", "agent.boot", "scene_id=living_room_03"],
  ["00.02", "info", "capture.start", "src=ray-ban-gen2.mp4 size=84.2MB"],
  ["00.18", "info", "capture.frames", "extracted=240 fps=30"],
  ["04.10", "ok", "capture.done", "duration=4.1s"],
  ["04.11", "info", "infer.poses.start", "model=vggt-1b dtype=fp16"],
  ["12.40", "info", "infer.poses.progress", "frames=80/120 conf=0.91"],
  ["28.30", "info", "infer.poses.progress", "frames=120/120 conf=0.94"],
  ["42.80", "ok", "infer.poses.done", "surfels=2.41M dur=38.7s"],
  ["42.82", "info", "splat.cluster.start", "voxel=0.025"],
  ["49.10", "ok", "splat.cluster.done", "clusters=412173 dur=6.3s"],
  ["49.11", "info", "segment.sam31.start", "device=A100 batch=8"],
  ["54.40", "info", "segment.sam31.masks", "kept=89 / 412 (>0.6 iou)"],
  ["58.20", "info", "agent.gateway.label", "via=pydantic-ai/anthropic"],
  ["60.30", "ok", "segment.label.done", "objects=27 dur=11.2s"],
  ["60.31", "ok", "manifest.write", "status=ready"],
  ["60.32", "ok", "agent.ready", "where_am_i ≤3s"],
];

export function LandingPipeline() {
  return (
    <section id="pipeline" className="lp-section lp-pipeline">
      <SectionHeader
        title={
          <>
            From wearable capture to a <em>navigable 3D twin</em> in <em>under 90 seconds</em>.
          </>
        }
        sub="A production pipeline you can deploy on your own infrastructure. Every stage emits structured traces, so latency, cost, and quality are observable end-to-end."
      />

      <div className="lp-pipeline-grid">
        <StagePanel />
        <LogPanel />
      </div>

      <StatsRow />
    </section>
  );
}

function StagePanel() {
  return (
    <div className="lp-card lp-stage-panel">
      <div className="lp-card-head">
        <div className="lp-card-head-l">
          <h3 className="lp-card-title">Inference run</h3>
          <span className="lp-mono lp-muted">representative scene</span>
        </div>
        <span className="lp-status-pill lp-status-pill--ok">
          <span className="lp-status-dot lp-status-dot--ok" />
          ready · 60.3s
        </span>
      </div>

      <ol className="lp-stage-list">
        {STAGES.filter((s) => !s.hidden).map((s) => (
          <li key={s.key} className="lp-stage-row">
            <span className="lp-stage-dot lp-stage-dot--complete" />
            <div className="lp-stage-meta">
              <div className="lp-stage-label">{s.label}</div>
              <div className="lp-stage-sub lp-mono">{s.sub}</div>
            </div>
            <div className="lp-stage-numbers">
              <span className="lp-mono lp-muted">{s.extra}</span>
              <span className="lp-mono lp-stage-dur">{s.duration}</span>
            </div>
          </li>
        ))}
      </ol>

      <div className="lp-stage-foot">
        <span className="lp-mono lp-muted">deliverables</span>
        <div className="lp-stage-foot-files">
          <FileChip name="metric mesh" />
          <FileChip name="point cloud" />
          <FileChip name="instance masks" />
          <FileChip name="semantic graph" />
        </div>
      </div>
    </div>
  );
}

function FileChip({ name }: { name: string }) {
  return (
    <span className="lp-file-chip">
      <span className="lp-file-chip-icon">▤</span>
      <span className="lp-mono">{name}</span>
    </span>
  );
}

function LogPanel() {
  const [count, setCount] = useState(0);
  const tailRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let i = 0;
    setCount(0);
    const id = setInterval(() => {
      i += 1;
      if (i > SPAN_LOG.length) {
        i = 0;
        setCount(0);
        return;
      }
      setCount(i);
    }, 380);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (tailRef.current) tailRef.current.scrollTop = 1e6;
  }, [count]);

  const visible = SPAN_LOG.slice(0, count);

  return (
    <div className="lp-card lp-log-panel">
      <div className="lp-log-head">
        <div className="lp-log-traffic">
          <span />
          <span />
          <span />
        </div>
        <span className="lp-mono lp-muted">
          logfire · agent + pipeline · tail -f
        </span>
        <span className="lp-mono lp-muted">{visible.length} spans</span>
      </div>
      <div className="lp-log-body" ref={tailRef}>
        {visible.map((row, idx) => (
          <div key={idx} className="lp-log-row">
            <span className="lp-mono lp-log-time">{row[0]}</span>
            <span
              className={"lp-log-level lp-mono lp-log-level--" + row[1]}
            >
              {row[1]}
            </span>
            <span className="lp-mono lp-log-name">{row[2]}</span>
            <span className="lp-mono lp-log-meta">{row[3]}</span>
          </div>
        ))}
        <div className="lp-log-cursor lp-mono">
          <span className="lp-log-prompt">›</span>
          <span className="lp-log-blink">_</span>
        </div>
      </div>
    </div>
  );
}

function StatsRow() {
  return (
    <div className="lp-stats-row">
      <Cell label="frames" value="120 / 240" />
      <Cell label="objects" value="27" />
      <Cell label="points" value="2.41 M" />
      <Cell label="splat" value="48 MB" />
    </div>
  );
}

function Cell({ label, value }: { label: string; value: string }) {
  return (
    <div className="lp-stats-cell">
      <div className="lp-stats-value lp-mono">{value}</div>
      <div className="lp-stats-label lp-mono">{label}</div>
    </div>
  );
}
