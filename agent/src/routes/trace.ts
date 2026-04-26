import type { FastifyPluginAsync } from "fastify";

import {
  aggregateCost,
  LogfireReadError,
  spansForScene,
  toTree,
} from "../lib/logfire-read.js";

// Per-scene response cache (30s for completed scenes, off while processing).
// Read-API queries are cheap but not free; this also dampens UI poll storms.
interface CacheEntry {
  at: number;
  body: unknown;
}
const traceCache = new Map<string, CacheEntry>();
const TRACE_TTL_MS = 30_000;

const SCENE_ID_RE = /^[A-Za-z0-9_-]{1,64}$/;

export const traceRoute: FastifyPluginAsync = async (app) => {
  app.get<{ Params: { scene_id: string } }>(
    "/api/trace/:scene_id",
    async (request, reply) => {
      const sceneId = request.params.scene_id;
      if (!SCENE_ID_RE.test(sceneId)) {
        return reply.code(400).send({ error: "invalid scene_id" });
      }
      const cacheKey = `tree:${sceneId}`;
      const hit = traceCache.get(cacheKey);
      if (hit && Date.now() - hit.at < TRACE_TTL_MS) {
        return hit.body;
      }
      try {
        const rows = await spansForScene(sceneId);
        const body = {
          scene_id: sceneId,
          span_count: rows.length,
          tree: toTree(rows),
          cost: aggregateCost(rows),
        };
        traceCache.set(cacheKey, { at: Date.now(), body });
        return body;
      } catch (err) {
        if (err instanceof LogfireReadError) {
          request.log.warn({ status: err.status, body: err.body.slice(-500) }, "logfire read failed");
          return reply.code(502).send({ error: "logfire read failed", detail: err.message });
        }
        throw err;
      }
    },
  );

  app.get<{ Params: { scene_id: string } }>(
    "/api/trace/:scene_id/cost",
    async (request, reply) => {
      const sceneId = request.params.scene_id;
      if (!SCENE_ID_RE.test(sceneId)) {
        return reply.code(400).send({ error: "invalid scene_id" });
      }
      try {
        const rows = await spansForScene(sceneId);
        return aggregateCost(rows);
      } catch (err) {
        if (err instanceof LogfireReadError) {
          return reply.code(502).send({ error: "logfire read failed", detail: err.message });
        }
        throw err;
      }
    },
  );
};
