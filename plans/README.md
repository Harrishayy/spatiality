# Plans — Glasses → 3D Twin

Decentralized plan set for the Unicorn Mafia AI hackathon (24h, solo + Claude + Devin). Each module has a self-contained plan with file contracts; modules don't depend on each other at runtime, only on shared schemas.

Read in this order:

1. [`ORCHESTRATOR.md`](./ORCHESTRATOR.md) — north star, module map, critical path, time budget, demo script
2. [`modules/01_capture.md`](./modules/01_capture.md) — Ray-Ban mp4 → frames
3. [`modules/02_inference.md`](./modules/02_inference.md) — frames → Gaussian splat (VGGT + 3DGRUT)
4. [`modules/03_segmentation.md`](./modules/03_segmentation.md) — splat + frames → annotations (SAM 3.1 + VLM)
5. [`modules/04_object_isolation.md`](./modules/04_object_isolation.md) — per-object cluster isolation (stretch)
6. [`modules/05_storage.md`](./modules/05_storage.md) — artifact layer, manifest schema
7. [`modules/06_web.md`](./modules/06_web.md) — **Devin spec** — splat viewer + agent UI
8. [`modules/07_agent.md`](./modules/07_agent.md) — **Devin spec** — chat backend
9. [`modules/08_observability.md`](./modules/08_observability.md) — Logfire + Pydantic AI Gateway spend caps
10. [`modules/09_deployment.md`](./modules/09_deployment.md) — Render + Modal/Brev configs
11. ~~[`modules/10_kaggle.md`](./modules/10_kaggle.md)~~ — **archived**. Kaggle was the early-test path before Modal credits landed; the bundle/kernel artifacts were swept to `old/kaggle/` on 2026-04-25. Kept only as reference for offline-bundle patterns. Inference now ships exclusively on Modal (`plans/modules/09_deployment.md` + `inference/modal_app.py`).

## Owners
- **Harrish + Claude Code:** capture, inference, segmentation, object-isolation, observability, deployment glue.
- **Devin:** web + agent (entire user-facing layer).
- **Shared:** storage contract, schemas (must be agreed on hour 0).

## Key contracts (don't break these)
All modules read/write under `artifacts/scenes/<scene_id>/`. The schema is in [`modules/05_storage.md`](./modules/05_storage.md). Every module ships a stub output day 0 so the others can develop without waiting.

## Verified facts (April 2026)
- **SAM 3.1** (Meta, March 27 2026) — drop-in replacement for SAM 3, multi-object tracking, ~32 fps on H100.
- **VGGT** (CVPR 2025) — fastest SOTA for camera poses + dense point cloud, ~0.2s feed-forward.
- **3DGRUT** (NVIDIA) — handles non-pinhole cameras (Ray-Ban wide-angle).
- **Pydantic AI Gateway** — single SDK for OpenAI + Anthropic + Google + Bedrock + Groq, with Logfire tracing and spend caps.
