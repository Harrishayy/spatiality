import Fastify from "fastify";
import cors from "@fastify/cors";
import multipart from "@fastify/multipart";

import { uploadsRoute } from "./routes/uploads.js";
import { jobsRoute } from "./routes/jobs.js";

const PORT = Number(process.env.PORT ?? 8080);
const HOST = process.env.HOST ?? "0.0.0.0";

const app = Fastify({
  logger: { level: process.env.LOG_LEVEL ?? "info" },
  bodyLimit: 10 * 1024 * 1024,
});

await app.register(cors, {
  origin: (origin, cb) => {
    // Allow no-origin (curl, server-to-server), and any explicit allow-list.
    if (!origin) return cb(null, true);
    const allowed = (process.env.CORS_ORIGINS ?? "http://localhost:5173,http://localhost:3000")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    cb(null, allowed.includes(origin) || allowed.includes("*"));
  },
  credentials: false,
});

await app.register(multipart, {
  limits: { fileSize: 5_000_000_000, files: 1 },
});

app.get("/health", async () => ({ ok: true }));

await app.register(uploadsRoute);
await app.register(jobsRoute);

app
  .listen({ port: PORT, host: HOST })
  .then((addr) => app.log.info(`agent listening on ${addr}`))
  .catch((err) => {
    app.log.error(err);
    process.exit(1);
  });
