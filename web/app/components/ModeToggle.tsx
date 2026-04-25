"use client";

import { useUploadMode } from "@/lib/uploadMode";

export function ModeToggle() {
  const [mode, setMode] = useUploadMode();
  const isLocal = mode === "local";
  return (
    <button
      type="button"
      onClick={() => setMode(isLocal ? "r2" : "local")}
      className="flex items-center gap-2 rounded-full border border-ink-700 bg-ink-900/60 px-3 py-1 font-mono text-[10px] uppercase tracking-wider text-ink-300 transition hover:border-accent-400/60 hover:text-ink-100"
      title={
        isLocal
          ? "Uploads bypass R2 — multipart to agent → Modal Volume"
          : "Uploads stream to Cloudflare R2 (production path)"
      }
    >
      <span
        className={`inline-block size-2 rounded-full ${
          isLocal ? "bg-amber-400" : "bg-emerald-400"
        }`}
      />
      mode: {isLocal ? "local" : "r2"}
    </button>
  );
}
