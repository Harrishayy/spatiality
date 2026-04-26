import type {
  Annotation,
  ChatMessage,
  CostAggregate,
  GatewayHealth,
  JobSettings,
  Manifest,
  TraceResponse,
} from "./types";

export const DEMO_SCENE_ID = "demo_bedroom";

/** Self-contained scene served from web/public/demo. Used when R2 / Modal /
 *  the agent service aren't reachable so the viewer still has something to
 *  show on a fresh localhost. Scene IDs starting with "_" are reserved for
 *  this kind of fixture. */
export const LOCAL_DEMO_SCENE_ID = "_demo_room";

const LOCAL_DEMO_SUMMARY: SceneSummary = {
  scene_id: LOCAL_DEMO_SCENE_ID,
  status: "ready",
  created_at: new Date().toISOString(),
  stats: { frame_count: 60, object_count: 3, splat_size_mb: 0.26 },
  total_duration_s: 4.2,
};

const LOCAL_DEMO_MANIFEST: Manifest = {
  scene_id: LOCAL_DEMO_SCENE_ID,
  created_at: LOCAL_DEMO_SUMMARY.created_at!,
  status: "ready",
  stages: {
    capture:      { status: "complete", duration_s: 0.6 },
    poses:        { status: "complete", duration_s: 1.8, method: "stub", frame_count: 60 },
    splat:        { status: "complete", duration_s: 0.4, method: "stub", gaussian_count: 17334 },
    segmentation: { status: "complete", duration_s: 1.4, method: "stub", object_count: 3 },
  },
  artifacts: {
    splat_ply:        "/demo/points.ply",
    annotations_json: "/demo/annotations.json",
  },
  stats: { frame_count: 60, object_count: 3, splat_size_mb: 0.26 },
  errors: [],
};

const isLocalDemo = (sceneId: string) => sceneId === LOCAL_DEMO_SCENE_ID;

export function getArtifactUrl(sceneId: string, artifact: string): string {
  if (isLocalDemo(sceneId)) {
    return `/demo/${artifact}`;
  }
  const r2Base = process.env.NEXT_PUBLIC_R2_ARTIFACTS_PUBLIC_BASE;
  const useR2 = r2Base && process.env.NEXT_PUBLIC_DEFAULT_MODE !== "local";
  if (useR2) {
    return `${r2Base}/scenes/${sceneId}/${artifact}`;
  }
  // Modal's get-artifact endpoint signature is `(scene_id, file)` — the
  // earlier `?path=` form returns HTTP 422 ("Field required: file") and
  // breaks every Modal-fallback fetch (annotations, frames, masks, …).
  return `/m/get-artifact?scene_id=${encodeURIComponent(sceneId)}&file=${encodeURIComponent(artifact)}`;
}

async function unwrap<T>(res: Response, label: string): Promise<T> {
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: `${label}: ${res.status}` }));
    throw new Error(err.error ?? `${label}: ${res.status}`);
  }
  return res.json();
}

export async function initR2Upload(params: {
  filename: string;
  content_type: string;
  size_bytes: number;
}): Promise<{
  scene_id: string;
  r2_key: string;
  upload_url: string;
  expires_in_seconds: number;
}> {
  const res = await fetch("/api/uploads/init", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(params),
  });
  return unwrap(res, "initR2Upload");
}

export type SubmitJobParams =
  | { mode: "r2"; scene_id: string; r2_key: string; settings: JobSettings }
  | { mode: "local"; scene_id: string; modal_path: string; settings: JobSettings };

export async function submitJob(
  params: SubmitJobParams,
): Promise<{ status: string; scene_id: string; mode: string }> {
  const res = await fetch("/api/jobs", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(params),
  });
  return unwrap(res, "submitJob");
}

export async function fetchManifest(sceneId: string): Promise<Manifest> {
  if (isLocalDemo(sceneId)) return LOCAL_DEMO_MANIFEST;
  const res = await fetch(`/api/jobs/${sceneId}`);
  return unwrap(res, "fetchManifest");
}

