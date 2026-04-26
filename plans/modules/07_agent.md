# Module 07 — Agent backend

## Owner
Harrish + Claude Code, end-to-end.

## Goal
Fastify server with three responsibilities: orchestrate the pipeline (Modal trigger + status), serve scene artifacts, and proxy chat/VLM calls to Claude through Pydantic AI Gateway with Logfire tracing.

## Routes

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/upload` | Accept mp4, write to disk, kick off pipeline. Return `{scene_id}` |
| `GET`  | `/api/jobs/:scene_id` | Return current `manifest.json` |
| `POST` | `/api/agent/chat` | General chat with annotations injected as context |
| `POST` | `/api/agent/locate` | "Where am I?" — image + camera state + nearby objects |
| `GET`  | `/artifacts/*` | Static files (splat.ply, annotations.json, thumbnails) |

## Stack
- **Node 20 + Fastify + TypeScript**
- **Anthropic SDK** (`@anthropic-ai/sdk`) configured to use Pydantic AI Gateway base URL
- **Modal SDK** (Python? — see decision below)
- **Persistent disk** for `/artifacts/`

### Decision: Modal trigger from Node
Modal's primary SDK is Python. Three options:
1. **Spawn Python subprocess** that calls `modal run` — simple, brittle.
2. **Modal Web Endpoints** — Modal can expose any function as an HTTP endpoint. Recommended: deploy `inference.run` as a web endpoint, call it from Fastify with `fetch`.
3. **Tiny Python sidecar** on Render — extra service, more moving parts.

**Pick option 2.** Modal web endpoints are first-class.

## Pydantic AI Gateway integration
- All Claude calls go through Pydantic AI Gateway. Base URL for Anthropic-direct routing:
  - EU: `https://gateway-eu.pydantic.dev/proxy/anthropic/`
  - US: `https://gateway-us.pydantic.dev/proxy/anthropic/`
- Auth: Bearer token (`pylf_v...`) — the Logfire project token doubles as Gateway auth.
- The Anthropic SDK uses `authToken` (Bearer auth), NOT `apiKey` (which sends `x-api-key`). Confusing this is the most common Pydantic Gateway integration bug.
- Spend cap enforced at the Gateway level (configured in Logfire dashboard, not in code).
- Anthropic SDK instantiation:
  ```ts
  import Anthropic from '@anthropic-ai/sdk';

  const anthropic = new Anthropic({
    baseURL: process.env.PYDANTIC_GATEWAY_URL, // https://gateway-eu.pydantic.dev/proxy/anthropic/
    authToken: process.env.PYDANTIC_GATEWAY_KEY, // pylf_v...
  });
  ```
- Verify wiring with a smoke test before any feature work:
  ```ts
  const r = await anthropic.messages.create({
    model: 'claude-haiku-4-5',
    max_tokens: 32,
    messages: [{ role: 'user', content: 'ping' }],
  });
  console.log(r.content);
  ```
- Confirm the call shows up in Logfire's AI Gateway dashboard. If it doesn't trace within ~30s, your auth token is wrong (most likely cause) or the base URL is missing the trailing slash.

## `/api/agent/locate` — the hero interaction

**Input:**
```json
{
  "scene_id": "bedroom_v1",
  "image_b64": "...",
  "camera_pos": [0.5, 1.2, -1.8],
  "camera_dir": [0.0, -0.1, -0.99],
  "nearby": [
    {"id": "obj_001", "label": "MacBook Air (M3)", "centroid": [0.42, 0.91, -1.23]},
    {"id": "obj_002", "label": "stack of books",   "centroid": [-0.31, 0.88, -1.50]}
  ]
}
```

**Logic:**
1. Load full `annotations.json` for scene.
2. (Optional re-filter) intersect `nearby` with frustum + 5m distance.
3. Build prompt:
   > System: "You're an assistant that knows the user is exploring a 3D Gaussian splat of their room. Given their current camera position, looking direction, the labeled objects in their view, and a screenshot of what they see, tell them where they are and what's around them. Be concrete and grounded — name specific objects from the list."
   >
   > User content: `[image, "I'm at position (x,y,z) looking along (dx,dy,dz). Objects in my view: <labels>. Where am I and what's around me?"]`
4. Call `claude-haiku-4-5` (vision-capable, cheap) via Gateway.
5. Return `{text, latency_ms, cost_usd}`.

**Latency target:** ≤3s p95.
**Cost target:** ≤$0.001/call.

## `/api/agent/chat`

General chat. Tool-use enabled with these tools:

```ts
const tools = [
  {
    name: "locate_object",
    description: "Highlight an object in the viewer by its label",
    input_schema: { type: "object", properties: { label: { type: "string" }}, required: ["label"] }
  },
  {
    name: "move_camera_to",
    description: "Tween the user's camera to look at an object",
    input_schema: { type: "object", properties: { label: { type: "string" }}, required: ["label"] }
  },
  {
    name: "describe_scene",
    description: "Get a text summary of all objects in the scene",
    input_schema: { type: "object", properties: {} }
  }
];
```

The web client receives tool_use blocks and executes them locally (locate_object highlights the matching cluster, move_camera_to tweens, etc).

## `/api/upload`
1. Receive multipart upload, validate (max 200MB, video/* mime).
2. Generate `scene_id` (slug + short hash).
3. Write to `artifacts/scenes/<scene_id>/source.mp4`.
4. Spawn capture: extract frames → write `frames/` and `capture.yaml`.
5. Write initial `manifest.json` with `status: "queued"`.
6. Trigger Modal web endpoint `POST /run-inference` with `{scene_id}`.
7. Return `{scene_id}` immediately (don't block on Modal).

The Modal job will write to the same persistent disk via Modal Volume sync (configured in [`09_deployment.md`](./09_deployment.md)).

## Cost guards
- **Hard limit at Gateway level:** $5 across all model calls. Configured in Logfire dashboard.
- **Per-IP rate limit:** 10 requests/min on `/api/agent/*`.
- **Image quality cap:** require client to send JPEG q=0.8 max 1024px wide. Reject bigger.

## Logfire integration
- `logfire.configure(token=...)` at boot.
- Every route wrapped in `logfire.span("route_name", scene_id=...)`.
- Anthropic calls auto-instrumented via Pydantic AI Gateway — appears in Logfire automatically.

## Acceptance criteria
- `/api/agent/locate` p95 ≤3s.
- `/api/upload` returns within 500ms (job runs async).
- All errors return `{error: string, code: string}` with proper status codes.
- Logfire dashboard shows traces for every model call within 5s.
- Spend cap blocks calls past $5 (verify by simulating in dev).

## Done criteria for this ticket
- Deployed to Render web service at a stable URL.
- All routes return correctly against the test scene.
- Spend tracking visible in Logfire.
- `web/` can talk to `agent/` end-to-end without CORS issues.
