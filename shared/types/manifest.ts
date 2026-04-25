// MIRROR OF shared/shared/schemas/manifest.py — keep in sync.
// Spec: plans/modules/05_storage.md.

export type StageStatus = "pending" | "running" | "complete" | "failed";
export type ManifestStatus = "queued" | "processing" | "ready" | "failed";

export interface Stage {
  status: StageStatus;
  duration_s?: number | null;
  // Stage-specific extras (poses.method, splat.iterations, segmentation.object_count, ...)
  [extra: string]: unknown;
}

export interface Stages {
  capture: Stage;
  poses: Stage;
  splat: Stage;
  segmentation: Stage;
}

export interface Artifacts {
  splat_ply: string;
  annotations_json: string;
  thumbnail_jpg: string;
  cameras_json: string;
}

export interface Stats {
  frame_count: number;
  object_count: number;
  splat_size_mb: number;
}

export interface Manifest {
  scene_id: string;
  created_at: string; // ISO-8601
  status: ManifestStatus;
  stages: Stages;
  artifacts: Artifacts;
  stats: Stats;
  errors: string[];
}
