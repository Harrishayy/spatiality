"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { ModeToggle } from "@/components/ModeToggle";
import { SettingsPanel, DEFAULT_SETTINGS } from "@/components/SettingsPanel";
import { Uploader } from "@/components/Uploader";
import { useUpload } from "@/hooks/useUpload";
import { submitJob, DEMO_SCENE_ID } from "@/lib/api";
import { useUploadMode } from "@/lib/uploadMode";

const HAS_AGENT = !!process.env.NEXT_PUBLIC_AGENT_URL;

export default function Index() {
  const router = useRouter();
  const [mode] = useUploadMode();
  const { state, start, reset } = useUpload();
  const [settings, setSettings] = useState(DEFAULT_SETTINGS);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const canSubmit = state.status === "done" && !!state.result && !submitting;

  async function onStart() {
    if (!state.result) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      if (mode === "r2") {
        if (!state.result.r2Key) throw new Error("missing r2_key");
        await submitJob({
          mode: "r2",
          scene_id: state.result.sceneId,
          r2_key: state.result.r2Key,
          settings,
        });
      } else {
        if (!state.result.modalPath) throw new Error("missing modal_path");
        await submitJob({
          mode: "local",
          scene_id: state.result.sceneId,
          modal_path: state.result.modalPath,
          settings,
        });
      }
      router.push(`/scenes/${state.result.sceneId}`);
    } catch (err) {
      setSubmitError(String((err as Error).message ?? err));
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-5xl flex-col gap-6 px-4 py-6">
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="size-7 rounded-md bg-gradient-to-br from-accent-500 to-accent-300 pin-glow" />
          <div className="flex flex-col leading-tight">
            <span className="text-base font-semibold tracking-tight">Glasses → 3D Twin</span>
            <span className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
              upload a video, get a splat
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {HAS_AGENT ? (
            <ModeToggle />
          ) : (
            <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-3 py-1 font-mono text-[10px] uppercase tracking-wider text-amber-300">
              demo mode (no agent)
            </span>
          )}
          <a
            href={`/scenes/${DEMO_SCENE_ID}`}
            className="rounded-full border border-ink-700 bg-ink-900/60 px-3 py-1 font-mono text-[10px] uppercase tracking-wider text-ink-300 hover:border-ink-500 hover:text-ink-100"
          >
            view demo →
          </a>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <div className="flex flex-col gap-4">
          <Uploader
            state={state}
            onPick={(file) => start(file, mode)}
            onReset={reset}
          />
          {!HAS_AGENT && (
            <p className="rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 font-mono text-[11px] leading-relaxed text-amber-200/90">
              Set <code>NEXT_PUBLIC_AGENT_URL</code> to enable real uploads. Until then,
              this page is read-only and the demo scene above is what you can explore.
            </p>
          )}
        </div>

        <div className="flex flex-col gap-4">
          <SettingsPanel
            value={settings}
            onChange={setSettings}
            durationS={state.durationS}
          />
          <button
            type="button"
            onClick={onStart}
            disabled={!canSubmit || !HAS_AGENT}
            className={`rounded-xl px-4 py-3 text-sm font-semibold tracking-tight transition ${
              canSubmit && HAS_AGENT
                ? "bg-accent-500 text-ink-950 hover:bg-accent-400"
                : "cursor-not-allowed bg-ink-800 text-ink-500"
            }`}
          >
            {submitting
              ? "Queueing…"
              : state.status === "uploading"
                ? `Uploading ${(state.progress * 100).toFixed(0)}%`
                : state.status === "done"
                  ? `Start pipeline → ${mode === "local" ? "Modal Volume" : "R2"}`
                  : "Pick a video first"}
          </button>
          {submitError && (
            <span className="font-mono text-[11px] text-red-300">{submitError}</span>
          )}
        </div>
      </div>
    </main>
  );
}
