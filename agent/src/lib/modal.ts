const MODAL_PROCESS_VIDEO_URL = process.env.MODAL_PROCESS_VIDEO_URL ?? "";
const MODAL_GET_MANIFEST_URL = process.env.MODAL_GET_MANIFEST_URL ?? "";

export type ProcessVideoSource =
  | { kind: "r2"; r2_key: string }
  | { kind: "local"; modal_path: string };

export interface ProcessVideoBody {
  scene_id: string;
  source: ProcessVideoSource;
  settings: unknown;
}

export interface FireResult {
  ok: boolean;
  status: number;
  body: string;
}

export async function fireProcessVideo(body: ProcessVideoBody): Promise<FireResult> {
  if (!MODAL_PROCESS_VIDEO_URL) {
    return { ok: false, status: 0, body: "MODAL_PROCESS_VIDEO_URL not set" };
  }
  const res = await fetch(MODAL_PROCESS_VIDEO_URL, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  return { ok: res.ok, status: res.status, body: text };
}

export async function fetchManifestFromModal(sceneId: string): Promise<unknown | null> {
  if (!MODAL_GET_MANIFEST_URL) return null;
  const url = `${MODAL_GET_MANIFEST_URL}?scene_id=${encodeURIComponent(sceneId)}`;
  const res = await fetch(url);
  if (res.status === 404) return null;
  if (!res.ok) {
    const detail = (await res.text()).slice(-300);
    throw new Error(`modal get_manifest ${res.status}: ${detail}`);
  }
  return res.json();
}
