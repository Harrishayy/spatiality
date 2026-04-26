// Annotation + frame-image helpers used by the chat tool-use loop.
//
// Primary store is R2 (artifacts/scenes/<id>/annotations.json + frames/),
// but the segmentation pipeline writes everything to the Modal Volume
// FIRST and only mirrors a subset to R2. When the mirror is broken or
// hasn't run yet, R2 returns 404 and chat would lose every label.
//
// Modal's `get-artifact` endpoint serves the same files straight off the
// Volume, so it's the always-correct fallback. The web side already does
// this via `getArtifactUrl` in web/app/lib/api.ts; the agent now mirrors
// that behavior for its own reads.

import { getArtifactBytes, getArtifactJson } from "./r2.js";

const MODAL_GET_ARTIFACT_URL =
  process.env.MODAL_GET_ARTIFACT_URL ??
  process.env.NEXT_PUBLIC_MODAL_GET_ARTIFACT_URL ??
  "";

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

// The segmentation pipeline (`AnnotationsFile.write_atomic` →
// `RootModel[list[Annotation]].model_dump_json`) emits a bare JSON array
// at the top level, NOT a `{ annotations: [...] }` wrapper. Earlier code
// here parsed only the wrapped shape and silently returned [] for every
// real run. Accept both so this never traps us again.
type AnnotationsPayload = AnnotationLite[] | { annotations?: AnnotationLite[] };

function flatten(payload: AnnotationsPayload | null): AnnotationLite[] {
  if (!payload) return [];
  const arr = Array.isArray(payload) ? payload : payload.annotations ?? [];
  return arr.map((a) => ({
    id: a.id,
    label: a.label,
    centroid: a.centroid,
    bbox: a.bbox,
    frame_ids: a.frame_ids,
  }));
}

async function fetchAnnotationsFromModal(
  sceneId: string,
): Promise<AnnotationLite[]> {
  if (!MODAL_GET_ARTIFACT_URL) return [];
  try {
    const url = `${MODAL_GET_ARTIFACT_URL}?scene_id=${encodeURIComponent(
      sceneId,
    )}&file=annotations.json`;
    const res = await fetch(url);
    if (!res.ok) return [];
    const data = (await res.json()) as AnnotationsPayload;
    return flatten(data);
  } catch {
    return [];
  }
}

export async function loadAnnotations(sceneId: string): Promise<AnnotationLite[]> {
  // Fast path: R2 (production preference). NoSuchKey/404 yields null —
  // that's the missing-mirror case the Modal fallback below handles.
  let primary: AnnotationLite[] = [];
  try {
    const r2 = await getArtifactJson<AnnotationsPayload>(
      `scenes/${sceneId}/annotations.json`,
    );
    primary = flatten(r2);
  } catch {
    // Surface nothing — fall through to Modal.
  }
  if (primary.length > 0) return primary;

  // Slow path: Modal Volume via the public get-artifact endpoint. Always
  // correct since segmentation writes to the Volume directly.
  return fetchAnnotationsFromModal(sceneId);
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

async function fetchFrameBytesFromModal(
  sceneId: string,
  frameId: string,
): Promise<Buffer | null> {
  if (!MODAL_GET_ARTIFACT_URL) return null;
  try {
    const url = `${MODAL_GET_ARTIFACT_URL}?scene_id=${encodeURIComponent(
      sceneId,
    )}&file=frames/${encodeURIComponent(frameId)}`;
    const res = await fetch(url);
    if (!res.ok) return null;
    const arr = new Uint8Array(await res.arrayBuffer());
    return Buffer.from(arr);
  } catch {
    return null;
  }
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
    let bytes: Buffer | null = null;
    try {
      bytes = await getArtifactBytes(key);
    } catch {
      // Same fallback story as loadAnnotations: R2 may not have the
      // frame yet (mirror skipped or never ran). Modal Volume always does.
    }
    if (!bytes) bytes = await fetchFrameBytesFromModal(sceneId, frameId);
    if (!bytes) continue;
    out.push({
      frame_id: frameId,
      media_type: "image/jpeg",
      data_b64: bytes.toString("base64"),
    });
  }
  return out;
}
