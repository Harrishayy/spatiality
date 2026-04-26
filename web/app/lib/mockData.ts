// Default fixtures used until /agent is wired (or NEXT_PUBLIC_AGENT_URL is set).
// Mirrors artifacts/scenes/test_scene_v0/.

import type { Annotation, Manifest } from "./types";

export const DEMO_SCENE_ID = "test_scene_v0";

export const demoManifest: Manifest = {
  scene_id: DEMO_SCENE_ID,
  created_at: "2026-04-25T14:23:11Z",
  status: "ready",
  stages: {
    capture: { status: "complete", duration_s: 8 },
    poses: { status: "complete", duration_s: 4.1, method: "vggt-surfel" },
    splat: { status: "complete", duration_s: 1.2, gaussian_count: 1_120_345 },
    segmentation: { status: "complete", duration_s: 78, object_count: 2 },
  },
  artifacts: {
    splat_ply: `/artifacts/scenes/${DEMO_SCENE_ID}/splat.ply`,
    annotations_json: `/artifacts/scenes/${DEMO_SCENE_ID}/annotations.json`,
    thumbnail_jpg: `/artifacts/scenes/${DEMO_SCENE_ID}/thumbnail.jpg`,
    cameras_json: `/artifacts/scenes/${DEMO_SCENE_ID}/cameras.json`,
  },
  stats: { frame_count: 60, object_count: 2, splat_size_mb: 0 },
  errors: [],
};

export const demoAnnotations: Annotation[] = [
  {
    id: "obj_001",
    label: "MacBook Air (M3)",
    centroid: [0.42, 0.91, -1.23],
    bbox: [
      [0.3, 0.85, -1.4],
      [0.55, 0.95, -1.1],
    ],
    color: "#a8b2bd",
    confidence: 0.91,
    alternatives: ["laptop", "MacBook"],
    cluster_gaussian_indices: [12, 45, 78, 102],
  },
  {
    id: "obj_002",
    label: "stack of books",
    centroid: [-0.31, 0.88, -1.5],
    bbox: [
      [-0.42, 0.8, -1.62],
      [-0.2, 0.96, -1.38],
    ],
    color: "#7a5a3a",
    confidence: 0.83,
    alternatives: ["books", "pile of books"],
    cluster_gaussian_indices: [201, 202, 215, 233, 244],
  },
  {
    id: "obj_003",
    label: "Yeti Blue microphone",
    centroid: [0.78, 0.7, -0.85],
    bbox: [
      [0.7, 0.55, -0.95],
      [0.86, 0.85, -0.75],
    ],
    color: "#4d4d52",
    confidence: 0.78,
    alternatives: ["microphone", "podcast mic"],
    cluster_gaussian_indices: [310, 312, 318, 324, 330],
  },
  {
    id: "obj_004",
    label: "ceramic mug",
    centroid: [-0.55, 0.84, -0.62],
    bbox: [
      [-0.62, 0.78, -0.7],
      [-0.48, 0.92, -0.54],
    ],
    color: "#c89c6a",
    confidence: 0.86,
    alternatives: ["cup", "coffee cup"],
    cluster_gaussian_indices: [401, 405, 411, 419, 423],
  },
];
