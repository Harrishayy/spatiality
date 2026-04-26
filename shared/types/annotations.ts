// MIRROR OF shared/shared/schemas/annotations.py — keep in sync.

export type Vec3 = [number, number, number];
export type BBox = [Vec3, Vec3];

export interface Annotation {
  id: string;
  label: string;
  centroid: Vec3;
  bbox: BBox;
  color: string;
  confidence: number;
  alternatives: string[];
  cluster_gaussian_indices: number[];
  provenance?: string[];
  frame_ids?: string[];
}

export type AnnotationsFile = Annotation[];
