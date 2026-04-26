// MIRROR OF shared/shared/schemas/wireframe.py — keep in sync.

export interface Range {
  start: number;
  end: number;
}

export interface WireframeIndex {
  point_count: number;
  voxel_range: Range;
  annotations: Record<string, Range>;
}
