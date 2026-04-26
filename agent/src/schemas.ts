import { z } from "zod";

// Allowed VLM models routed through Pydantic AI Gateway. This is the
// closed-list backend twin of VLM_MODEL_OPTIONS in web/app/lib/types.ts;
// keep the two in sync. Adding a new model is a one-line change here +
// the matching ID in shared.gateway → Modal env (VLM_MODEL=<id>).
export const VlmModelId = z.enum([
  "claude-haiku-4-5",
  "claude-sonnet-4-6",
  "claude-opus-4-7",
]);
export type VlmModelId = z.infer<typeof VlmModelId>;

// Scene IDs flow into R2 keys (`scenes/<id>/...`), Modal querystrings, and
// Logfire SQL. Lock the charset to ULID/path-safe characters so a malicious
// caller can't path-traverse or break out of a quoted SQL literal.
export const SceneIdSchema = z
  .string()
  .min(1)
  .max(64)
  .regex(/^[A-Za-z0-9_-]+$/, "scene_id must be [A-Za-z0-9_-]{1,64}");
export const SCENE_ID_RE = /^[A-Za-z0-9_-]{1,64}$/;

export const Settings = z.object({
  fps: z.number().min(0.5).max(10).default(2.0),
  max_frames: z.number().int().min(10).max(800).default(400),
  target_long_side: z.number().int().min(480).max(3840).default(1920),
  segment: z.boolean().default(true),
  keyframes: z.number().int().min(2).max(30).default(5),
  vlm_model: VlmModelId.optional(),
});
export type Settings = z.infer<typeof Settings>;

export const InitUploadBody = z.object({
  filename: z.string().min(1).max(256),
  content_type: z.string().min(3).max(128),
  size_bytes: z.number().int().min(1).max(2_000_000_000),
});
export type InitUploadBody = z.infer<typeof InitUploadBody>;

export const SubmitJobBody = z.discriminatedUnion("mode", [
  z.object({
    mode: z.literal("r2"),
    scene_id: SceneIdSchema,
    r2_key: z.string().min(1),
    settings: Settings,
  }),
  z.object({
    mode: z.literal("local"),
    scene_id: SceneIdSchema,
    modal_path: z.string().min(1),
    settings: Settings,
  }),
]);
export type SubmitJobBody = z.infer<typeof SubmitJobBody>;
