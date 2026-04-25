# Orchestrator plan — Glasses → 3D Twin

## North star
A user opens a URL on their phone, uploads a 30-second video from Meta Ray-Ban Gen 2 glasses, and within 5 minutes is walking through a 3D Gaussian splat of their space. While exploring it, they can ask a VLM in natural language ("where am I?", "what's that on the desk?") and get a real-time spatial answer based on their current view. Fine-grained object labels (e.g. "MacBook Air", "stack of books") are visible as floating annotations.

Two demo pillars:
1. **Fast inference** — capture-to-twin in under 5 minutes.
2. **In-twin VLM Q&A** — ask "where am I?" while navigating the splat; agent answers from your current viewpoint + position.

## Decisions (locked in)
- **Splat method:** 3DGRUT (NVIDIA, ray-tracing-based) — handles **any camera model** (pinhole phone video, Ray-Ban wide-angle, GoPro fisheye) via configurable projection. **Locked.**
- **Input source:** any mp4. Pipeline is camera-agnostic; `capture.yaml` records the camera type and inference picks the right 3DGRUT config. Demo uses Ray-Ban for narrative reasons, but a phone video uploaded by a judge would also work.
- **Pose + initial point cloud:** VGGT (~0.2s feed-forward) — replaces COLMAP for speed.
- **Segmentation:** two-pass — SAM 3.1 produces masks, then a VLM (Claude Haiku via Pydantic AI Gateway) names each region with fine-grained labels.
- **GPU:** Kaggle (RTX Pro 6000, offline-bundled) for early test runs → Modal or Brev for the production demo run.
- **Hosting:** Render hosts `/web` (static site) + `/agent` (web service). Inference is external.
- **Builders:** Harrish + Claude Code own pipeline modules. Devin owns `/web` + `/agent`.
- **Observability + cost:** Pydantic AI Gateway is the only model entry point. Logfire traces every call. Hard spend caps configured day 0.

## Module map

