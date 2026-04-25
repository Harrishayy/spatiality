// MIRROR OF shared/shared/schemas/annotations.py — keep in sync.
// Spec: plans/modules/05_storage.md.

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
}

export type AnnotationsFile = Annotation[];
