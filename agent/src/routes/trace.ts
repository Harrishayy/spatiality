import type { FastifyBaseLogger, FastifyPluginAsync } from "fastify";

import {
  aggregateCost,
  LogfireReadError,
  spansForScene,
  toTree,
  type SpanRow,
} from "../lib/logfire-read.js";
import { getArtifactJson, putArtifactJson } from "../lib/r2.js";
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

const SNAPSHOT_KEY = (sceneId: string) => `scenes/${sceneId}/trace.json`;

// Logfire-read attempts can outlive the request that made the snapshot worth
// taking; debounce concurrent writes so the first finished snapshot wins and
// we don't hammer R2 from parallel pollers.
const inflightSnapshot = new Set<string>();

async function readSnapshot(sceneId: string): Promise<SpanRow[] | null> {
  try {
    const snap = await getArtifactJson<{ rows: SpanRow[] }>(SNAPSHOT_KEY(sceneId));
    return snap?.rows ?? null;
  } catch {
    return null;
  }
}

function writeSnapshot(sceneId: string, rows: SpanRow[], log: FastifyBaseLogger): void {
  if (inflightSnapshot.has(sceneId)) return;
  inflightSnapshot.add(sceneId);
  void putArtifactJson(SNAPSHOT_KEY(sceneId), { rows, snapshot_at: new Date().toISOString() })
    .catch((err) => log.warn({ err, sceneId }, "trace snapshot write failed"))
    .finally(() => inflightSnapshot.delete(sceneId));
}

// Resolve span rows for a scene, with R2 snapshot fallback. Logfire is the
// live source of truth (covers in-flight pipelines and recent runs); the R2
// snapshot at scenes/<id>/trace.json is what keeps demos viewable after
// Logfire's retention window aged the spans out.
async function getRowsCached(
  sceneId: string,
  log: FastifyBaseLogger,
): Promise<{ rows: SpanRow[]; source: "live" | "snapshot" | "live-empty" }> {
  const hit = spanCache.get(sceneId);
  if (hit && Date.now() - hit.at < TRACE_TTL_MS) {
    return { rows: hit.rows, source: hit.rows.length ? "live" : "live-empty" };
  }

  let liveRows: SpanRow[] | null = null;
  let liveErr: unknown = null;
  try {
    liveRows = await spansForScene(sceneId);
  } catch (err) {
    liveErr = err;
  }

  if (liveRows && liveRows.length > 0) {
    spanCache.set(sceneId, { at: Date.now(), rows: liveRows });
    writeSnapshot(sceneId, liveRows, log);
    return { rows: liveRows, source: "live" };
  }

  const snapshot = await readSnapshot(sceneId);
  if (snapshot && snapshot.length > 0) {
    spanCache.set(sceneId, { at: Date.now(), rows: snapshot });
    return { rows: snapshot, source: "snapshot" };
  }

  if (liveErr) throw liveErr;
  spanCache.set(sceneId, { at: Date.now(), rows: liveRows ?? [] });
  return { rows: liveRows ?? [], source: "live-empty" };
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
        const { rows, source } = await getRowsCached(sceneId, request.log);
        return {
          scene_id: sceneId,
          span_count: rows.length,
          tree: toTree(rows),
          cost: aggregateCost(rows),
          source,
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
        const { rows } = await getRowsCached(sceneId, request.log);
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
