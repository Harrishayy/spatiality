# Module 04 — Object isolation (stretch)

## Goal
Let the user tap an object in the viewer and see it on its own — either by hiding the rest of the splat, or eventually by training a high-quality per-object splat.

## Two paths

### Path A — Cluster isolation (cheap, ship this)
- Each annotation in `annotations.json` already includes `cluster_gaussian_indices`.
- The viewer maintains a "visible cluster" set; tapping an annotation toggles to that cluster only.
- Hidden Gaussians get `opacity = 0` (or filtered before passing to the renderer).
- Optional: animate the alpha fade for a clean visual handoff.

**Difficulty:** trivial. ~50 lines in the viewer's render loop.
**Demo value:** strong — tap MacBook Air, the rest of the room fades out, you orbit just the laptop.

### Path B — Per-object splat training (skip unless miracle)
- Take all frames where object X is detected, crop each to its bbox, retrain a small splat just on those crops.
- Output: a separate, denser `splat_<obj_id>.ply` with much higher per-object detail.
- **Why hard:** a single walk-through rarely gives enough parallax around any one object. Single-object splats need orbiting around it specifically. The Ray-Ban capture is a room walkthrough, not a per-object orbit.
- **Verdict:** skip for v1. Mention in the pitch as "next step."

## Path A acceptance criteria
- Tapping a label hides all other clusters within 200ms.
- Tapping the same label again restores full scene.
- Tapping a different label transitions cleanly without flicker.
- Works on iPhone Safari.

## File contract
This module is implemented entirely in `/web` — it doesn't write any new artifacts. It reads `annotations.json` and uses the `cluster_gaussian_indices` field already present.

## Owner
Lands as part of `/web` polish phase. See [`06_web.md`](./06_web.md).
