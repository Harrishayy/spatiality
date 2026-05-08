# Spatiality — fast inference for 3D meshes

**Any short video pass → measurable, labelled, queryable 3D twin in under 250 seconds.**

Phone, GoPro, or smart glasses (Ray-Ban Gen 2 is a first-class capture path) feed a deployed Modal pipeline that produces a navigable Gaussian splat, per-object segmentation, and a chat agent that can locate, measure, and reason about anything in the scene.


---

## Why this exists

3D capture has stopped being a content pipeline and started becoming a *sensor* pipeline — the consumer is increasingly an agent, not a human in a viewer. The convergence of **VGGT** (March 2025, monocular metric depth + poses), **SAM 3.1** (gated Facebook video-segmentation release), and **Claude Haiku 4.5** (cheap, fast, multimodal) makes it possible — for the first time — to turn a casual walkthrough into a queryable spatial corpus in the time it takes to make coffee.

Spatiality is a working end-to-end system, not a notebook. Every stage is real, deployed, observable, and individually swappable.

---

## Use cases

**Robotics.** Geometry-grounded environments at the speed of iteration. Walk a room with any camera you already own and export a metric, mesh-ready 3D scene straight into Isaac Sim, Gazebo, Unity, or Unreal the same morning. Replaces $5k–$50k survey jobs and unblocks sim-to-real loops that used to wait days for a new asset.

**Augmented reality.** Anchor experiences to a physical space the day a venue is built — no scan crew, no scheduling. Reconstruct any room into a metric mesh you can drop into ARKit, ARCore, or Unity, with labelled object pins already attached.

**Virtual reality.** Stand up real-world locations in your engine in minutes. Author location-based VR — training sims, virtual tours, walkable archives — straight from on-site capture, with the file structure your engine expects.

**Emergency / human response.** First-on-scene situational awareness *before* the first responder. A walkthrough from any handheld or body-worn camera (smart glasses, GoPro, phone) delivers a measurable, labelled 3D mesh to incident command in under 250 seconds, and a chat agent that can answer "where's the gas shut-off?" or "how far from the entrance to the stairwell?" in real time.

---

## Tech stack

