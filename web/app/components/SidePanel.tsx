"use client";

import type { ReactNode } from "react";

import type { Annotation, Manifest, StageStatus } from "@/lib/types";
import { useUI } from "@/store/ui";
import { AnnotationEvidencePanel } from "./AnnotationEvidencePanel";
import { ChatPanel } from "./ChatPanel";
import { PipelineProgress } from "./PipelineProgress";

interface Props {
  manifest: Manifest;
  annotations: Annotation[];
  messages: import("@/lib/types").ChatMessage[];
  onSend: (text: string) => void;
  loading: boolean;
  segStatus: StageStatus;
}

export function SidePanel({
  manifest,
  annotations,
  messages,
  onSend,
  loading,
  segStatus,
}: Props) {
  const isolatedIds = useUI((s) => s.isolatedIds);
  const clearIsolated = useUI((s) => s.clearIsolated);
  const selectedId = useUI((s) => s.selectedId);
  const selected =
    selectedId == null ? null : annotations.find((a) => a.id === selectedId) ?? null;

  return (
    <aside className="lp-side md:max-w-sm">
      <CollapseSection
        name="Pipeline"
        accent="live"
        meta={<span className="lp-collapse-count">{manifest.scene_id}</span>}
        defaultOpen
      >
        <PipelineProgress manifest={manifest} />
      </CollapseSection>

      <CollapseSection
        name="Objects"
        accent="scene"
        meta={
          <span className="lp-collapse-count">{annotations.length}</span>
        }
        defaultOpen
      >
        <ObjectsList annotations={annotations} segStatus={segStatus} />
        {isolatedIds.size > 0 && (
          <button
            onClick={clearIsolated}
            className="lp-btn lp-btn-ghost lp-btn-sm self-start"
          >
            ↺ Clear isolation ({isolatedIds.size})
          </button>
        )}
      </CollapseSection>

      {selected && (
        <CollapseSection
          name="Evidence"
          accent={selected.label}
          defaultOpen
          flush
        >
          <AnnotationEvidencePanel
            sceneId={manifest.scene_id}
            annotation={selected}
          />
        </CollapseSection>
      )}

      <CollapseSection
        name="Chat"
        accent="ask"
        defaultOpen
        grow
        flush
      >
        <ChatPanel
          sceneId={manifest.scene_id}
          messages={messages}
          onSend={onSend}
          disabled={loading}
        />
      </CollapseSection>
    </aside>
  );
}

interface SectionProps {
  name: string;
  accent?: string;
  meta?: ReactNode;
  defaultOpen?: boolean;
  grow?: boolean;
  flush?: boolean;
  children: ReactNode;
}

function CollapseSection({
  name,
  accent,
  meta,
  defaultOpen,
  grow,
  flush,
  children,
}: SectionProps) {
  return (
    <details
      open={defaultOpen}
      className={[
        "lp-collapse",
        grow ? "lp-collapse--grow" : "",
        flush ? "lp-collapse--flush" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <summary className="lp-collapse-head">
        <span className="lp-collapse-title">
          <span className="lp-collapse-title-name">{name}</span>
          {accent && (
            <span className="lp-collapse-title-accent">{accent}</span>
          )}
        </span>
        <span className="lp-collapse-meta">
          {meta}
          <span className="lp-collapse-chevron" aria-hidden>
            ▾
          </span>
        </span>
      </summary>
      <div className="lp-collapse-body">{children}</div>
    </details>
  );
}

function ObjectsList({
  annotations,
  segStatus,
}: {
  annotations: Annotation[];
  segStatus: StageStatus;
}) {
  const selectedId = useUI((s) => s.selectedId);
  const setSelected = useUI((s) => s.setSelected);
  const isolatedIds = useUI((s) => s.isolatedIds);
  const toggleIsolated = useUI((s) => s.toggleIsolated);

  if (annotations.length === 0) {
    let label: string;
    if (segStatus === "running") label = "Segmenting…";
    else if (segStatus === "pending") label = "Segmentation pending.";
    else if (segStatus === "failed") label = "Segmentation failed.";
    else label = "No objects found.";
    return (
      <div className="lp-objects-empty">
        {segStatus === "running" && (
          <span className="lp-status-dot lp-status-dot--warn" />
        )}
        <span>{label}</span>
      </div>
    );
  }
  return (
    <div className="lp-objects-list">
      {annotations.map((a) => {
        const selected = selectedId === a.id;
        const isolated = isolatedIds.has(a.id);
        return (
          <div
            key={a.id}
            className={[
              "lp-objects-row",
              selected ? "lp-objects-row--selected" : "",
              isolated ? "lp-objects-row--isolated" : "",
            ].join(" ")}
            onClick={() => setSelected(selected ? null : a.id)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                setSelected(selected ? null : a.id);
              }
            }}
          >
            <span
              className="lp-objects-dot"
              style={{ backgroundColor: a.color }}
            />
            <span className="lp-objects-label">{a.label}</span>
            <span className="lp-objects-conf">
              {(a.confidence * 100).toFixed(0)}%
            </span>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                toggleIsolated(a.id);
              }}
              title={isolated ? "Show all" : "Isolate"}
              className={[
                "lp-objects-iso",
                isolated ? "lp-objects-iso--on" : "",
              ].join(" ")}
              aria-label={isolated ? "Show all" : "Isolate"}
            >
              ◉
            </button>
          </div>
        );
      })}
    </div>
  );
}
