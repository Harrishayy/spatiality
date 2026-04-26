// Annotation + frame-image helpers used by the chat tool-use loop.
// Annotations come from artifacts/scenes/<id>/annotations.json (R2).
// Frames come from artifacts/scenes/<id>/frames/<name>.jpg (R2).

import { getArtifactBytes, getArtifactJson } from "./r2.js";

export interface AnnotationLite {
  id: string;
  label: string;
  centroid?: [number, number, number];
  bbox?: [[number, number, number], [number, number, number]];
  frame_ids?: string[];
}

export interface FrameImage {
  frame_id: string;
  media_type: "image/jpeg";
  data_b64: string;
}

interface AnnotationsFile {
  scene_id?: string;
  annotations?: AnnotationLite[];
}

export async function loadAnnotations(sceneId: string): Promise<AnnotationLite[]> {
  const file = await getArtifactJson<AnnotationsFile>(
    `scenes/${sceneId}/annotations.json`,
  );
  if (!file?.annotations) return [];
  return file.annotations.map((a) => ({
    id: a.id,
    label: a.label,
    centroid: a.centroid,
    bbox: a.bbox,
    frame_ids: a.frame_ids,
  }));
}

export function resolveAnnotation(
  annotations: AnnotationLite[],
  labelOrId: string,
): AnnotationLite | null {
  if (!labelOrId) return null;
  const needle = labelOrId.trim().toLowerCase();
  // Exact id match first.
  const byId = annotations.find((a) => a.id.toLowerCase() === needle);
  if (byId) return byId;
  // Exact label match.
  const byLabel = annotations.find((a) => a.label.toLowerCase() === needle);
  if (byLabel) return byLabel;
  // Substring fallback — both directions.
  const byPartial = annotations.find(
    (a) =>
      a.label.toLowerCase().includes(needle) ||
      needle.includes(a.label.toLowerCase()),
  );
  return byPartial ?? null;
}

export async function fetchFramesForAnnotation(
  sceneId: string,
  ann: AnnotationLite,
  maxFrames: number,
): Promise<FrameImage[]> {
  const ids = (ann.frame_ids ?? []).slice(0, Math.max(0, maxFrames));
  if (ids.length === 0) return [];
  const out: FrameImage[] = [];
  for (const frameId of ids) {
    const key = `scenes/${sceneId}/frames/${frameId}`;
    const bytes = await getArtifactBytes(key);
    if (!bytes) continue;
    out.push({
      frame_id: frameId,
      media_type: "image/jpeg",
      data_b64: bytes.toString("base64"),
    });
  }
  return out;
}
