"use client";

import { useState } from "react";
import { postLocate } from "@/lib/api";
import { nearbyAnnotations } from "@/lib/cameraMath";
import type { Annotation } from "@/lib/types";
import { useUI } from "@/store/ui";

interface Props {
  sceneId: string;
  annotations: Annotation[];
  onAnswer: (text: string) => void;
}

export function WhereAmIButton({ sceneId, annotations, onAnswer }: Props) {
  const camera = useUI((s) => s.camera);
  const [busy, setBusy] = useState(false);

  const onClick = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const nearby = nearbyAnnotations(annotations, camera.position, camera.direction);
      const resp = await postLocate({
        scene_id: sceneId,
        camera_pos: camera.position,
        camera_dir: camera.direction,
        nearby: nearby.map((a) => ({
          id: a.id,
          label: a.label,
          centroid: a.centroid,
        })),
      });
      onAnswer(resp.text);
    } finally {
      setBusy(false);
    }
  };

  return (
    <button
      onClick={onClick}
      disabled={busy}
      className={[
        "group flex items-center gap-2 rounded-full px-4 py-2",
        "bg-accent-500 text-white font-medium",
        "shadow-[0_0_24px_rgba(124,92,255,0.45)]",
        "transition active:scale-95 hover:bg-accent-400",
        "disabled:opacity-60",
      ].join(" ")}
      aria-label="Where am I?"
    >
      <span
        className={[
          "block size-2 rounded-full bg-white",
          busy ? "animate-[pulse_900ms_ease-in-out_infinite]" : "",
        ].join(" ")}
      />
      <span className="text-sm">{busy ? "Looking…" : "Where am I?"}</span>
    </button>
  );
}