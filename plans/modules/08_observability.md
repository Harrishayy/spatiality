# Module 08 — Observability + cost guards

## Goal
Every model call traced. Spend hard-capped before any traffic. Two dashboards we monitor: Logfire (model calls) and Modal/Brev (GPU time).

## Why this is hour-0 work
Spend caps must exist *before* any traffic hits the Gateway. A stray loop or a misconfigured client can burn $50 in five minutes if uncapped.

## Setup steps (~30 min, hour 0)

### Pydantic Logfire + AI Gateway
1. Sign in at [logfire.pydantic.dev](https://logfire.pydantic.dev) with the team plan account.
2. Create a project: `glasses-twin-hackathon`. Pick **EU region** (London latency).
3. Open the AI Gateway tab → create a gateway. Add provider keys:
   - Anthropic (your existing key)
   - Optionally Google (for Gemini Flash as a backup VLM)
4. Generate a **Gateway auth token** for this project — format `pylf_v...`. Save as `PYDANTIC_GATEWAY_KEY`.
5. Gateway base URLs (confirmed format):
   - For Anthropic-direct routing: `https://gateway-eu.pydantic.dev/proxy/anthropic/`
   - For Pydantic AI framework: `https://gateway-eu.pydantic.dev/proxy`
   - Swap `-eu` → `-us` if you switched region.
6. **Set spend caps** in the gateway settings:
   - **Hard cap:** $5 total. Beyond this, all requests are rejected.
   - **Soft alert:** $2. Webhook or email notification.
7. Enable tracing — every Gateway call auto-emits a Logfire span.

### Logfire token in the agent service
- Add to Render env vars on the `/agent` service:
  - `PYDANTIC_GATEWAY_URL` — `https://gateway-eu.pydantic.dev/proxy/anthropic/`
  - `PYDANTIC_GATEWAY_KEY` — `pylf_v...`
  - `LOGFIRE_TOKEN` — same `pylf_v...` (Logfire token doubles as Gateway auth)
- Install: `pnpm add @pydantic/logfire-node @pydantic/logfire-api`
- In `agent/src/instrumentation.ts` (must run before any other imports):
  ```ts
  import { configure } from '@pydantic/logfire-node';
  configure({ token: process.env.LOGFIRE_TOKEN });
  ```
- In `agent/src/index.ts`:
  ```ts
  import './instrumentation';   // first import, before fastify
  import Fastify from 'fastify';
  // ...
  ```
- The `@pydantic/logfire-node` package wraps OpenTelemetry's auto-instrumentations, so Fastify routes, fetch calls, and Anthropic SDK calls are traced without further code.

## Code patterns

### Wrap every route in a span
```ts
fastify.post('/api/agent/locate', async (req, res) => {
  return logfire.span('agent.locate', { scene_id: req.body.scene_id }, async () => {
    // ... handler
  });
});
```

### Anthropic calls auto-traced
Because Anthropic SDK is configured with Gateway base URL, every call shows up in Logfire automatically with model, prompt tokens, completion tokens, cost, latency.

### Tag pipeline stages
Inference and segmentation also emit spans (Python side):
```python
import logfire
logfire.configure(token=os.environ["LOGFIRE_TOKEN"])

with logfire.span("inference.train", scene_id=scene_id):
    # ...
```

## What to monitor
- **Real-time spend** — Logfire AI Gateway dashboard.
- **p50 / p95 / p99 latency** for `/api/agent/locate` (target p95 ≤ 3s).
- **Error rate** — anything ≥1% during demo means investigate before going on stage.
- **Tokens per request** — unexpected spikes mean prompt regression or image too large.

## Modal / Brev cost tracking (separate)
- **Modal:** dashboard at `modal.com/apps/<your-app>` shows GPU-hours.
- **Budget:** $30 across all dev runs. Set Modal billing alert at $20.
- **Daily checkpoint:** at hours 6, 12, 18 — read the dashboard, cross-check against expectations.

## Mubit credits
- **Action item:** clarify what Mubit's $8k credits cover *before hour 0*.
- If they cover Modal/Brev compute → route inference billing through them, raise the cap.
- If they cover LLM spend → use the credit-bearing API key as the Gateway provider key.
- If neither → use your own keys, keep caps tight.

## Acceptance criteria
- Logfire dashboard shows live traces within 30s of any model call.
- Spend cap rejects a synthetic over-budget request in dev (verify before opening to traffic).
- Modal cost dashboard accurate and bookmarked.
- Daily-summary script exists (or just the dashboards are bookmarked) for quick checks.

## Failure paths
- **Logfire down:** model calls still work; traces missing temporarily. Acceptable for normal ops, **disastrous for the demo** because Logfire IS the evidence layer. See "Demo evidence playbook" below for fallback.
- **Gateway down:** all model calls fail. Mitigation: have a kill switch in `/agent` that swaps `baseURL` back to direct Anthropic for the demo only. (Loses spend cap protection — only flip during the actual demo if Gateway is broken.)

## Demo evidence playbook

The demo cites Logfire as proof of inference timing. The audience sees the trace waterfall, not a live progress bar. This requires up-front instrumentation discipline.

### Spans to instrument (the audience will see these)
Pipeline modules must emit these named spans with metadata:

| Span name | Module | Required attrs |
|-----------|--------|----------------|
| `capture.extract_frames` | capture | `scene_id`, `frame_count`, `source_camera` |
| `inference.vggt` | inference | `scene_id`, `frame_count`, `gpu` |
| `inference.splat` | inference | `scene_id`, `gpu`, `gaussian_count` |
| `segmentation.sam3` | segmentation | `scene_id`, `keyframe_count`, `mask_count` |
| `segmentation.vlm_label` | segmentation | `scene_id`, `cluster_count` (cost auto-attached) |
| `agent.locate` | agent | `scene_id` (cost auto-attached) |

VLM evidence is also captured at the call-site spans, so the website can read
the actual model output without re-running inference:

| Span name | Module | Payload attrs |
|-----------|--------|---------------|
| `segmentation.vlm_proposal.frame` | proposer | `vlm_response_raw` (full text), `vlm_proposals` (parsed phrases + bboxes), `latency_ms`, `input_tokens`, `output_tokens`, `est_cost_usd`, `model_response_id`, `stop_reason` |
| `segmentation.vlm_proposal.summary` | proposer | `proposals` (every phrase across keyframes), `proposal_count_total`, `proposal_count_per_frame` |
| `segmentation.vlm_label.batch` | vlm | `vlm_response_raw`, `vlm_labels` (per-cluster label + confidence + alternatives), `tile_hints`, `latency_ms`, `input_tokens`, `output_tokens`, `est_cost_usd`, `model_response_id`, `stop_reason` |
| `segmentation.vlm_label.summary` | vlm | `labels` (final per-cluster label map), `kept_count`, `rejected_none_count`, `dropped_duplicate_count` |

Modal-side wrapper spans cover the wall-clock for each web endpoint plus the
volume reload/commit + subprocess overhead that lives outside the named
pipeline spans:

| Span name | Module | Attrs |
|-----------|--------|-------|
| `modal.process_video` | modal_app | `scene_id`, `source_kind`, `frame_count`, `video_duration_s`, `video_width`, `video_height`, `backend`, `inference_spawned` |
| `modal.run_inference` | modal_app | `scene_id`, `backend`, `keyframes`, `segment`, `segmentation_spawned` |
| `modal.run_segmentation` | modal_app | `scene_id`, `keyframes` |
| `modal.prepare_scene` | modal_app | `scene_id`, `manifest_state` |
| `modal.subprocess.<stage>` | modal_app | `scene_id`, `stage`, `argv`, `returncode`, `stdout_tail`, `stderr_tail` (on failure) |
| `modal.ffprobe`, `modal.ffmpeg_extract` | modal_app | `scene_id`, ffprobe/ffmpeg facts |

The `inference.splat` span is a single voxel-downsample of the surfels
emitted by `inference.vggt`; no per-step milestones are needed since
there's no iterative training. The `gaussian_count` attribute on the span
is the proof point — visible in the waterfall metadata.

### Pre-demo bake
1. Run the full pipeline on the chosen scene end-to-end.
2. Open Logfire → filter `scene_id == "demo_scene_v1"`.
3. Confirm the waterfall shows all 6 spans, no error spans, no warnings.
4. Save the filter as a named view.
5. Bookmark the view URL. **This is your evidence tab.**

### Demo-day setup
- Browser tab 1: the finished twin URL (the `/web` page).
- Browser tab 2: the Logfire saved view (the evidence tab).
- Browser tab 3: pre-recorded backup capture video (in case live record fails).
- Phone: same `/web` URL bookmarked, tested.

### Fallback if Logfire is broken on demo day
- Pre-export the trace JSON from a successful pipeline run during pre-demo bake.
- Render it as a static HTML waterfall ahead of time (a few minutes of work — just a styled `<table>` with timing).
- Host the static HTML at a stable URL on Render.
- If Logfire is unreachable on stage, point to the static evidence page instead.

This gives you a verifiable timing story even in a Logfire outage.

### What audience-grade trace metadata looks like
Bad (low information density):
```
inference.splat    1.2s
```

Good (specific, demo-worthy):
```
inference.splat    1.2s   scene_id=demo_scene_v1, gpu=A100-80GB, gaussian_count=1_120_345
```

The metadata is what makes a 30-second screenshot of the dashboard convincing.
