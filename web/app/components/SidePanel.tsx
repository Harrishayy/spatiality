"use client";

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
      <section className="lp-side-section">
        <PipelineProgress manifest={manifest} />
      </section>

      <section className="lp-side-section">
        <div className="lp-side-section-head">
          <span className="lp-side-section-title">
            <span className="lp-eyebrow">Objects</span>
            <span className="lp-side-section-accent">scene</span>
          </span>
          <span className="lp-side-section-id">{annotations.length}</span>
        </div>
        <ObjectsList annotations={annotations} segStatus={segStatus} />
      </section>

      {selected && (
        <section className="lp-side-section">
          <AnnotationEvidencePanel
            sceneId={manifest.scene_id}
            annotation={selected}
          />
        </section>
      )}

      {isolatedIds.size > 0 && (
        <button
          onClick={clearIsolated}
          className="lp-btn lp-btn-ghost lp-btn-sm self-start"
        >
          ↺ Clear isolation ({isolatedIds.size})
        </button>
      )}

      <section className="lp-side-section lp-side-section--grow">
        <div className="lp-side-section-head">
          <span className="lp-side-section-title">
            <span className="lp-eyebrow">Chat</span>
            <span className="lp-side-section-accent">ask</span>
          </span>
        </div>
        <ChatPanel
          sceneId={manifest.scene_id}
          messages={messages}
          onSend={onSend}
          disabled={loading}
        />
      </section>
    </aside>
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
