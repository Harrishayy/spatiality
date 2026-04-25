# /agent — Render orchestration backend

Fastify (TypeScript) service that bridges the web app and Modal:

- `POST /api/uploads/init` → presigned R2 PUT URL (R2 mode)
- `POST /api/uploads/local` → multipart upload, pushes to Modal Volume via `modal volume put` (local mode)
- `POST /api/jobs` → fires `process_video` on Modal
- `GET /api/jobs/:scene_id?mode=r2|local` → manifest passthrough (R2 bucket in r2 mode, Modal `get_manifest` in local mode)
- `GET /health`

Run locally: `pnpm install && pnpm --filter agent dev`.
Local mode requires the `modal` CLI authenticated (`modal token current`).

Env: see project-root `.env.example` (R2_*, MODAL_PROCESS_VIDEO_URL, MODAL_GET_MANIFEST_URL, CORS_ORIGINS).
