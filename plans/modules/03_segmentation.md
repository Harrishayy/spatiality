# Module 03 — Segmentation + annotation

## Goal
Take the splat + frames and produce `annotations.json` listing every recognized object with a fine-grained label, 3D position, bbox, and the Gaussian indices it owns.

## Inputs
- `splat.ply`, `points.ply`, `cameras.json` (from `/inference`)
- `frames/` (rendered or raw input frames)

## Outputs
- `annotations.json` (schema in [`05_storage.md`](./05_storage.md))

## Approach: two-pass — SAM 3.1 for masks, VLM for fine labels

This beats one-pass options for two reasons: (1) SAM 3.1 handles "what region" robustly without needing a list of expected objects; (2) the VLM step gives us "MacBook Air" instead of "laptop", which is the demo value-add.

### Pass 1 — SAM 3.1 mask generation
- Pick **4–6 keyframes** evenly distributed by camera angle (read from `cameras.json`).
- Run SAM 3.1 in **automatic mask mode** per keyframe (`mask_generator.generate(image)`).
- Each keyframe yields N 2D masks → set of (frame_id, mask_id, polygon, confidence).

### Pass 2 — Lift 2D masks to 3D Gaussian clusters
- For each 2D mask, project the splat's Gaussians into that camera and find Gaussians whose projection falls inside the mask polygon.
- Cross-reference Gaussians appearing inside masks across multiple frames — these belong to the same 3D object.
- Cluster Gaussian indices by mask co-occurrence. Fall back to **DBSCAN on Gaussian centers** if mask lifting is too noisy.

### Pass 3 — VLM fine-grained labeling
- For each 3D cluster, find the keyframe where its mask had largest area, render a tight crop with that mask's bbox.
- Send crop to **Claude Haiku via Pydantic AI Gateway** with prompt:
  > "Identify this object precisely. Use specific names where visible (model number, brand). Otherwise use a descriptive phrase. Reply JSON: `{label, confidence, alternatives}`"
- Cache by cluster id (idempotent reruns).
- **Batch:** send 4–6 crops per VLM call to cut cost; tile them in a grid image with cluster IDs visible, ask for JSON keyed by ID.

### Pass 4 — Emit `annotations.json`
For each cluster: `{id, label, centroid, bbox, color, confidence, cluster_gaussian_indices}`.

## Tech
- **Segmentation:** SAM 3.1 ([`facebookresearch/sam3`](https://github.com/facebookresearch/sam3)) — auto mask gen.
- **VLM:** Claude Haiku via Pydantic AI Gateway. Single SDK, automatic Logfire trace, hard spend cap.
- **Mask lifting:** custom Python using Gaussian centers + camera matrices from `cameras.json`. ~80 lines.
- **Compute:** Modal A100 (same image as `/inference`).

## CLI
```
python segmentation/run.py --scene <scene_id> [--keyframes 5]
```

## Implementation steps
1. **Hour 0:** stub `segmentation/run.py` that emits 5 fake objects in plausible 3D positions. Unblocks the web layer's work.
2. **Hour 5:** wire SAM 3.1 mask gen on a single keyframe; verify masks look right.
3. **Hour 5.5:** mask-to-Gaussian lifting on the test scene.
4. **Hour 6:** VLM batch labeling pipeline.
5. **Hour 6.5:** end-to-end on the real test scene; eyeball label quality.
6. **Hour 7:** swap stub for real impl in production.

## Acceptance criteria
- 5–8 distinct objects identified per typical room scene.
- ≥80% labels match human-judged ground truth on the hero scene (manually verified).
- Total wall clock: ≤90s on Modal A100.
- VLM cost: ≤$0.10 per scene (batched calls).

## Failure paths
- **SAM 3.1 not installable:** fall back to SAM 2 + Grounding DINO + VLM. Loses concept-aware segmentation but still produces masks.
- **Mask-to-3D lifting noisy:** DBSCAN on Gaussian centers as a coarse fallback.
- **VLM hallucinates specific brands:** add `confidence < 0.7` → use the generic alternative.

## Stretch
- **Concept-prompted SAM 3.1:** instead of automatic masks, feed it a curated concept list per scene type (room, kitchen, office). Higher precision.
- **VLM also writes a one-line description** per object for the agent's spatial-query context ("MacBook Air, lid open, screen showing terminal").
