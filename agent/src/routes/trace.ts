import type { FastifyPluginAsync } from "fastify";

import {
  aggregateCost,
  LogfireReadError,
  spansForScene,
  toTree,
  type SpanRow,
} from "../lib/logfire-read.js";
import { SCENE_ID_RE } from "../schemas.js";

// Per-scene span-row cache. Both endpoints (`/api/trace/:scene_id` and
// `/api/trace/:scene_id/cost`) derive from the same Logfire query; share the
// cache so a UI that polls cost separately doesn't double the read load.
interface CacheEntry {
  at: number;
  rows: SpanRow[];
}
const spanCache = new Map<string, CacheEntry>();
const TRACE_TTL_MS = 30_000;

async function getRowsCached(sceneId: string): Promise<SpanRow[]> {
  const hit = spanCache.get(sceneId);
  if (hit && Date.now() - hit.at < TRACE_TTL_MS) return hit.rows;
  const rows = await spansForScene(sceneId);
  spanCache.set(sceneId, { at: Date.now(), rows });
  return rows;
}

export const traceRoute: FastifyPluginAsync = async (app) => {
  app.get<{ Params: { scene_id: string } }>(
    "/api/trace/:scene_id",
    async (request, reply) => {
      const sceneId = request.params.scene_id;
      if (!SCENE_ID_RE.test(sceneId)) {
        return reply.code(400).send({ error: "invalid scene_id" });
      }
      try {
        const rows = await getRowsCached(sceneId);
        return {
          scene_id: sceneId,
          span_count: rows.length,
          tree: toTree(rows),
          cost: aggregateCost(rows),
        };
      } catch (err) {
        if (err instanceof LogfireReadError) {
          request.log.warn(
            { status: err.status, body: err.body.slice(-500) },
            "logfire read failed",
          );
          return reply.code(502).send({ error: "logfire read failed" });
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
        const rows = await getRowsCached(sceneId);
        return aggregateCost(rows);
      } catch (err) {
        if (err instanceof LogfireReadError) {
          return reply.code(502).send({ error: "logfire read failed" });
        }
        throw err;
      }
    },
  );
};
