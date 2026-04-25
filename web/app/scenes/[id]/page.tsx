"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import dynamic from "next/dynamic";
import { Header } from "@/components/Header";
import { SidePanel } from "@/components/SidePanel";
import { WhereAmIButton } from "@/components/WhereAmIButton";
import { useChat } from "@/hooks/useChat";
import { useScene } from "@/hooks/useScene";
import { DEMO_SCENE_ID } from "@/lib/api";

const SplatViewer = dynamic(
  () => import("@/components/SplatViewer").then((m) => m.SplatViewer),
  { ssr: false },
);

export default function ScenePage() {
  const params = useParams<{ id: string }>();
  const sceneId = params?.id ?? DEMO_SCENE_ID;
  const { manifest, annotations, splatUrl, ready } = useScene(sceneId);
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
  const annos = annotations.data ?? [];
  const emptySplat = (m?.stats.splat_size_mb ?? 0) <= 0.001;

  return (
    <div className="flex h-screen w-screen flex-col bg-ink-950">
      <Header manifest={m} />

      <main className="relative flex min-h-0 flex-1">
        <section className="relative min-h-0 flex-1">
          {ready && splatUrl.data ? (
            <SplatViewer
              splatUrl={splatUrl.data}
              annotations={annos}
              emptySplat={emptySplat}
            />
          ) : (
            <LoadingScreen status={m?.status} />
          )}

          <div className="pointer-events-none absolute inset-x-0 bottom-3 flex items-center justify-center gap-2 px-3">
            {ready && (
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

          {emptySplat && ready && (
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
              loading={!ready}
            />
          )}
        </div>
      </main>
    </div>
  );
}

function LoadingScreen({ status }: { status?: string }) {
  return (
    <div className="flex h-full w-full items-center justify-center">
      <div className="flex flex-col items-center gap-3 text-ink-400">
        <div className="size-8 animate-[pulse_900ms_ease-in-out_infinite] rounded-full bg-accent-500" />
        <p className="font-mono text-xs uppercase tracking-wider">
          {status ?? "loading"}
        </p>
        <p className="max-w-xs text-center text-xs text-ink-500">
          Polling manifest.json. The splat will load as soon as the pipeline
          flips to ready.
        </p>
      </div>
    </div>
  );
}
