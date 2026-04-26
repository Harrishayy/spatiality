// MIRROR OF shared/shared/schemas/capture.py — keep in sync.

export type CameraModel = "pinhole" | "meta_rayban_gen2" | "fisheye" | "generic";

export interface CaptureYaml {
  scene_id: string;
  source_video: string;
  duration_s: number;
  fps: number;
  frame_count: number;
  resolution: [number, number];
  camera_model: CameraModel;
  fov_deg?: number | null;
  captured_at: string; // ISO-8601
}
