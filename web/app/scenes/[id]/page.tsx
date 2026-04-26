"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import dynamic from "next/dynamic";
import { Header } from "@/components/Header";
import { PipelineProgress } from "@/components/PipelineProgress";
import { SidePanel } from "@/components/SidePanel";
import { StageDrawer } from "@/components/StageDrawer";
import { WhereAmIButton } from "@/components/WhereAmIButton";
import { useChat } from "@/hooks/useChat";
import { useScene } from "@/hooks/useScene";
import { DEMO_SCENE_ID } from "@/lib/api";
import type { Manifest, StageStatus } from "@/lib/types";

const SplatViewer = dynamic(
  () => import("@/components/SplatViewer").then((m) => m.SplatViewer),
  { ssr: false },
);

export default function ScenePage() {
  const params = useParams<{ id: string }>();
  const sceneId = params?.id ?? DEMO_SCENE_ID;
  const { manifest, annotations, splatUrl, splatReady, segReady } = useScene(sceneId);
  const { messages, send, append } = useChat(sceneId);
  const [showSide, setShowSide] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(min-width: 768px)");
    setShowSide(mq.matches);
    const onChange = (e: MediaQueryListEvent) => setShowSide(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const m = manifest.data;
  // Stable reference: react-query gives us the same array across renders when
  // data is unchanged; the ?? [] fallback used to mint a fresh array each
  // render, which would tear down the SplatViewer on every poll.
  const annos = useMemo(() => annotations.data ?? [], [annotations.data]);
  const emptySplat = (m?.stats.splat_size_mb ?? 0) <= 0.001;
  const segStatus: StageStatus = m?.stages.segmentation.status ?? "pending";
  const failed = m?.status === "failed";

  return (
    <div className="flex h-screen w-screen flex-col bg-ink-950">
      <Header manifest={m} />

      <main className="relative flex min-h-0 flex-1">
        <section className="relative min-h-0 flex-1">
          {splatReady && splatUrl.data ? (
            <SplatViewer
              splatUrl={splatUrl.data}
              annotations={annos}
              emptySplat={emptySplat}
            />
          ) : (
            <PipelinePending manifest={m} failed={failed} />
          )}

          <div className="pointer-events-none absolute inset-x-0 bottom-3 flex items-center justify-center gap-2 px-3">
            {splatReady && (
              <div className="pointer-events-auto">
                <WhereAmIButton
                  sceneId={sceneId}
                  annotations={annos}
                  onAnswer={(text) =>
                    append({ role: "agent", text: `📍 ${text}` })
                  }
                />
              </div>
            )}
            <button
              onClick={() => setShowSide((s) => !s)}
              className="pointer-events-auto rounded-full border border-ink-700 bg-ink-900/80 px-3 py-2 text-xs text-ink-200 backdrop-blur md:hidden"
            >
              {showSide ? "Hide ▸" : "Chat ◂"}
            </button>
          </div>

          {splatReady && !segReady && segStatus !== "failed" && (
            <SegmentingBanner status={segStatus} />
          )}

          {splatReady && segStatus === "failed" && (
            <FailedBanner
              title="Segmentation failed"
              detail={m?.errors?.[m.errors.length - 1]}
            />
          )}

          {emptySplat && splatReady && (
            <div className="pointer-events-none absolute left-3 top-3 max-w-xs rounded-md border border-ink-700/60 bg-ink-900/70 px-3 py-2 text-xs text-ink-300 backdrop-blur">
              <p>
                <strong className="text-ink-100">Demo placeholder:</strong>{" "}
                splat.ply is empty (stub scene). Annotation bboxes are rendered
                as wireframes so you can see the spatial layout. Drop a real
                splat at <code>/artifacts/scenes/{sceneId}/splat.ply</code> to
                see it for real.
              </p>
            </div>
          )}
        </section>

        <div
          className={[
            "absolute inset-y-0 right-0 z-10 w-full bg-ink-950/95 backdrop-blur md:relative md:bg-transparent md:backdrop-blur-none",
            "transition-transform md:max-w-sm",
            showSide ? "translate-x-0" : "translate-x-full md:translate-x-0",
          ].join(" ")}
        >
          {m && (
            <SidePanel
              manifest={m}
              annotations={annos}
              messages={messages}
              onSend={send}
              loading={!splatReady}
              segStatus={segStatus}
            />
          )}
        </div>
      </main>

      {/* Drill-down drawer — opens when a Pipeline row is clicked. Lives at
          page level so the backdrop covers the splat viewer too. */}
      <StageDrawer sceneId={sceneId} manifestStatus={m?.status ?? null} />
    </div>
  );
}

function PipelinePending({
  manifest,
  failed,
}: {
  manifest?: Manifest;
  failed: boolean;
}) {
  return (
    <div className="flex h-full w-full items-center justify-center p-6">
      <div className="flex w-full max-w-md flex-col items-stretch gap-4">
        <div className="flex items-center gap-3 text-ink-400">
          <div
            className={[
              "size-3 rounded-full",
              failed
                ? "bg-red-400"
                : "animate-[pulse_900ms_ease-in-out_infinite] bg-accent-500",
            ].join(" ")}
          />
          <p className="font-mono text-xs uppercase tracking-wider">
            {failed ? "pipeline failed" : "running pipeline"}
          </p>
        </div>
        {manifest && <PipelineProgress manifest={manifest} />}
        {failed && manifest?.errors?.length ? (
          <pre className="max-h-32 overflow-auto rounded-md border border-red-500/40 bg-red-500/10 p-3 text-[11px] text-red-200">
            {manifest.errors[manifest.errors.length - 1]}
          </pre>
        ) : (
          <p className="text-center text-xs text-ink-500">
            The splat will appear as soon as the splat stage completes —
            segmentation continues in the background.
          </p>
        )}
      </div>
    </div>
  );
}

function SegmentingBanner({ status }: { status: StageStatus }) {
  const label =
    status === "running"
      ? "Segmentation in progress — annotations will appear shortly."
      : "Annotations not yet generated. Segmentation pending.";
  return (
    <div className="pointer-events-none absolute right-3 top-3 max-w-xs rounded-md border border-accent-500/40 bg-ink-900/80 px-3 py-2 text-xs text-ink-200 backdrop-blur">
      <div className="flex items-center gap-2">
        <span className="size-2 animate-[pulse_900ms_ease-in-out_infinite] rounded-full bg-accent-400" />
        <span>{label}</span>
      </div>
    </div>
  );
}

function FailedBanner({
  title,
  detail,
}: {
  title: string;
  detail?: string;
}) {
  return (
    <div className="pointer-events-none absolute right-3 top-3 max-w-xs rounded-md border border-red-500/50 bg-red-500/10 px-3 py-2 text-xs text-red-200 backdrop-blur">
      <p className="font-medium">{title}</p>
      {detail && <p className="mt-1 truncate text-[11px] opacity-80">{detail}</p>}
    </div>
  );
}
