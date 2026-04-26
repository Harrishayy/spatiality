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
      className="lp-where-btn"
      aria-label="Where am I?"
    >
      <span className="lp-where">
        <span className="lp-where-pulse" />
      </span>
      <span>{busy ? "Looking…" : "Where am I?"}</span>
    </button>
  );
}
