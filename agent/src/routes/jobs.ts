import type { FastifyPluginAsync } from "fastify";

import { fetchManifestFromModal, fireProcessVideo } from "../lib/modal.js";
import { getArtifactJson, R2_ARTIFACTS_BUCKET } from "../lib/r2.js";
import { SubmitJobBody } from "../schemas.js";

interface CacheEntry {
  at: number;
  body: unknown | null;
}
const manifestCache = new Map<string, CacheEntry>();
const CACHE_TTL_MS = 1_000;

export const jobsRoute: FastifyPluginAsync = async (app) => {
  app.post("/api/jobs", async (request, reply) => {
    const parsed = SubmitJobBody.safeParse(request.body);
    if (!parsed.success) return reply.code(400).send({ error: parsed.error.message });

    const body = parsed.data;
    const source =
      body.mode === "r2"
        ? { kind: "r2" as const, r2_key: body.r2_key }
        : { kind: "local" as const, modal_path: body.modal_path };

    const fired = await fireProcessVideo({
      scene_id: body.scene_id,
      source,
      settings: body.settings,
    });
    if (!fired.ok) {
      request.log.error({ status: fired.status, body: fired.body.slice(-500) }, "process_video failed");
      return reply.code(502).send({ error: "modal process_video failed", detail: fired.body.slice(-500) });
    }
    return { status: "queued", scene_id: body.scene_id, mode: body.mode };
  });

  app.get<{ Params: { scene_id: string }; Querystring: { mode?: string } }>(
    "/api/jobs/:scene_id",
    async (request, reply) => {
      const sceneId = request.params.scene_id;
      const mode = request.query.mode === "local" ? "local" : "r2";
      const cacheKey = `${mode}:${sceneId}`;
      const hit = manifestCache.get(cacheKey);
      if (hit && Date.now() - hit.at < CACHE_TTL_MS) {
        if (hit.body === null) return reply.code(404).send();
        return hit.body;
      }
      try {
        const m =
          mode === "local"
            ? await fetchManifestFromModal(sceneId)
            : R2_ARTIFACTS_BUCKET
              ? await getArtifactJson<unknown>(`scenes/${sceneId}/manifest.json`)
              : null;
        manifestCache.set(cacheKey, { at: Date.now(), body: m });
        if (m === null) return reply.code(404).send();
        return m;
      } catch (err) {
        request.log.error({ err }, "manifest fetch failed");
        return reply.code(502).send({ error: "manifest fetch failed" });
      }
    },
  );
};
