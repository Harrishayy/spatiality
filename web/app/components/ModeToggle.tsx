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
          ? "Direct upload — multipart to agent → Modal Volume"
          : "Streamed upload (production path)"
      }
    >
      <span
        className="inline-block size-1.5 rounded-full"
        style={{ background: isLocal ? "var(--hue-amber)" : "var(--emerald)" }}
      />
      Mode · {isLocal ? "Local" : "Cloud"}
    </button>
  );
}
