import { create } from "zustand";
import type { Vec3 } from "@/lib/types";

interface CameraState {
  position: Vec3;
  direction: Vec3;
}

interface UIState {
  selectedId: string | null;
  isolatedIds: Set<string>;
  camera: CameraState;
  setSelected: (id: string | null) => void;
  toggleIsolated: (id: string) => void;
  clearIsolated: () => void;
  setCamera: (pos: Vec3, dir: Vec3) => void;
}

export const useUI = create<UIState>((set) => ({
  selectedId: null,
  isolatedIds: new Set<string>(),
  camera: { position: [0, 0, 0], direction: [0, 0, -1] },
  setSelected: (id) => set({ selectedId: id }),
  toggleIsolated: (id) =>
    set((s) => {
      const next = new Set(s.isolatedIds);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return { isolatedIds: next };
    }),
  clearIsolated: () => set({ isolatedIds: new Set() }),
  setCamera: (position, direction) =>
    set(() => ({ camera: { position, direction } })),
}));