| Layer | What we use | Why |
|---|---|---|
| **Compute** | [Modal](https://modal.com) — H100 GPUs, persistent volumes, web endpoints | Serverless GPU with 30-min timeouts; one `modal deploy` ships the whole inference + segmentation surface |
| **Model gateway** | [Pydantic AI Gateway](https://ai.pydantic.dev/gateway/) (`gateway-eu.pydantic.dev`) | Every Claude call routes through it — enforced at startup. Bearer auth, not `apiKey` |
| **Observability** | [Logfire](https://logfire.pydantic.dev) (Pydantic) | Spans on every pipeline stage; Anthropic SDK auto-instrumented; live trace tail rendered in the viewer |
| **Schemas** | [Pydantic](https://docs.pydantic.dev) v2 (Python) + mirrored TypeScript interfaces | Manifest + annotations are the source of truth; `just check` round-trips every artifact through pydantic |
| **3D inference** | VGGT 1B (vanilla + FastVGGT token-merging fork) | Metric depth + camera poses from raw frames; 100-frame default, 700-frame FastVGGT path |
| **Segmentation** | Facebook SAM 3.1 (gated HF weights, CUDA kernels compiled into the Modal image) | Real per-object masks across keyframes |
| **VLM labelling** | Claude Haiku 4.5 via the Gateway | Fast, cheap multimodal labelling of segmented objects |
| **Agent** | [Hono](https://hono.dev) on Node 20, Claude Haiku 4.5 tool-use loop | Four tools: `locate_object`, `get_frames_for_object`, `move_camera_to`, `describe_scene` |
| **Web** | [Next.js 15](https://nextjs.org), three.js Points renderer, Tailwind | Splat + annotations + chat in one mobile-viewable page |
| **Hosting** | [Render](https://render.com) — `spatiality-agent` (Hono) + `spatiality-web` (Next.js), shared 10 GB persistent disk | Always-on services so the demo never cold-starts; mounted disk holds the `artifacts/` tree |
| **Object storage** | Cloudflare R2 — `spatiality` (uploads, presigned PUT) + `spatiality-artifacts` (public mirror) | Browser-direct splat fetches without paying egress |
| **Capture** | ffmpeg (pinhole, fisheye, Ray-Ban Gen 2 camera models) | Frame extraction at 4 fps default, 10 fps for FastVGGT |
| **Tooling** | `uv` (Python workspace), `pnpm` (TS workspace), `just` (top-level recipes), `bun` (locally) | One `uv sync` + `pnpm install` and you're running |

---

## Repo layout

```
capture/         # mp4 → frames (ffmpeg)
inference/       # frames → Gaussian splat (VGGT + per-pixel surfels). modal_app.py lives here.
segmentation/    # splat + frames → annotations (SAM 3.1 + Claude Haiku VLM)
shared/          # pydantic + TS schemas, Logfire wiring, Pydantic AI Gateway client
agent/           # Hono service on Render: capture intake, manifest polling, chat tool-use loop
web/             # Next.js viewer (splat + annotations + chat + Logfire trace tail)
artifacts/       # scenes/<scene_id>/{manifest.json, frames/, points.ply, splat.ply, annotations.json}
samples/         # bundled .mp4s for local testing
scripts/         # demo bake, gateway enforcement check, stub-scene generator
docs/            # DESIGN_SYSTEM.md and architecture notes
```

The **file contract** is hard: every artifact lives under `artifacts/scenes/<scene_id>/`, conforming to [`shared/shared/schemas/manifest.py`](shared/shared/schemas/manifest.py) and [`shared/shared/schemas/annotations.py`](shared/shared/schemas/annotations.py). No database. Manifests are the source of truth.

---

## Quickstart (local)

```bash
# 1. Install deps
uv sync
pnpm install

# 2. Copy env and fill in PYDANTIC_GATEWAY_KEY + LOGFIRE_TOKEN at minimum
cp .env.example .env

# 3. Smoke the whole stubbed pipeline end-to-end
just smoke
# → stub-scene → capture → infer → segment → check

# 4. Real pipeline against a sample video
just capture-real demo_v1 samples/capture.mp4 4.0
just infer-real demo_v1
just segment-real demo_v1 12

# 5. Web viewer + agent
pnpm --filter agent dev   # Hono on :8080
pnpm --filter web dev     # Next.js on :3000
```

Open <http://localhost:3000>, pick a scene, watch the splat render, click an object, ask the agent a question.

---

## Deployment (production)

```bash
# Inference + segmentation on Modal (first deploy ~25 min while SAM 3.1 weights compile in)
just modal-deploy

# Agent + web on Render (defined in render.yaml)
git push render main

# Trigger a real inference run against the deployed endpoint
just modal-inference demo_v1
just modal-inference-fast demo_v1   # FastVGGT, 700-frame budget
just modal-segment demo_v1 12
```

Render serves `spatiality-agent` (Hono) and `spatiality-web` (Next.js) on the **starter plan** to prevent sleep, with a shared 10 GB persistent disk mounted at `/var/data/artifacts`. R2 holds the public splat mirror so browsers fetch `splat.ply` directly without round-tripping through Render.

---

## Pipeline (representative wall-clock)

| Stage | Span | Time |
|---|---|---:|
| Capture | `capture.extract_frames` | 4.1s · 120 frames from a 30s video |
| Reconstruction | `inference.vggt` | 38.7s · 2.41M points on H100 |
| Compaction | `inference.compact_splat` | 6.3s · 48 MB splat.ply |
| Segmentation | `segmentation.sam3` + `segmentation.vlm_label` | 11.2s · 27 objects |
| **Total** | | **~60s** |

Every span lands in Logfire under the canonical names defined in [`shared/shared/observability.py`](shared/shared/observability.py). The viewer pulls the trace tail live via the Logfire Read API.

---

## License

Hackathon prototype. No license attached yet — get in touch before reusing.
