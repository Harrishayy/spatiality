"use client";

import { useUploadMode } from "@/lib/uploadMode";

export function ModeToggle() {
  const [mode, setMode] = useUploadMode();
  const isLocal = mode === "local";
  return (
    <button
      type="button"
      onClick={() => setMode(isLocal ? "r2" : "local")}
      className={`lp-mode-chip ${isLocal ? "" : "lp-mode-chip--on"} inline-flex items-center gap-2`}
      title={
        isLocal
          ? "Uploads bypass R2 — multipart to agent → Modal Volume"
          : "Uploads stream to Cloudflare R2 (production path)"
      }
    >
      <span
        className="inline-block size-1.5 rounded-full"
        style={{
          background: isLocal ? "var(--hue-amber)" : "var(--emerald)",
          boxShadow: isLocal
            ? "0 0 6px rgba(255,179,71,0.6)"
            : "0 0 6px rgba(78,201,176,0.6)",
        }}
      />
      mode: {isLocal ? "local" : "r2"}
    </button>
  );
}
