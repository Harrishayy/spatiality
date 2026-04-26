import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, unlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Transform } from "node:stream";
import { pipeline } from "node:stream/promises";
import { createWriteStream } from "node:fs";

import type { FastifyPluginAsync } from "fastify";

import { presignPut, r2Configured } from "../lib/r2.js";
import { newSceneId, sanitizeFilename } from "../lib/sceneId.js";
import { InitUploadBody } from "../schemas.js";

const ARTIFACTS_VOLUME = "glasses-twin-artifacts";

// In-memory dedupe: SHA-256 of the uploaded bytes → scene that already owns
// them. Resets on process restart, which is fine — the worst case is one
// duplicate scene after a deploy.
const seenBySha = new Map<string, { sceneId: string; modalPath: string }>();

export const uploadsRoute: FastifyPluginAsync = async (app) => {
  // ── R2 mode: hand the browser a presigned PUT URL ────────────────────
  app.post("/api/uploads/init", async (request, reply) => {
    if (!r2Configured) {
      return reply.code(400).send({ error: "R2 not configured on agent — use local mode" });
    }
    const parsed = InitUploadBody.safeParse(request.body);
    if (!parsed.success) {
      return reply.code(400).send({ error: parsed.error.message });
    }
    const { filename, content_type, size_bytes } = parsed.data;
    if (!content_type.startsWith("video/")) {
      return reply.code(400).send({ error: "content_type must be video/*" });
    }
    const sceneId = newSceneId();
    const safe = sanitizeFilename(filename);
    const r2Key = `uploads/${sceneId}/${safe}`;
    const uploadUrl = await presignPut(r2Key, content_type, 3600);
    return {
      scene_id: sceneId,
      r2_key: r2Key,
      upload_url: uploadUrl,
      expires_in_seconds: 3600,
      size_bytes,
    };
  });

  // ── Local mode: accept multipart, push to Modal Volume via CLI ───────
  app.post("/api/uploads/local", async (request, reply) => {
    const file = await request.file({ limits: { fileSize: 5_000_000_000 } });
    if (!file) return reply.code(400).send({ error: "no file in multipart body" });

    const sceneId = newSceneId();
    const safe = sanitizeFilename(file.filename || "video.mp4");
    const tmpDir = join(tmpdir(), "glasses-twin", sceneId);
    await mkdir(tmpDir, { recursive: true });
    const tmpPath = join(tmpDir, safe);

    const hash = createHash("sha256");
    const hashTap = new Transform({
      transform(chunk, _, cb) {
        hash.update(chunk);
        cb(null, chunk);
      },
    });
    await pipeline(file.file, hashTap, createWriteStream(tmpPath));
    if (file.file.truncated) {
      await unlink(tmpPath).catch(() => {});
      return reply.code(413).send({ error: "file too large" });
    }
    const sha = hash.digest("hex");

    const cached = seenBySha.get(sha);
    if (cached) {
      await unlink(tmpPath).catch(() => {});
      request.log.info({ sha, scene_id: cached.sceneId }, "dedupe hit");
      return { scene_id: cached.sceneId, modal_path: cached.modalPath, deduped: true };
    }

    const modalPath = `/scenes/${sceneId}/_upload.mp4`;
    // `modal volume put <volume> <local> <remote> --force`. Strip the leading
    // slash because the Modal CLI treats remote paths as relative to volume root.
    const remote = modalPath.replace(/^\//, "");
    const res = await runCmd("modal", ["volume", "put", ARTIFACTS_VOLUME, tmpPath, remote, "--force"]);
    await unlink(tmpPath).catch(() => {});

    if (res.code !== 0) {
      // stderr can quote auth headers or volume paths from the modal CLI —
      // log it server-side, never echo to the browser.
      request.log.error({ stderr: res.stderr.slice(-500) }, "modal volume put failed");
      return reply.code(500).send({ error: "modal volume put failed" });
    }

    seenBySha.set(sha, { sceneId, modalPath });
    return { scene_id: sceneId, modal_path: modalPath };
  });
};

function runCmd(
  cmd: string,
  args: string[],
): Promise<{ code: number; stdout: string; stderr: string }> {
  return new Promise((resolve) => {
    const child = spawn(cmd, args, { stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (b) => (stdout += b.toString()));
    child.stderr.on("data", (b) => (stderr += b.toString()));
    child.on("close", (code) => resolve({ code: code ?? -1, stdout, stderr }));
    child.on("error", (err) => resolve({ code: -1, stdout, stderr: stderr + String(err) }));
  });
}
