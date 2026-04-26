# Project: Glasses → 3D Twin

24h hackathon build. Multi-module, decentralized architecture. Read [`plans/ORCHESTRATOR.md`](plans/ORCHESTRATOR.md) for the system overview. Per-module specs live in [`plans/modules/`](plans/modules/).

## Hard rules (don't violate)

- **File contract:** all artifacts live under `artifacts/scenes/<scene_id>/`. The full schema (manifest.json, annotations.json) is defined in [`plans/modules/05_storage.md`](plans/modules/05_storage.md). Modules that read or write artifacts must conform exactly.
- **Model calls:** every model call routes through Pydantic AI Gateway. Anthropic SDK uses `authToken` (Bearer header), NOT `apiKey`. Base URL is `https://gateway-eu.pydantic.dev/proxy/anthropic/`. See [`plans/modules/07_agent.md`](plans/modules/07_agent.md) for the exact instantiation.
- **Observability:** every Python pipeline stage emits Logfire spans with the names listed in [`plans/modules/08_observability.md`](plans/modules/08_observability.md). The demo cites these spans on stage — span names and metadata must match the playbook.
- **No database.** Flat files only. Manifests are the source of truth.
- **No auth, no multi-user.** Single-scene demo.
- **Stub aggressively.** A working end-to-end pipeline with stubs in some modules beats any one polished module. Use `TODO(swap):` comments to mark deferred work.

## Session scopes

Each Claude Code session is scoped to one of these. The user's first prompt will name which session this is. Do not touch modules outside the named scope — generate stub outputs matching the storage schemas instead.

- **Session A — Bootstrap.** Reads: README, ORCHESTRATOR, 05_storage, 08_observability, 09_deployment. Output: repo scaffold, justfile, schemas typed in pydantic + TS, render.yaml, Modal app skeleton, Logfire wired into agent and pipeline stubs.
- **Session B — Pipeline.** Reads: 01_capture, 02_inference, 09_deployment (Modal section). Output: working capture and inference modules, Modal app function body, end-to-end smoke test on `samples/`. (10_kaggle is archived at `old/kaggle/` — Kaggle was the early test path; we ship on Modal.)
- **Session C — Segmentation.** Reads: 03_segmentation. Output: SAM 3.1 mask generation + VLM labeling pipeline; emits annotations.json conforming to the schema.
- **Session D — Polish.** Reads: 04_object_isolation. Output: integration testing, second test scene, demo-bake script.

`/web` and `/agent` live in this repo and are in-scope for any session — see [`plans/modules/06_web.md`](plans/modules/06_web.md) and [`plans/modules/07_agent.md`](plans/modules/07_agent.md) for their specs.

## Conventions
- Python 3.11. `uv` for env management. `pyproject.toml` per Python module.
- Node 20+. pnpm. TS strict mode.
- `justfile` at the root for top-level recipes (`just capture`, `just infer`, etc.).
- Type everything: pydantic models for Python data, TS interfaces for JS data.
- Git commit after each module reaches "scaffolded with stub output" state.
- All env vars documented in `.env.example`. Never commit secrets.
- **UI design system.** Visual contract lives in [`docs/DESIGN_SYSTEM.md`](docs/DESIGN_SYSTEM.md): warm-sunset `ink/accent` tokens, `.lp-*` component class API, voice & copy rules. Tokens are wired in [`web/tailwind.config.mjs`](web/tailwind.config.mjs) + [`web/app/styles/landing.css`](web/app/styles/landing.css); live reference at `/design-system`. Match it pixel-for-pixel; don't fork class names; don't introduce new accent colors outside the coral → apricot → gold ramp.

## When ambiguity hits
- Read the relevant module file in `plans/modules/`. The answer is usually there.
- If still ambiguous, pick the simpler option and add a `TODO(swap):` comment explaining the tradeoff. Do not block on trivia.
- If a decision affects another module's contract, stop and surface it — that's the only category worth interrupting flow for.
