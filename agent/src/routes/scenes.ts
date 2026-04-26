import type { FastifyPluginAsync } from "fastify";

import { getArtifactJson, listSceneIds } from "../lib/r2.js";

interface ManifestSummary {
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

interface ManifestLike {
  scene_id?: string;
  status?: string;
  created_at?: string;
  stats?: ManifestSummary["stats"];
  artifacts?: { thumbnail_jpg?: string };
  stages?: Record<string, { duration_s?: number }>;
}

interface CacheEntry {
  at: number;
  body: ManifestSummary[];
}

let cache: CacheEntry | null = null;
const TTL_MS = 30_000;

export const scenesRoute: FastifyPluginAsync = async (app) => {
  app.get("/api/scenes", async (_request, reply) => {
    if (cache && Date.now() - cache.at < TTL_MS) return cache.body;

    let ids: string[];
    try {
      ids = await listSceneIds();
    } catch (err) {
      app.log.error({ err }, "list scenes failed");
      return reply.code(502).send({ error: "list scenes failed" });
    }

    const summaries = await Promise.all(
      ids.map(async (id): Promise<ManifestSummary | null> => {
        try {
          const m = await getArtifactJson<ManifestLike>(
            `scenes/${id}/manifest.json`,
          );
          if (!m) return null;
          const stages = m.stages ?? {};
          const total = Object.values(stages).reduce(
            (acc, s) => acc + (s?.duration_s ?? 0),
            0,
          );
          return {
            scene_id: m.scene_id ?? id,
            status: m.status,
            created_at: m.created_at,
            stats: m.stats,
            thumbnail: m.artifacts?.thumbnail_jpg,
            total_duration_s: total > 0 ? Math.round(total * 10) / 10 : undefined,
          };
        } catch {
          return null;
        }
      }),
    );

    const body = summaries
      .filter((s): s is ManifestSummary => s !== null)
      .sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));

    cache = { at: Date.now(), body };
    return body;
  });
};
