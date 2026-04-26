export type Vec3 = [number, number, number];
export type BBox = [Vec3, Vec3];

export interface Annotation {
  id: string;
  label: string;
  centroid: Vec3;
  bbox: BBox;
  color: string;
  confidence: number;
  alternatives?: string[];
  cluster_gaussian_indices?: number[];
}

export type StageStatus = "pending" | "running" | "complete" | "failed";
export type ManifestStatus = "queued" | "processing" | "ready" | "failed";

export interface Stage {
  status: StageStatus;
  duration_s?: number;
  method?: string;
  iterations?: number;
  object_count?: number;
  frame_count?: number;
  gaussian_count?: number;
}

export interface Manifest {
  scene_id: string;
  created_at: string;
  status: ManifestStatus;
  stages: {
    capture: Stage;
    poses: Stage;
    splat: Stage;
    segmentation: Stage;
  };
  artifacts?: {
    splat_ply?: string;
    annotations_json?: string;
    thumbnail_jpg?: string;
    cameras_json?: string;
  };
  stats: {
    frame_count: number;
    object_count: number;
    splat_size_mb: number;
  };
  errors?: string[];
}

export interface ChatMessage {
  id: string;
  role: "user" | "agent";
  text: string;
  pending?: boolean;
}

export type VlmModelId = "claude-haiku-4-5" | "claude-sonnet-4-6" | "claude-opus-4-7";

export interface JobSettings {
  fps: number;
  max_frames: number;
  target_long_side: number;
  segment: boolean;
  keyframes: number;
  vlm_model: VlmModelId;
}

export const VLM_MODEL_OPTIONS = [
  { id: "claude-haiku-4-5" as VlmModelId, label: "Haiku 4.5", cost: "$0.001" },
  { id: "claude-sonnet-4-6" as VlmModelId, label: "Sonnet 4.6", cost: "$0.003" },
  { id: "claude-opus-4-7" as VlmModelId, label: "Opus 4.7", cost: "$0.015" },
] as const;

export interface GatewayHealth {
  ok: boolean;
  gateway_url: string;
  key_fingerprint: string;
  probe_status: number | null;
  probe_detail: string | null;
  latency_ms: number;
}

export interface TraceTreeNode {
  span_id: string;
  parent_span_id: string | null;
  span_name: string;
  start_timestamp: string;
  end_timestamp: string;
  duration: number;
  trace_id: string;
  attributes: Record<string, unknown>;
  children: TraceTreeNode[];
}

export interface CostAggregate {
  total_usd: number;
  call_count: number;
  by_span?: Array<{
    span_name: string;
    usd: number;
    tokens_in: number;
    tokens_out: number;
  }>;
}

export interface TraceResponse {
  scene_id: string;
  span_count: number;
  tree: TraceTreeNode[];
  cost: CostAggregate;
}

export type UploadMode = "r2" | "local";
