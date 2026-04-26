"use client";

import { useCallback, useEffect, useState } from "react";

import type { UploadMode } from "./types";

export type { UploadMode };

const STORAGE_KEY = "spatiality:upload-mode";

function defaultMode(): UploadMode {
  return process.env.NEXT_PUBLIC_DEFAULT_MODE === "local" ? "local" : "r2";
}

export function useUploadMode(): [UploadMode, (mode: UploadMode) => void] {
  const [mode, setModeState] = useState<UploadMode>(defaultMode);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "r2" || stored === "local") setModeState(stored);
  }, []);

  const setMode = useCallback((next: UploadMode) => {
    setModeState(next);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, next);
    }
  }, []);

  return [mode, setMode];
}
