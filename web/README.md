# /web — Glasses → 3D Twin viewer

Next.js 16 (App Router) + React 18 + TypeScript strict + Three.js + `@mkkellogg/gaussian-splats-3d` + Tailwind.

Spec: [`../plans/modules/06_web.md`](../plans/modules/06_web.md). Schema mirror lives at [`app/lib/types.ts`](./app/lib/types.ts) — keep in sync with `shared/shared/schemas/*.py`.

## What ships out of the box

- **SplatViewer** — drag/orbit/zoom, loads `splat.ply` via `gaussian-splats-3d`. When the splat is empty (stub scene), falls back to a Three.js placeholder with annotation bboxes rendered as wireframes so the rest of the UI is exercisable. Dynamically imported with `ssr: false` since it owns a WebGL context.
- **AnnotationOverlay** — HTML billboard pins anchored to each annotation centroid; tap to select, double-tap to isolate (Module 04 Path A).
- **PipelineProgress** — auto-polls `manifest.json` every 2 s until `status === "ready"`, then loads splat + annotations.
- **ChatPanel** — messages list + input. Mock responses canned in `app/lib/api.ts` until `NEXT_PUBLIC_AGENT_URL` is set.
- **WhereAmIButton** — frustum-filters annotations, POSTs to `/api/agent/locate`, shows the answer back in chat.
- **Object isolation** — Tap pin or sidebar row to select; double-tap (or sidebar ◉) to toggle isolation. Hidden cluster annotations dim to 30% opacity. Once a real splat with `cluster_gaussian_indices` is wired, the same toggle hides those Gaussians too — that's the only edit needed in `SplatViewer.tsx`.

## Routes

- `/` — server redirect to the demo scene.
- `/scenes/[id]` — viewer for a given scene (e.g. `/scenes/test_scene_v0`, `/scenes/modal_smoke_v2`).

## Run locally (mock backend)

```
pnpm install
pnpm dev      # → http://localhost:5173
```

By default the app talks to itself: a mock API (`app/lib/api.ts`) returns the demo scene from `web/public/artifacts/scenes/test_scene_v0/`. No backend required.

## Run against a real /agent

Set `NEXT_PUBLIC_AGENT_URL` and Next rewrites `/api` and `/artifacts` to the agent service:

```
NEXT_PUBLIC_AGENT_URL=https://glasses-twin-agent.onrender.com pnpm dev
```

Or build for prod:

```
NEXT_PUBLIC_AGENT_URL=https://glasses-twin-agent.onrender.com pnpm build
pnpm start
```

## File contracts (read; don't drift)

- `manifest.json` — schema in [`../plans/modules/05_storage.md`](../plans/modules/05_storage.md)
- `annotations.json` — same spec; rendered as billboards
- `splat.ply` — fetched URL passed to `gaussian-splats-3d`'s `addSplatScene`

## What's NOT in here (per spec)

- Upload UI — wire when `/api/upload` is live
- Voice input — stretch
- PWA manifest — stretch
