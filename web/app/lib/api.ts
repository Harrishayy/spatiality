import type {
  Annotation,
  ChatMessage,
  GatewayHealth,
  JobSettings,
  Manifest,
  TraceResponse,
} from "./types";

export const DEMO_SCENE_ID = "demo_bedroom";

function getArtifactUrl(sceneId: string, artifact: string): string {
  const r2Base = process.env.NEXT_PUBLIC_R2_ARTIFACTS_PUBLIC_BASE;
  const useR2 = r2Base && process.env.NEXT_PUBLIC_DEFAULT_MODE !== "local";
  if (useR2) {
    return `${r2Base}/scenes/${sceneId}/${artifact}`;
  }
  return `/m/get-artifact?scene_id=${encodeURIComponent(sceneId)}&path=${encodeURIComponent(artifact)}`;
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
  const res = await fetch(`/api/jobs/${sceneId}`);
  return unwrap(res, "fetchManifest");
}

export async function fetchAnnotations(sceneId: string): Promise<Annotation[]> {
  const res = await fetch(getArtifactUrl(sceneId, "annotations.json"));
  return unwrap(res, "fetchAnnotations");
}

export async function fetchSplatUrl(sceneId: string): Promise<string> {
  return getArtifactUrl(sceneId, "splat.ply");
}

export function frameUrl(sceneId: string, frameName: string): string {
  return getArtifactUrl(sceneId, `frames/${frameName}.jpg`);
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
