import type { Annotation, Vec3 } from "./types";

interface NearbyOptions {
  maxDistance?: number;
  maxAngle?: number;
  limit?: number;
}

export function nearbyAnnotations(
  annotations: Annotation[],
  cameraPos: Vec3,
  cameraDir: Vec3,
  opts: NearbyOptions = {},
): Annotation[] {
  const maxDistance = opts.maxDistance ?? 50;
  const maxAngle = opts.maxAngle ?? Math.PI / 2;
  const limit = opts.limit ?? 64;

  const dirMag = Math.hypot(cameraDir[0], cameraDir[1], cameraDir[2]);
  if (dirMag === 0) return annotations.slice(0, limit);
  const dirNorm: Vec3 = [
    cameraDir[0] / dirMag,
    cameraDir[1] / dirMag,
    cameraDir[2] / dirMag,
  ];

  const scored: Array<{ annotation: Annotation; score: number }> = [];

  for (const a of annotations) {
    const to: Vec3 = [
      a.centroid[0] - cameraPos[0],
      a.centroid[1] - cameraPos[1],
      a.centroid[2] - cameraPos[2],
    ];
    const distance = Math.hypot(to[0], to[1], to[2]);
    if (distance > maxDistance) continue;

    let angle = 0;
    if (distance > 0) {
      const dot =
        (dirNorm[0] * to[0] + dirNorm[1] * to[1] + dirNorm[2] * to[2]) / distance;
      angle = Math.acos(Math.max(-1, Math.min(1, dot)));
      if (angle > maxAngle) continue;
    }

    const angleScore = 1 - angle / maxAngle;
    const distanceScore = 1 / (1 + distance);
    scored.push({ annotation: a, score: angleScore * distanceScore });
  }

  scored.sort((x, y) => y.score - x.score);
  return scored.slice(0, limit).map((x) => x.annotation);
}
