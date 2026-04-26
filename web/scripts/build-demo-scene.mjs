#!/usr/bin/env node
// Generates a self-contained "_demo" scene under web/public/demo so the
// scenes viewer renders something tangible on localhost without needing
// R2 / Modal / the agent service to be live.
//
// Output:
//   web/public/demo/points.ply       — binary PLY (xyz float32 + uchar rgb)
//   web/public/demo/annotations.json — three stub objects
//
// Coordinates: useScene.ts flips Y and Z when reading both the cloud and
// annotations (OpenCV → Three.js). To keep the mental model sane we author
// the scene in viewer-friendly coords (+Y up) and negate Y/Z on write so
// the runtime flip restores them.

import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(__dirname, "..", "public", "demo");
mkdirSync(OUT, { recursive: true });

// ── room geometry ──
const W = 4.0;   // width  (x)
const H = 2.6;   // height (y, viewer-up)
const D = 4.0;   // depth  (z, viewer-forward-ish)

const pts = [];
const rng = mulberry32(0xc0ffee); // deterministic, so the build is reproducible

const jitter = (a) => a + (rng() - 0.5) * 0.025;

// Wall: covers a planar quad. `axis` is the constant axis; `at` is its
// value; the other two axes range over [u0,u1] and [v0,v1]. We sample N×N
// points with a small noise to break the grid look.
const wall = (axis, at, u0, u1, v0, v1, color) => {
  const N = 48;
  for (let i = 0; i < N; i++) {
    for (let j = 0; j < N; j++) {
      const u = u0 + (u1 - u0) * (i / (N - 1));
      const v = v0 + (v1 - v0) * (j / (N - 1));
      let x, y, z;
      if (axis === "y") { x = jitter(u); y = jitter(at); z = jitter(v); }
      else if (axis === "x") { x = jitter(at); y = jitter(u); z = jitter(v); }
      else /* z */          { x = jitter(u); y = jitter(v); z = jitter(at); }
      pts.push([x, y, z, color]);
    }
  }
};

// Sunset palette: floor cream, ceiling deep plum, walls graded warm.
wall("y", 0,   -W / 2, W / 2, -D / 2, D / 2, [228, 195, 168]); // floor
wall("y", H,   -W / 2, W / 2, -D / 2, D / 2, [54, 32, 44]);    // ceiling
wall("z", -D/2, -W / 2, W / 2, 0, H,         [255, 157, 111]); // back wall (apricot)
wall("z",  D/2, -W / 2, W / 2, 0, H,         [77, 47, 58]);    // front wall (deep)
wall("x", -W/2, -D / 2, D / 2, 0, H,         [255, 210, 156]); // left wall (gold)
wall("x",  W/2, -D / 2, D / 2, 0, H,         [255, 107, 74]);  // right wall (coral)

// Solid box of points for visual mass.
const box = (cx, cy, cz, sx, sy, sz, color, step = 0.05) => {
  for (let x = cx - sx / 2; x <= cx + sx / 2 + 1e-9; x += step) {
    for (let y = cy - sy / 2; y <= cy + sy / 2 + 1e-9; y += step) {
      for (let z = cz - sz / 2; z <= cz + sz / 2 + 1e-9; z += step) {
        pts.push([jitter(x), jitter(y), jitter(z), color]);
      }
    }
  }
};

// "side chair" near the back-left.
box(-1.0, 0.4, -1.0, 0.6, 0.8, 0.6, [200, 140, 110]);
// "low table" centred-front-right.
box( 0.8, 0.42, 0.5, 1.2, 0.04, 0.8, [150, 100, 80]);
box( 0.4, 0.21, 0.2, 0.04, 0.4, 0.04, [110, 80, 70]);
box( 1.2, 0.21, 0.2, 0.04, 0.4, 0.04, [110, 80, 70]);
box( 0.4, 0.21, 0.8, 0.04, 0.4, 0.04, [110, 80, 70]);
box( 1.2, 0.21, 0.8, 0.04, 0.4, 0.04, [110, 80, 70]);
// "lamp" on the table.
box( 0.8, 0.7, 0.5, 0.18, 0.5, 0.18, [255, 220, 170]);

// ── PLY (binary little-endian) ──
const N = pts.length;
const header =
  "ply\n" +
  "format binary_little_endian 1.0\n" +
  `element vertex ${N}\n` +
  "property float x\n" +
  "property float y\n" +
  "property float z\n" +
  "property uchar red\n" +
  "property uchar green\n" +
  "property uchar blue\n" +
  "end_header\n";

const STRIDE = 4 + 4 + 4 + 1 + 1 + 1; // 15
const body = Buffer.alloc(STRIDE * N);
for (let i = 0; i < N; i++) {
  const [x, y, z, c] = pts[i];
  const off = i * STRIDE;
  body.writeFloatLE(x, off + 0);
  // Negate Y and Z so useScene's flip restores them to viewer-up.
  body.writeFloatLE(-y, off + 4);
  body.writeFloatLE(-z, off + 8);
  body.writeUInt8(clamp8(c[0]), off + 12);
  body.writeUInt8(clamp8(c[1]), off + 13);
  body.writeUInt8(clamp8(c[2]), off + 14);
}

writeFileSync(resolve(OUT, "points.ply"), Buffer.concat([Buffer.from(header, "ascii"), body]));

// ── annotations ──
// Authored in viewer convention; flip Y/Z so useScene's flip restores them.
const annotations = [
  {
    id: "obj_chair",
    label: "side chair",
    centroid: [-1.0, 0.4, -1.0],
    bbox: [[-1.3, 0, -1.3], [-0.7, 0.8, -0.7]],
    color: "#ff9d6f",
    confidence: 0.92,
    alternatives: ["armchair", "stool"],
    frame_ids: [],
  },
  {
    id: "obj_table",
    label: "low table",
    centroid: [0.8, 0.42, 0.5],
    bbox: [[0.2, 0.2, 0.1], [1.4, 0.46, 0.9]],
    color: "#ffd29c",
    confidence: 0.87,
    frame_ids: [],
  },
  {
    id: "obj_lamp",
    label: "table lamp",
    centroid: [0.8, 0.7, 0.5],
    bbox: [[0.71, 0.45, 0.41], [0.89, 0.95, 0.59]],
    color: "#ff6b4a",
    confidence: 0.81,
    frame_ids: [],
  },
];

const flipPt = ([x, y, z]) => [x, -y, -z];
const flipBox = ([lo, hi]) => [
  [lo[0], -hi[1], -hi[2]],
  [hi[0], -lo[1], -lo[2]],
];
const written = annotations.map((a) => ({
  ...a,
  centroid: flipPt(a.centroid),
  bbox: flipBox(a.bbox),
}));

writeFileSync(
  resolve(OUT, "annotations.json"),
  JSON.stringify(written, null, 2),
);

console.log(`✓ wrote ${N.toLocaleString()} points → public/demo/points.ply`);
console.log(`✓ wrote ${written.length} annotations → public/demo/annotations.json`);

// ── helpers ──
function clamp8(n) { return Math.max(0, Math.min(255, Math.round(n))); }
function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