| # | Module | Owner | Inputs | Outputs |
|---|--------|-------|--------|---------|
| 1 | capture | Harrish + Claude | mp4 | frames/*.png, capture.yaml |
| 2 | inference | Harrish + Claude | frames/ | splat.ply, points.ply, cameras.json |
| 3 | segmentation | Harrish + Claude | splat.ply + frames | annotations.json |
| 4 | object-isolation (stretch) | Harrish | annotations.json + splat.ply | per-object viewer state |
| 5 | storage | Devin (interface), Harrish (impl) | (provides) | manifest.json, scene dir |
| 6 | web | **Devin** | manifest.json | mobile-viewable URL |
| 7 | agent | **Devin** | manifest.json + chat | tool-use responses |
| 8 | observability | Harrish | All model calls | Logfire dashboard, spend caps |
| 9 | deployment | Harrish | render.yaml, modal app | live URLs |

## Critical path (the chain that gates the demo)
```
upload → frames → VGGT poses + point cloud → 3DGRUT splat → splat in viewer
```

Total budget: **5 minutes**. Anything that branches off this chain (segmentation, fine-grained labels, agent chat, per-object isolation) enriches the demo but does not gate the moment the splat appears on the phone.

## Parallelization (3 workers)

```
Hour 0  ───────────────────────────────────────────────────────────
        Harrish+Claude          Devin
Hour 0  Repo + schemas          Repo + Render account
Hour 1  Logfire/Gateway setup   /web scaffold (against stub manifest)
Hour 2  Capture module          /agent scaffold (against fake annotations)
Hour 3  Kaggle inference test   Splat viewer wired up
Hour 4  Modal inference setup   Label overlays
Hour 5  VGGT integration        Chat panel + tool-use
Hour 6  Segmentation: SAM 3.1   Camera-fly animation
Hour 7  VLM labeling pass       Render deploy + mobile QA
Hour 8  E2E smoke               Polish
Hour 9  E2E w/ real video       Bug fix
Hour 10 Polish + 2nd scene      —
Hour 11 Buffer                  —
Hour 12-16 SLEEP                SLEEP
Hour 17-20 Demo capture         Final UX pass
Hour 21-23 Pitch deck + rehearse —
Hour 24 Pitch                   Pitch
```

## Stub strategy (everyone unblocks day 0)
Hour 0 deliverable: `modules/05_storage.md` finalized with manifest schema. Then:
- Devin builds against a fake `manifest.json` pointing at a known-good prebaked splat (`samples/test_scene.ply`) and hardcoded annotations.
- Pipeline modules build against the same fake input format on Harrish's side.
- Each module ships v0 with a stub generator that produces valid output. Real implementation drops in v1.

This means the web layer can be deployed and demo-ready by hour 8 even if the real inference pipeline isn't wired up yet.

## Failure mitigations

| Failure | Mitigation |
|---------|------------|
| 3DGRUT won't compile in time | Vanilla 3DGS via Splatfacto on Modal — pipeline still works, loses Ray-Ban-specific quality |
| SAM 3.1 wrong env / too slow | SAM 2 + Grounding DINO + VLM — fewer concepts but proven |
| VGGT poses bad on Ray-Ban footage | COLMAP via `ns-process-data` — adds 1–2 min to pipeline |
| Modal/Brev credits exhausted | Kaggle for the demo run — slower but free |
| Render free tier sleeps mid-demo | Cron pinger every 10 min, or upgrade to Starter ($7/mo) |
| Segmentation produces nonsense | Hand-curate annotations.json for the hero scene before the demo |
| Live capture fails on stage | Pre-recorded fallback scene already in `samples/` and pre-processed |

## Cost & observability
- **All model calls go through Pydantic AI Gateway** — single SDK + key + spend dashboard.
- **Spend caps:** $5 hard cap on AI Gateway (covers VLM + agent chat). $30 budget on Modal/Brev for inference compute. Configured before any traffic.
- **Logfire project:** auto-traces every Gateway call. Spans tagged by module name.
- **Mubit credits:** verify scope before hour 0 — if they cover Modal/Brev or general LLM spend, route the spend cap accordingly.

See [`modules/08_observability.md`](./modules/08_observability.md) for setup steps.

## Demo script (4 minutes on stage — pre-baked inference, log-cited)

We do **not** run inference live on stage. Inference takes 5–10 minutes and is the wrong thing to gamble on. Instead: we pre-bake the demo scene before the pitch, show capture → handoff → finished twin, and use Logfire as the evidence layer for the inference that already happened. This is lower-risk and more credible because the audience sees verifiable timings, not a progress bar that could stall.

| Time | Beat |
|------|------|
| 0:00–0:15 | **Hook + live capture (the start of the process):** "Watch — I'm going to walk through my room with these glasses, and end up with a queryable 3D twin of it on my phone." Live-record 30s. |
| 0:15–0:45 | **Upload + verbal handoff:** Open URL on phone, upload the clip. "Inference takes 5–10 minutes — pose estimation, splat training, segmentation. You'll see receipts in a moment." Show upload completing, then transition. |
| 0:45–1:15 | **The finished twin (pre-baked, the end of the process):** Open the pre-built scene URL. Drag, orbit. **Hero moment:** tap "where am I?" → VLM responds. Move camera. Ask again. Different answer. |
| 1:15–2:00 | **Two more interactions:** spatial chat query ("what's the laptop model?"), then a flyby ("show me the mug"). Optional: tap-to-isolate one object. |
| 2:00–2:45 | **Evidence (the Logfire moment):** Flip to the Logfire trace view filtered to the demo scene. "Here's what actually ran. Capture 8 seconds. VGGT poses 1.2 seconds. 3DGRUT splat 6 minutes 20. SAM 3.1 segmentation 52 seconds. VLM labeling 26 seconds. Every spatial query you just saw cost about $0.001, traced and spend-capped." Point to the waterfall. |
| 2:45–3:30 | **Why this matters (Mubit hook):** tailor to Mubit's domain. The substance is: same pipeline runs on any video, any camera; no specialized hardware; mobile-viewable; observable; cost-bounded. |
| 3:30–4:00 | **Where this goes:** "Today's run was ~7 minutes. With warm Modal containers and tighter 3DGRUT iteration count, we have a path to under 90 seconds. The architecture's ready — what you saw is the v0." |

## Pre-demo bake (T-30 minutes)
- Run the full pipeline on the chosen demo scene end-to-end.
- Verify the trace appears in Logfire and looks clean (no warnings, no error spans).
- Save a Logfire view filtered to `scene_id == demo_scene_v1`. Bookmark that URL — it's the "evidence tab".
- Open the finished twin URL on the demo phone, confirm splat loads + "where am I?" works.
- Have a backup pre-recorded video of the capture portion in case live capture fails.

## Open questions (resolve before hour 0)
- What is Mubit's actual product / domain? The pitch's last 30s should hook into their world.
- Should we pre-record a backup demo video in case live capture fails on stage?
- Are there specific objects you want pre-tested for fine-grained labeling (e.g. specific MacBook model, specific book titles)?
- Do Mubit's $8k credits apply to Modal/Brev compute, to LLM spend, or to a specific provider?
