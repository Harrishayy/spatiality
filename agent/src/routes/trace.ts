import type { FastifyBaseLogger, FastifyPluginAsync } from "fastify";

import { getAgentCost } from "../lib/agent-cost.js";
import {
  aggregateCost,
  type CostAggregate,
  LogfireReadError,
  spansForScene,
  toTree,
  type SpanRow,
} from "../lib/logfire-read.js";
import { getArtifactJson, putArtifactJson } from "../lib/r2.js";
import { SCENE_ID_RE } from "../schemas.js";

// Fold per-scene agent-side model usage (chat tool-loop turns recorded by
// `recordModelCall`) into the Logfire-derived totals so the scenes-page
// CostBadge reflects everything the user has spent on this scene, not just
// the segmentation labeler. Returns a new aggregate; doesn't mutate.
function withAgentCost(sceneId: string, base: CostAggregate): CostAggregate {
  const a = getAgentCost(sceneId);
  if (a.call_count === 0) return base;
  return {
    total_usd: round6(base.total_usd + a.total_usd),
    total_tokens_in: base.total_tokens_in + a.total_tokens_in,
    total_tokens_out: base.total_tokens_out + a.total_tokens_out,
    call_count: base.call_count + a.call_count,
    by_span: [
      ...base.by_span,
      {
        span_name: "agent.chat",
        usd: round6(a.total_usd),
        tokens_in: a.total_tokens_in,
        tokens_out: a.total_tokens_out,
      },
    ],
  };
}

function round6(n: number): number {
  return Math.round(n * 1_000_000) / 1_000_000;
}

// Per-scene span-row cache. Both endpoints (`/api/trace/:scene_id` and
// `/api/trace/:scene_id/cost`) derive from the same Logfire query; the
// cache exists so when the trace drawer's 10s poll and the cost badge's
// 5s poll happen to land near-simultaneously they don't double-read
// Logfire. TTL must stay strictly below the trace poll interval so live
// updates aren't served stale — 5s is just enough to dedupe overlapping
// /trace + /cost ticks and nothing more.
interface CacheEntry {
  at: number;
  rows: SpanRow[];
}
const spanCache = new Map<string, CacheEntry>();
const TRACE_TTL_MS = 5_000;

const SNAPSHOT_KEY = (sceneId: string) => `scenes/${sceneId}/trace.json`;

// Logfire-read attempts can outlive the request that made the snapshot worth
// taking; debounce concurrent writes so the first finished snapshot wins and
// we don't hammer R2 from parallel pollers.
const inflightSnapshot = new Set<string>();
// Throttle: at the trace drawer's 2s poll cadence we'd otherwise PUT a
// snapshot every tick of an in-flight pipeline. The snapshot only needs to
// stay fresh enough for the post-Logfire-retention fallback — a 30s lag is
// invisible to that use case.
const lastSnapshotAt = new Map<string, number>();
const SNAPSHOT_MIN_INTERVAL_MS = 30_000;

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
  const last = lastSnapshotAt.get(sceneId) ?? 0;
  if (Date.now() - last < SNAPSHOT_MIN_INTERVAL_MS) return;
  inflightSnapshot.add(sceneId);
  lastSnapshotAt.set(sceneId, Date.now());
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
          cost: withAgentCost(sceneId, aggregateCost(rows)),
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
        return withAgentCost(sceneId, aggregateCost(rows));
      } catch (err) {
        if (err instanceof LogfireReadError) {
          return reply.code(502).send({ error: "logfire read failed" });
        }
        throw err;
      }
    },
  );
};
