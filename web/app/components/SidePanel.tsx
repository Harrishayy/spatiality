"use client";

import type { Annotation, Manifest } from "@/lib/types";
import { useUI } from "@/store/ui";
import { ChatPanel } from "./ChatPanel";
import { PipelineProgress } from "./PipelineProgress";

interface Props {
  manifest: Manifest;
  annotations: Annotation[];
  messages: import("@/lib/types").ChatMessage[];
  onSend: (text: string) => void;
  loading: boolean;
}

export function SidePanel({
  manifest,
  annotations,
  messages,
  onSend,
  loading,
}: Props) {
  const isolatedIds = useUI((s) => s.isolatedIds);
  const clearIsolated = useUI((s) => s.clearIsolated);

  return (
    <aside
      className={[
        "flex h-full min-h-0 w-full flex-col gap-4 overflow-hidden",
        "border-l border-ink-800 bg-ink-900/60 p-4 backdrop-blur",
        "md:max-w-sm",
      ].join(" ")}
    >
      <PipelineProgress manifest={manifest} />

      <ObjectsList annotations={annotations} />

      {isolatedIds.size > 0 && (
        <button
          onClick={clearIsolated}
          className="rounded-md border border-ink-700 bg-ink-800 px-3 py-1 text-xs text-ink-300 hover:border-accent-400/60 hover:text-accent-300"
        >
          ↺ Clear isolation ({isolatedIds.size})
        </button>
      )}

      <div className="flex min-h-0 flex-1 flex-col">
        <h3 className="mb-2 text-xs uppercase tracking-wider text-ink-400">
          Chat
        </h3>
        <div className="flex min-h-0 flex-1 flex-col">
          <ChatPanel
            messages={messages}
            onSend={onSend}
            disabled={loading}
          />
        </div>
      </div>
    </aside>
  );
}

function ObjectsList({ annotations }: { annotations: Annotation[] }) {
  const selectedId = useUI((s) => s.selectedId);
  const setSelected = useUI((s) => s.setSelected);
  const isolatedIds = useUI((s) => s.isolatedIds);
  const toggleIsolated = useUI((s) => s.toggleIsolated);

  if (annotations.length === 0) {
    return (
      <div className="text-xs italic text-ink-500">No annotations yet.</div>
    );
  }
  return (
    <div className="space-y-1">
      <h3 className="text-xs uppercase tracking-wider text-ink-400">
        Objects ({annotations.length})
      </h3>
      <ul className="scroll-thin max-h-48 space-y-1 overflow-y-auto pr-1">
        {annotations.map((a) => {
          const selected = selectedId === a.id;
          const isolated = isolatedIds.has(a.id);
          return (
            <li
              key={a.id}
              className={[
                "group flex items-center gap-2 rounded-md border px-2 py-1.5",
                selected
                  ? "border-accent-400/80 bg-accent-500/10"
                  : "border-ink-800 bg-ink-900/40 hover:border-ink-700",
                isolated ? "ring-1 ring-accent-300/50" : "",
              ].join(" ")}
            >
              <button
                onClick={() => setSelected(selected ? null : a.id)}
                className="flex flex-1 items-center gap-2 text-left"
              >
                <span
                  className="block size-2.5 rounded-full"
                  style={{ backgroundColor: a.color }}
                />
                <span className="text-sm">{a.label}</span>
                <span className="ml-auto font-mono text-[10px] tabular-nums text-ink-500">
                  {(a.confidence * 100).toFixed(0)}%
                </span>
              </button>
              <button
                onClick={() => toggleIsolated(a.id)}
                title={isolated ? "Show all" : "Isolate"}
                className={[
                  "rounded px-1.5 py-0.5 text-[10px] transition",
                  isolated
                    ? "bg-accent-500/30 text-accent-200"
                    : "text-ink-500 opacity-0 group-hover:opacity-100 hover:text-accent-300",
                ].join(" ")}
              >
                ◉
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}