export async function fetchAnnotations(sceneId: string): Promise<Annotation[]> {
  const res = await fetch(getArtifactUrl(sceneId, "annotations.json"));
  return unwrap(res, "fetchAnnotations");
}

export async function fetchPointsUrl(sceneId: string): Promise<string> {
  // The viewer parser is hard-coded for points.ply (xyz + uchar rgb +
  // optional confidence). splat.ply uses INRIA's f_dc_* SH coefficients and
  // is consumed by the segmentation lift / mask projection only — never by
  // the web viewer.
  return getArtifactUrl(sceneId, "points.ply");
}

export function frameUrl(sceneId: string, frameName: string): string {
  return getArtifactUrl(sceneId, `frames/${frameName}.jpg`);
}

/**
 * Frame URL for the evidence gallery. Unlike `frameUrl`, this trusts the
 * caller's filename verbatim — `Annotation.frame_ids` from the real
 * segmentation pipeline already includes the file extension (e.g.
 * `0001.png`), so we must not append another one.
 */
export function evidenceFrameUrl(sceneId: string, frameName: string): string {
  return getArtifactUrl(sceneId, `frames/${frameName}`);
}

/**
 * Mask URL for the evidence gallery. Masks are written by
 * `segmentation.lift_masks._write_cluster_masks` as PNGs keyed by the
 * frame stem (no extension), so `0001.png` → `masks/<id>/0001.png`.
 */
export function maskUrl(
  sceneId: string,
  annotationId: string,
  frameName: string,
): string {
  const stem = frameName.replace(/\.[^./]+$/, "");
  return getArtifactUrl(sceneId, `masks/${annotationId}/${stem}.png`);
}

export async function postLocate(params: {
  scene_id: string;
  camera_pos: [number, number, number];
  camera_dir: [number, number, number];
  nearby: Array<{ id: string; label: string; centroid: [number, number, number] }>;
}): Promise<{
  text: string;
  primary_object_id: string | null;
  latency_ms: number;
  model: string;
}> {
  const res = await fetch("/api/agent/locate", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(params),
  });
  return unwrap(res, "postLocate");
}

export async function postChat(params: {
  scene_id: string;
  message: string;
  camera_pos: [number, number, number];
}): Promise<ChatMessage> {
  const res = await fetch("/api/agent/chat", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(params),
  });
  return unwrap(res, "postChat");
}

export async function fetchTrace(sceneId: string): Promise<TraceResponse> {
  const res = await fetch(`/api/trace/${sceneId}`);
  return unwrap(res, "fetchTrace");
}

/** Lightweight per-scene cost — same backend cache as `fetchTrace`, just
 *  the aggregated dollar / token / call totals. Drives the header
 *  CostBadge so it can refresh without pulling the full span tree. */
export async function fetchCost(sceneId: string): Promise<CostAggregate> {
  const res = await fetch(`/api/trace/${sceneId}/cost`);
  return unwrap(res, "fetchCost");
}

export interface SceneSummary {
  scene_id: string;
  status?: string;
  created_at?: string;
  stats?: {
    frame_count?: number;
    object_count?: number;
    splat_size_mb?: number;
  };
  thumbnail?: string;
  total_duration_s?: number;
}

export async function fetchScenes(): Promise<SceneSummary[]> {
  // Always include the bundled local demo so a fresh checkout has at least
  // one scene to open even if the agent / R2 aren't reachable.
  let remote: SceneSummary[] = [];
  try {
    const res = await fetch("/api/scenes", { cache: "no-store" });
    if (res.ok) remote = await res.json();
  } catch {
    // Agent unreachable — fall through to just the local demo.
  }
  const seen = new Set(remote.map((s) => s.scene_id));
  return seen.has(LOCAL_DEMO_SCENE_ID)
    ? remote
    : [LOCAL_DEMO_SUMMARY, ...remote];
}

export async function fetchGatewayHealth(): Promise<GatewayHealth | null> {
  try {
    const res = await fetch("/api/gateway/health");
    if (!res.ok) return null;
    const health = (await res.json()) as GatewayHealth;
    return health.ok ? health : null;
  } catch {
    return null;
  }
}
