"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

import { ModeToggle } from "@/components/ModeToggle";
import { SettingsPanel, DEFAULT_SETTINGS } from "@/components/SettingsPanel";
import { Uploader } from "@/components/Uploader";
import { useUpload } from "@/hooks/useUpload";
import { submitJob, DEMO_SCENE_ID } from "@/lib/api";
import { useUploadMode } from "@/lib/uploadMode";

const HAS_AGENT = !!process.env.NEXT_PUBLIC_AGENT_URL;

export default function UploadPage() {
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
    <main className="mx-auto flex min-h-screen w-full max-w-6xl flex-col gap-12 px-6 py-10 md:px-10 md:py-14">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <Link href="/" className="flex items-center gap-3">
          <div
            className="size-7 rounded-lg"
            style={{
              background:
                "linear-gradient(135deg, var(--accent-500) 0%, var(--accent-300) 100%)",
            }}
          />
          <div className="flex flex-col leading-tight">
            <span className="text-[15.5px] font-semibold tracking-tight text-ink-100">
              Spatiality
            </span>
            <span className="text-[12.5px] text-ink-500">
              Fast inference for 3D meshes — any camera in, measurable scene out.
            </span>
          </div>
        </Link>
        <div className="flex items-center gap-2">
          {HAS_AGENT ? (
            <ModeToggle />
          ) : (
            <span className="rounded-full border border-[rgba(255,179,71,0.35)] bg-[rgba(255,179,71,0.08)] px-3 py-1 text-[12px] text-amber-300">
              Demo mode — no agent connected
            </span>
          )}
          <a href={`/scenes/${DEMO_SCENE_ID}`} className="lp-btn lp-btn-ghost lp-btn-sm">
            View demo
            <span className="lp-btn-arrow">→</span>
          </a>
        </div>
      </header>

      <section className="flex flex-col gap-3">
        <h1 className="text-[clamp(28px,3.4vw,40px)] font-light leading-[1.05] tracking-[-0.022em] text-ink-100">
          Drop a clip. Get a 3D twin you can measure and ask questions of.
        </h1>
        <p className="max-w-xl text-[15px] leading-relaxed text-ink-400">
          One short pass from any camera is enough. We&rsquo;ll reconstruct the
          mesh, label the objects, and hand you a viewer plus a chat agent.
        </p>
      </section>

      <div className="grid grid-cols-1 gap-8 md:grid-cols-[1.05fr_0.95fr]">
        <div className="flex flex-col gap-4">
          <Uploader
            state={state}
            onPick={(file) => start(file, mode)}
            onReset={reset}
          />
          {!HAS_AGENT && (
            <p className="rounded-xl border border-[rgba(255,179,71,0.25)] bg-[rgba(255,179,71,0.05)] px-4 py-3 text-[13px] leading-relaxed text-amber-200/90">
              Set <code className="font-mono text-[12.5px]">NEXT_PUBLIC_AGENT_URL</code> to
              enable real uploads. Until then, this page is read-only and the demo scene
              above is what you can explore.
            </p>
          )}
        </div>

        <div className="flex flex-col gap-5">
          <SettingsPanel
            value={settings}
            onChange={setSettings}
            durationS={state.durationS}
          />
          <button
            type="button"
            onClick={onStart}
            disabled={!canSubmit || !HAS_AGENT}
            className="lp-cta"
          >
            {submitting
              ? "Queueing…"
              : state.status === "uploading"
                ? `Uploading ${(state.progress * 100).toFixed(0)}%`
                : state.status === "done"
                  ? `Start pipeline · ${mode === "local" ? "Modal" : "R2"}`
                  : "Pick a video first"}
          </button>
          {submitError && (
            <span className="text-[12.5px] text-[#ffb6a3]">{submitError}</span>
          )}
        </div>
      </div>
    </main>
  );
}
