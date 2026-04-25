"use client";

import { useCallback, useRef, useState } from "react";

import type { UploadState } from "@/hooks/useUpload";

interface Props {
  state: UploadState;
  onPick: (file: File) => void;
  onReset: () => void;
}

export function Uploader({ state, onPick, onReset }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  const handleFiles = useCallback(
    (files: FileList | null) => {
      if (!files || files.length === 0) return;
      const f = files[0];
      if (!f.type.startsWith("video/")) return;
      onPick(f);
    },
    [onPick],
  );

  if (state.status !== "idle") {
    return <ActiveUpload state={state} onReset={onReset} />;
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        handleFiles(e.dataTransfer.files);
      }}
      onClick={() => inputRef.current?.click()}
      className={`flex min-h-[260px] cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed p-6 text-center transition ${
        dragOver
          ? "border-accent-400 bg-accent-500/10"
          : "border-ink-700 bg-ink-900/40 hover:border-ink-500 hover:bg-ink-900/70"
      }`}
    >
      <div className="size-12 rounded-full bg-gradient-to-br from-accent-500 to-accent-300 pin-glow" />
      <div className="flex flex-col gap-1">
        <span className="text-sm font-semibold">Drop a video to start</span>
        <span className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
          mp4 / mov / webm · up to 2 GB
        </span>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="video/*"
        className="hidden"
        onChange={(e) => handleFiles(e.target.files)}
      />
    </div>
  );
}

function ActiveUpload({
  state,
  onReset,
}: {
  state: UploadState;
  onReset: () => void;
}) {
  const { file, progress, status, error, durationS } = state;
  const pct = Math.round(progress * 100);
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-ink-800 bg-ink-900/60 p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 flex-col">
          <span className="truncate text-sm font-semibold">{file?.name ?? "—"}</span>
          <span className="font-mono text-[10px] uppercase tracking-wider text-ink-500">
            {file ? `${(file.size / 1_000_000).toFixed(1)} MB` : ""}
            {durationS ? ` · ${durationS.toFixed(1)}s` : ""}
            {status === "uploading" ? ` · ${pct}%` : ""}
            {status === "done" ? " · uploaded" : ""}
            {status === "error" ? " · failed" : ""}
          </span>
        </div>
        <button
          type="button"
          onClick={onReset}
          className="rounded-md border border-ink-700 px-2 py-1 font-mono text-[10px] uppercase tracking-wider text-ink-400 hover:text-ink-100"
        >
          {status === "uploading" ? "cancel" : "remove"}
        </button>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-ink-800">
        <div
          className={`h-full transition-all ${
            status === "error" ? "bg-red-500" : status === "done" ? "bg-emerald-400" : "bg-accent-400"
          }`}
          style={{ width: `${Math.max(pct, status === "uploading" ? 4 : 0)}%` }}
        />
      </div>
      {error && (
        <span className="font-mono text-[11px] text-red-300">{error}</span>
      )}
    </div>
  );
}
