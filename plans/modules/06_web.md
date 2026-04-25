# Module 06 — Web (Devin spec)

## Owner
**Devin — primary builder, end-to-end.** Read this as a Linear ticket.

## Goal
A mobile-viewable URL where users (a) upload a video, (b) watch the pipeline run, and (c) navigate the resulting 3D twin while asking a VLM real-time spatial questions about their viewpoint.

## User flow
1. User opens URL on phone.
2. Tap "Upload video" → picks an `.mp4`.
3. Pipeline progress streams in: capture → poses → splat → annotations.
4. Once `manifest.status === "ready"`, splat viewer loads.
5. User drags to orbit, pinches to zoom, taps annotations to highlight.
6. **HERO INTERACTION:** taps "Where am I?" or types in chat → VLM answers based on current viewport + position + nearby objects.
7. Optional: voice input via mic icon.

## Tech stack
- **Vite + React 18 + TypeScript**
- **Splat rendering:** [`@mkkellogg/gaussian-splats-3d`](https://www.npmjs.com/package/@mkkellogg/gaussian-splats-3d) — verify latest version on npm before wiring.
- **3D math:** Three.js (transitive dep).
- **State / data:** TanStack Query for polling `manifest.json`; Zustand for camera state.
- **Styling:** TailwindCSS.
- **No backend SDK on client** — all model calls go through `/agent`.

## File structure (target)
```
web/
  src/
    App.tsx
    main.tsx
    components/
      Uploader.tsx
      PipelineProgress.tsx
      SplatViewer.tsx
      AnnotationOverlay.tsx
      ChatPanel.tsx
      WhereAmIButton.tsx
      VoiceInput.tsx          (stretch)
    hooks/
      useScene.ts              (polls /api/jobs/:id)
      useChat.ts               (manages chat state + posts to /api/agent/*)
      useCameraSnapshot.ts     (capture canvas + camera state)
    lib/
      api.ts
      types.ts                 (mirror of manifest + annotations schema)
      cameraMath.ts            (frustum culling for nearby objects)
    styles/
      globals.css
  index.html
  vite.config.ts
  tsconfig.json
  package.json
```

## Components — detailed specs

### `SplatViewer.tsx`
- Wraps `GaussianSplats3D.Viewer`.
- Props: `splatUrl: string`, `annotations: Annotation[]`, `onCameraChange: (state) => void`.
- Mounts a div, instantiates the viewer, loads the splat from `splatUrl`.
- Exposes `cameraRef` so other components can `getWorldPosition()` and `getWorldDirection()`.
- Re-emits camera state on every `OrbitControls` change event.

### `AnnotationOverlay.tsx`
- Renders 3D-anchored billboard labels at each annotation's `centroid`.
- Uses Three.js `Sprite` or HTML overlay with reprojected coords.
- Tap label → emits `onLabelTap(annotation)` (used by isolation feature, see [`04_object_isolation.md`](./04_object_isolation.md)).
- Labels fade based on distance + camera angle (don't show if behind camera).

### `WhereAmIButton.tsx` — the hero interaction
- Floating button, bottom-center on mobile, bottom-right on desktop.
- onTap:
  ```ts
  const canvas = viewerRef.current.renderer.domElement;
  const imageB64 = canvas.toDataURL("image/jpeg", 0.8);
  const cameraPos = viewerRef.current.camera.getWorldPosition();
  const cameraDir = viewerRef.current.camera.getWorldDirection();
  const nearbyAnnotations = filterByFrustum(annotations, cameraPos, cameraDir);

  const response = await api.locate({
    scene_id, image_b64: imageB64,
    camera_pos: cameraPos.toArray(),
    camera_dir: cameraDir.toArray(),
    nearby: nearbyAnnotations.map(a => ({id: a.id, label: a.label, centroid: a.centroid}))
  });

  chatStore.appendAgent(response.text);
  ```
- Show inline thinking indicator on the button while waiting.

### `ChatPanel.tsx`
- Bottom drawer on mobile, right sidebar on desktop (Tailwind responsive).
- Displays messages (user + agent).
- Text input + send button.
- Mic button (voice input — stretch).
- Each user message implicitly tagged with current camera position so the agent has context.

### `Uploader.tsx`
- Standard drag-and-drop or `<input type="file" accept="video/*">`.
- POSTs to `/api/upload` (multipart).
- Shows progress.
- On success, transitions to `PipelineProgress` view.

### `PipelineProgress.tsx`
- Polls `/api/jobs/:id` every 2s via TanStack Query.
- Renders each stage from `manifest.stages` as a checklist with timing.
- Animates transitions.
- When `status === "ready"`, transitions to viewer.

## Acceptance criteria
- Loads on iPhone Safari with no console errors.
- Splat renders ≥30fps on iPhone 13 / Pixel 7 or newer.
- "Where am I?" round-trip ≤3s end-to-end (image capture → API → VLM → render).
- Upload supports files up to 200MB.
- All state recovers if user refreshes mid-job (scene_id in URL).
- Lighthouse mobile score ≥80.

## Out of scope (do not build)
- User accounts / login.
- Multi-scene library / dashboard.
- Editing tools (move/rotate/recolor).
- Sharing or export buttons.
- A native iOS / Android app.

## Stretch (only after base is solid)
1. Voice input via browser SpeechRecognition + TTS reply.
2. Tap-to-isolate (Path A in [`04_object_isolation.md`](./04_object_isolation.md)).
3. Continuous narration as camera moves (throttled).
4. PWA manifest so user can "add to home screen".

## API contract (talks to `/agent`)
- `POST /api/upload` (multipart, returns `{scene_id}`)
- `GET /api/jobs/:scene_id` (returns `manifest.json`)
- `POST /api/agent/locate` (body: `{scene_id, image_b64, camera_pos, camera_dir, nearby[]}`, returns `{text, latency_ms}`)
- `POST /api/agent/chat` (body: `{scene_id, message, camera_pos}`, returns `{text, tool_calls?}`)
- `GET /artifacts/...` (static files from agent's persistent disk)

See [`07_agent.md`](./07_agent.md) for backend contract.

## Done criteria for this ticket
- Deployed to Render static site at a stable URL.
- Test scene loads end-to-end on a phone.
- "Where am I?" works against the agent backend.
- Mobile-responsive QA passes on at least one iPhone.
