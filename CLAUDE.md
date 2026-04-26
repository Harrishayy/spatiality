# Project: Spatiality — fast inference for 3D meshes

Multi-module, decentralized architecture. The headline is **fast inference for 3D meshes**: any short video pass (phone, GoPro, smart glasses — Ray-Ban is one of several supported inputs) becomes a measurable, queryable 3D mesh in under five minutes.

## Modules

- `capture/` — mp4 (any camera) → frames (ffmpeg).
- `inference/` — frames → Gaussian splat (VGGT depth + per-pixel surfel synthesis); Modal app lives in `inference/modal_app.py`.
- `segmentation/` — splat + frames → annotations (SAM 3.1 + Claude Haiku VLM).
- `shared/` — pydantic + TS schemas (manifest, annotations, capture), Logfire wiring, Pydantic AI Gateway client.
- `agent/` — Hono service on Render: capture intake, manifest polling, chat tool-use loop.
- `web/` — Next.js viewer (splat + annotations + chat).

## Hard rules (don't violate)

- **File contract:** all artifacts live under `artifacts/scenes/<scene_id>/`. Schemas of record: [`shared/shared/schemas/manifest.py`](shared/shared/schemas/manifest.py) and [`shared/shared/schemas/annotations.py`](shared/shared/schemas/annotations.py) (TS mirrors in `shared/types/`). Modules that read or write artifacts must conform exactly.
- **Model calls:** every model call routes through Pydantic AI Gateway. Anthropic SDK uses `authToken` (Bearer header), NOT `apiKey`. Base URL is `https://gateway-eu.pydantic.dev/proxy/anthropic/`. Client construction lives in [`shared/shared/gateway.py`](shared/shared/gateway.py); never bypass it.
- **Observability:** every Python pipeline stage emits Logfire spans using the constants in [`shared/shared/observability.py`](shared/shared/observability.py). Never inline span name strings.
- **No database.** Flat files only. Manifests are the source of truth.
- **No auth, no multi-user.** Single-scene demo.
- **Stub aggressively.** A working end-to-end pipeline with stubs in some modules beats any one polished module. Use `TODO(swap):` comments to mark deferred work.

## Conventions
- Python 3.11. `uv` for env management. `pyproject.toml` per Python module.
- Node 20+. pnpm. TS strict mode.
- `justfile` at the root for top-level recipes (`just capture`, `just infer`, etc.).
- Type everything: pydantic models for Python data, TS interfaces for JS data.
- All env vars documented in `.env.example`. Never commit secrets.
- **UI design system.** Visual contract lives in [`docs/DESIGN_SYSTEM.md`](docs/DESIGN_SYSTEM.md): warm-sunset `ink/accent` tokens, `.lp-*` component class API, voice & copy rules. Tokens are wired in [`web/tailwind.config.mjs`](web/tailwind.config.mjs) + [`web/app/styles/landing.css`](web/app/styles/landing.css); live reference at `/design-system`. Match it pixel-for-pixel; don't fork class names; don't introduce new accent colors outside the coral → apricot → gold ramp.

## When ambiguity hits
- Pick the simpler option and add a `TODO(swap):` comment explaining the tradeoff. Do not block on trivia.
- If a decision affects another module's contract (schema field, span name, endpoint shape), stop and surface it — that's the only category worth interrupting flow for.
