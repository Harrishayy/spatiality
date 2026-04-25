"use client";

/**
 * Splat viewer: parses our INRIA-layout PLY ourselves and renders it as a
 * Three.js Points cloud. We dropped @mkkellogg/gaussian-splats-3d after it
 * silently rendered nothing for a 27MB-then-2MB-then-32MB sequence of valid
 * PLYs across ~6 hours of debugging — the library reported parse success and
 * sceneCount=1 but never put pixels on screen. The Points-cloud render below
 * uses only documented Three.js primitives (BufferGeometry, Points,
 * PointsMaterial), so failures surface as actual exceptions.
 */

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import type { Annotation } from "@/lib/types";
import { useUI } from "@/store/ui";
import { AnnotationOverlay } from "./AnnotationOverlay";

// PLY decode constant: f_dc * SH_C0 + 0.5 = RGB ∈ [0,1]
const SH_C0 = 0.282094791;

/** Minimal PLY parser for binary_little_endian float headers.
 *  Returns positions (Nx3 Float32) and colors (Nx3 Float32 in [0,1]).
 *  Decodes color from f_dc_* if present, else falls back to per-vertex
 *  red/green/blue uchar attributes if present, else mid-gray. */
function parsePly(buf: ArrayBuffer): {
  positions: Float32Array;
  colors: Float32Array;
  count: number;
} {
  const bytes = new Uint8Array(buf);
  // Header is ASCII; find "end_header\n".
  const needle = new TextEncoder().encode("end_header\n");
  let bodyOff = -1;
  for (let i = 0; i + needle.length <= bytes.length; i++) {
    let m = true;
    for (let j = 0; j < needle.length; j++) {
      if (bytes[i + j] !== needle[j]) {
        m = false;
        break;
      }
    }
    if (m) {
      bodyOff = i + needle.length;
      break;
    }
  }
  if (bodyOff < 0) throw new Error("PLY: no end_header marker");
  const header = new TextDecoder("ascii").decode(bytes.subarray(0, bodyOff));
  if (!header.includes("format binary_little_endian 1.0")) {
    throw new Error("PLY: only binary_little_endian 1.0 supported");
  }

  // Walk header for vertex count and property list (in declaration order).
  type Prop = { name: string; type: string };
  let count = 0;
  const props: Prop[] = [];
  for (const line of header.split("\n")) {
    if (line.startsWith("element vertex ")) {
      count = parseInt(line.split(/\s+/)[2], 10);
    } else if (line.startsWith("property ")) {
      const parts = line.split(/\s+/);
      props.push({ type: parts[1], name: parts[2] });
    }
  }
  if (!count) throw new Error("PLY: vertex count = 0");

  // Compute strides (we only support float32 + uchar per-property, which
  // covers every Gaussian-splat dialect we've seen).
  const sizeOf = (t: string) =>
    t === "float" || t === "float32"
      ? 4
      : t === "uchar" || t === "uint8"
        ? 1
        : (() => {
            throw new Error(`PLY: unsupported property type ${t}`);
          })();
  let stride = 0;
  const offsetByName: Record<string, { off: number; type: string }> = {};
  for (const p of props) {
    offsetByName[p.name] = { off: stride, type: p.type };
    stride += sizeOf(p.type);
  }
  if (!offsetByName.x || !offsetByName.y || !offsetByName.z) {
    throw new Error("PLY: missing x/y/z");
  }

  const dv = new DataView(buf, bodyOff);
  const positions = new Float32Array(count * 3);
  const colors = new Float32Array(count * 3);

  const readF = (i: number, name: string) =>
    dv.getFloat32(i * stride + offsetByName[name].off, true);
  const readU8 = (i: number, name: string) =>
    dv.getUint8(i * stride + offsetByName[name].off);

  const hasFdc =
    "f_dc_0" in offsetByName &&
    "f_dc_1" in offsetByName &&
    "f_dc_2" in offsetByName;
  const hasUchar =
    "red" in offsetByName &&
    "green" in offsetByName &&
    "blue" in offsetByName &&
    offsetByName.red.type !== "float";

  for (let i = 0; i < count; i++) {
    positions[i * 3] = readF(i, "x");
    positions[i * 3 + 1] = readF(i, "y");
    positions[i * 3 + 2] = readF(i, "z");
    if (hasFdc) {
      // RGB = SH_C0 * f_dc + 0.5, clamped.
      const r = SH_C0 * readF(i, "f_dc_0") + 0.5;
      const g = SH_C0 * readF(i, "f_dc_1") + 0.5;
      const b = SH_C0 * readF(i, "f_dc_2") + 0.5;
      colors[i * 3] = Math.max(0, Math.min(1, r));
      colors[i * 3 + 1] = Math.max(0, Math.min(1, g));
      colors[i * 3 + 2] = Math.max(0, Math.min(1, b));
    } else if (hasUchar) {
      colors[i * 3] = readU8(i, "red") / 255;
      colors[i * 3 + 1] = readU8(i, "green") / 255;
      colors[i * 3 + 2] = readU8(i, "blue") / 255;
    } else {
      colors[i * 3] = 0.7;
      colors[i * 3 + 1] = 0.7;
      colors[i * 3 + 2] = 0.7;
    }
  }
  return { positions, colors, count };
}

type DebugState = {
  status: "idle" | "fetching" | "parsing" | "started" | "error";
  url?: string;
  fetchBytes?: number;
  fetchTotal?: number;
  fetchMs?: number;
  parseMs?: number;
  startedMs?: number;
  sceneCount?: number;
  webglOk?: boolean;
  containerSize?: [number, number];
  error?: string;
  errorStack?: string;
  log: string[];
};

interface Props {
  splatUrl: string;
  annotations: Annotation[];
  /** Set true when the splat file is empty/0-vertex; we'll show a placeholder. */
  emptySplat?: boolean;
}

export function SplatViewer({ splatUrl, annotations, emptySplat }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const overlayRef = useRef<HTMLDivElement | null>(null);
  const sceneRef = useRef<{
    cancel: () => void;
    camera: THREE.Camera | null;
  }>({ cancel: () => undefined, camera: null });
  const setCamera = useUI((s) => s.setCamera);
  const selectedId = useUI((s) => s.selectedId);
  const [debug, setDebug] = useState<DebugState>({ status: "idle", log: [] });
  const debugRef = useRef(debug);
  debugRef.current = debug;
  const pushDebug = (patch: Partial<DebugState>, line?: string) => {
    const next: DebugState = {
      ...debugRef.current,
      ...patch,
      log: line
        ? [...debugRef.current.log, `${new Date().toISOString().slice(11, 23)} ${line}`].slice(-30)
        : debugRef.current.log,
    };
    debugRef.current = next;
    setDebug(next);
    if (line) console.log(`[SplatViewer] ${line}`, patch);
  };

  // Refs so the heavy effect can read the latest annotations + setCamera
  // WITHOUT taking them as dependencies. annotations is a fresh array on
  // every parent render (page does `annotations.data ?? []`) — if we put it
  // in deps the splat viewer remounts on every 2s manifest poll, each
  // in-flight addSplatScene rejects with "Scene disposed", and the dispose
  // path stomps on DOM nodes mid-load. Critical fix.
  const annotationsRef = useRef<Annotation[]>(annotations);
  useEffect(() => {
    annotationsRef.current = annotations;
  }, [annotations]);
  const setCameraRef = useRef(setCamera);
  useEffect(() => {
    setCameraRef.current = setCamera;
  }, [setCamera]);

  // Fly-to request: set externally (annotation click, preset button), the
  // render loop interpolates `target` and `radius` toward it each frame.
  const flyToRef = useRef<{
    target: [number, number, number];
    radius: number;
  } | null>(null);

  // Imperative API the surrounding UI (zoom buttons, minimap) calls into.
  type ViewerApi = {
    zoom: (factor: number) => void;
    setTarget: (xyz: [number, number, number], radius?: number) => void;
    reset: () => void;
  };
  const apiRef = useRef<ViewerApi | null>(null);

  // Subset of points for the minimap (downsampled, kept in React state so
  // the minimap re-renders when the cloud loads). Camera position comes from
  // the existing zustand store, so the minimap re-renders ~60Hz for free.
  const [miniPoints, setMiniPoints] = useState<{
    xz: Float32Array; // (M*2,) flattened (x, z) pairs
    rgb: Float32Array; // (M*3,)
    bounds: { minX: number; maxX: number; minZ: number; maxZ: number };
  } | null>(null);
  useEffect(() => {
    if (!selectedId) return;
    const a = annotationsRef.current.find((x) => x.id === selectedId);
    if (!a) return;
    const [lo, hi] = a.bbox;
    const ext = Math.max(
      hi[0] - lo[0],
      hi[1] - lo[1],
      hi[2] - lo[2],
    );
    flyToRef.current = {
      target: a.centroid as [number, number, number],
      // Pull camera in proportional to the object's extent — small things =
      // close-up, big things = farther back.
      radius: Math.max(0.18, ext * 2.2),
    };
  }, [selectedId]);

  useEffect(() => {
    if (!containerRef.current) return;
    let disposed = false;

    // Snapshot annotations once for initial camera framing. Live updates after
    // mount go through AnnotationOverlay (it re-renders on prop change).
    const initial = initialView(annotationsRef.current);

    const useViewer = !emptySplat;
    let raf = 0;

    const cleanup: (() => void)[] = [];

    const c0 = containerRef.current;
    pushDebug(
      {
        status: "idle",
        url: splatUrl,
        containerSize: [c0.clientWidth, c0.clientHeight],
      },
      `mount: useViewer=${useViewer} url=${splatUrl} container=${c0.clientWidth}x${c0.clientHeight}`,
    );

    if (useViewer) {
      // WebGL probe — confirms the canvas can get a context at all.
      try {
        const probe = document.createElement("canvas");
        const ctx =
          probe.getContext("webgl2") || probe.getContext("webgl");
        pushDebug({ webglOk: !!ctx }, `webgl: ${ctx ? "OK" : "MISSING"}`);
      } catch (e) {
        pushDebug({ webglOk: false }, `webgl probe threw: ${e}`);
      }

      const container = containerRef.current;
      const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.setSize(container.clientWidth, container.clientHeight);
      renderer.setClearColor(0x0a0a0c, 1);
      container.appendChild(renderer.domElement);

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(
        50,
        container.clientWidth / container.clientHeight,
        0.05,
        100,
      );
      camera.position.set(...initial.position);
      camera.lookAt(...initial.lookAt);
      sceneRef.current.camera = camera;

      // Light scene scaffolding so the cloud has spatial context.
      scene.add(new THREE.GridHelper(8, 16, 0x3a3a46, 0x1a1a20));

      // Camera controls:
      //   left-drag   → orbit around `target` (theta/phi)
      //   right-drag  → pan `target` in screen space (move into the cloud)
      //   shift+drag  → also pan (for trackpad users without right-button)
      //   wheel       → dolly (radius); preventDefault on passive:false so the
      //                  browser doesn't scroll the page while you zoom
      //   keys WASD   → pan target horizontally; QE → pan vertically
      const target = new THREE.Vector3(...initial.lookAt);
      const sph = new THREE.Spherical();
      sph.setFromVector3(camera.position.clone().sub(target));
      let dragging: "orbit" | "pan" | null = null;
      let lastX = 0;
      let lastY = 0;
      const onDown = (e: PointerEvent) => {
        dragging =
          e.button === 2 || e.shiftKey || e.metaKey || e.ctrlKey
            ? "pan"
            : "orbit";
        lastX = e.clientX;
        lastY = e.clientY;
        (e.target as Element)?.setPointerCapture?.(e.pointerId);
      };
      const onMove = (e: PointerEvent) => {
        if (!dragging) return;
        const dx = e.clientX - lastX;
        const dy = e.clientY - lastY;
        lastX = e.clientX;
        lastY = e.clientY;
        if (dragging === "orbit") {
          sph.theta -= dx * 0.005;
          sph.phi = Math.max(0.05, Math.min(Math.PI - 0.05, sph.phi - dy * 0.005));
        } else {
          // Pan in camera-screen space scaled by radius so it feels
          // proportional at any zoom level.
          const right = new THREE.Vector3();
          const up = new THREE.Vector3();
          camera.matrixWorld.extractBasis(right, up, new THREE.Vector3());
          const k = sph.radius * 0.0015;
          target.addScaledVector(right, -dx * k);
          target.addScaledVector(up, dy * k);
        }
      };
      const onUp = () => {
        dragging = null;
      };
      const onWheel = (e: WheelEvent) => {
        e.preventDefault();
        const factor = Math.exp(e.deltaY * 0.0015);
        sph.radius = Math.max(0.05, Math.min(40, sph.radius * factor));
      };
      const onContextMenu = (e: MouseEvent) => e.preventDefault();
      const onKey = (e: KeyboardEvent) => {
        const k = sph.radius * 0.04;
        const right = new THREE.Vector3();
        const up = new THREE.Vector3();
        const fwd = new THREE.Vector3();
        camera.matrixWorld.extractBasis(right, up, fwd);
        fwd.negate();
        switch (e.key.toLowerCase()) {
          case "w": target.addScaledVector(fwd, k); break;
          case "s": target.addScaledVector(fwd, -k); break;
          case "a": target.addScaledVector(right, -k); break;
          case "d": target.addScaledVector(right, k); break;
          case "q": target.addScaledVector(up, -k); break;
          case "e": target.addScaledVector(up, k); break;
          case "r":
            target.set(...initial.lookAt);
            sph.setFromVector3(
              new THREE.Vector3(...initial.position).sub(target),
            );
            break;
          default: return;
        }
      };
      const dom = renderer.domElement;
      dom.addEventListener("pointerdown", onDown);
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      dom.addEventListener("wheel", onWheel, { passive: false });
      dom.addEventListener("contextmenu", onContextMenu);
      window.addEventListener("keydown", onKey);

      // Imperative API for outside UI (zoom buttons, minimap).
      apiRef.current = {
        zoom: (factor) => {
          sph.radius = Math.max(0.05, Math.min(40, sph.radius * factor));
        },
        setTarget: (xyz, radius) => {
          flyToRef.current = {
            target: xyz,
            radius: radius ?? sph.radius,
          };
        },
        reset: () => {
          target.set(...initial.lookAt);
          sph.setFromVector3(
            new THREE.Vector3(...initial.position).sub(target),
          );
          flyToRef.current = null;
        },
      };
      cleanup.push(() => {
        apiRef.current = null;
      });

      const onResize = () => {
        const w = container.clientWidth;
        const h = container.clientHeight;
        renderer.setSize(w, h);
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
      };
      window.addEventListener("resize", onResize);

      const tick = () => {
        // Interpolate toward the requested fly-to (annotation click etc.).
        const fly = flyToRef.current;
        if (fly) {
          const dst = new THREE.Vector3(...fly.target);
          target.lerp(dst, 0.12);
          sph.radius += (fly.radius - sph.radius) * 0.12;
          if (target.distanceToSquared(dst) < 1e-5 && Math.abs(sph.radius - fly.radius) < 1e-3) {
            flyToRef.current = null;
          }
        }
        const offset = new THREE.Vector3().setFromSpherical(sph);
        camera.position.copy(target.clone().add(offset));
        camera.lookAt(target);
        const dirVec = new THREE.Vector3();
        camera.getWorldDirection(dirVec);
        setCameraRef.current(
          [camera.position.x, camera.position.y, camera.position.z],
          [dirVec.x, dirVec.y, dirVec.z],
        );
        renderer.render(scene, camera);
        raf = requestAnimationFrame(tick);
      };
      tick();

      cleanup.push(() => {
        cancelAnimationFrame(raf);
        dom.removeEventListener("pointerdown", onDown);
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        dom.removeEventListener("wheel", onWheel);
        dom.removeEventListener("contextmenu", onContextMenu);
        window.removeEventListener("keydown", onKey);
        window.removeEventListener("resize", onResize);
        try {
          renderer.dispose();
          renderer.forceContextLoss();
          dom.remove();
        } catch {
          /* renderer disposal may race */
        }
      });

      // Fetch + parse PLY ourselves, build Three.js Points from xyz + decoded RGB.
      const fetchStart = performance.now();
      pushDebug(
        { status: "fetching", error: undefined, errorStack: undefined },
        `fetching ${splatUrl}`,
      );
      fetch(splatUrl)
        .then(async (res) => {
          if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText}`);
          const total = Number(res.headers.get("content-length") || 0);
          pushDebug(
            { fetchTotal: total },
            `fetch ok status=${res.status} content-length=${total}`,
          );
          const buf = await res.arrayBuffer();
          const fetchMs = Math.round(performance.now() - fetchStart);
          pushDebug(
            { fetchBytes: buf.byteLength, fetchMs, status: "parsing" },
            `fetched ${buf.byteLength} bytes in ${fetchMs}ms; parsing PLY`,
          );

          const parseStart = performance.now();
          const { positions, colors, count } = parsePly(buf);
          if (disposed) return;
          const parseMs = Math.round(performance.now() - parseStart);
          pushDebug(
            { parseMs, sceneCount: count, status: "started" },
            `parsed ${count} points in ${parseMs}ms; building Points`,
          );

          const geom = new THREE.BufferGeometry();
          geom.setAttribute("position", new THREE.BufferAttribute(positions, 3));
          geom.setAttribute("color", new THREE.BufferAttribute(colors, 3));
          const mat = new THREE.PointsMaterial({
            size: 0.012,
            vertexColors: true,
            sizeAttenuation: true,
            transparent: false,
            depthWrite: true,
          });
          const points = new THREE.Points(geom, mat);
          scene.add(points);
          pushDebug(
            { startedMs: 0 },
            `Points added to scene (size=${mat.size}m); first frame imminent`,
          );

          // Build a downsampled top-down (x,z) snapshot for the minimap.
          const M = Math.min(8000, count);
          const stride = Math.max(1, Math.floor(count / M));
          const xz = new Float32Array(Math.ceil(count / stride) * 2);
          const rgb = new Float32Array(Math.ceil(count / stride) * 3);
          let mi = 0;
          let minX = Infinity,
            maxX = -Infinity,
            minZ = Infinity,
            maxZ = -Infinity;
          for (let i = 0; i < count; i += stride) {
            const x = positions[i * 3];
            const z = positions[i * 3 + 2];
            xz[mi * 2] = x;
            xz[mi * 2 + 1] = z;
            rgb[mi * 3] = colors[i * 3];
            rgb[mi * 3 + 1] = colors[i * 3 + 1];
            rgb[mi * 3 + 2] = colors[i * 3 + 2];
            if (x < minX) minX = x;
            if (x > maxX) maxX = x;
            if (z < minZ) minZ = z;
            if (z > maxZ) maxZ = z;
            mi++;
          }
          setMiniPoints({
            xz: xz.subarray(0, mi * 2),
            rgb: rgb.subarray(0, mi * 3),
            bounds: { minX, maxX, minZ, maxZ },
          });
        })
        .catch((err: unknown) => {
          const e = err as Error;
          pushDebug(
            {
              status: "error",
              error: e?.message ?? String(err),
              errorStack: e?.stack,
            },
            `FAILED: ${e?.message ?? err}`,
          );
          console.error("[SplatViewer] load failed:", splatUrl, err);
        });
    } else {
      // Placeholder Three.js scene — friendly grid + ambient backdrop so the
      // annotation overlay still has spatial context to live in.
      const container = containerRef.current;
      const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.setSize(container.clientWidth, container.clientHeight);
      renderer.setClearColor(0x0a0a0c, 1);
      container.appendChild(renderer.domElement);

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(
        45,
        container.clientWidth / container.clientHeight,
        0.05,
        100,
      );
      camera.position.set(...initial.position);
      camera.lookAt(...initial.lookAt);

      // Subtle radial glow + grid + bbox wireframes for each annotation
      const grid = new THREE.GridHelper(8, 16, 0x3a3a46, 0x1a1a20);
      grid.position.y = 0;
      scene.add(grid);

      const ambient = new THREE.AmbientLight(0xffffff, 0.5);
      scene.add(ambient);
      const dir = new THREE.DirectionalLight(0x9b85ff, 0.8);
      dir.position.set(2, 3, 1);
      scene.add(dir);

      annotationsRef.current.forEach((a) => {
        const [lo, hi] = a.bbox;
        const size = new THREE.Vector3(
          hi[0] - lo[0],
          hi[1] - lo[1],
          hi[2] - lo[2],
        );
        const center = new THREE.Vector3(
          (lo[0] + hi[0]) / 2,
          (lo[1] + hi[1]) / 2,
          (lo[2] + hi[2]) / 2,
        );
        const geo = new THREE.BoxGeometry(size.x, size.y, size.z);
        const edges = new THREE.EdgesGeometry(geo);
        const mat = new THREE.LineBasicMaterial({
          color: new THREE.Color(a.color),
          transparent: true,
          opacity: 0.85,
        });
        const wire = new THREE.LineSegments(edges, mat);
        wire.position.copy(center);
        wire.userData.annotationId = a.id;
        scene.add(wire);
        geo.dispose();
      });

      // Light orbit controls — drag to rotate around lookAt.
      const target = new THREE.Vector3(...initial.lookAt);
      const sph = new THREE.Spherical();
      sph.setFromVector3(camera.position.clone().sub(target));
      let dragging = false;
      let lastX = 0;
      let lastY = 0;
      const onDown = (e: PointerEvent) => {
        dragging = true;
        lastX = e.clientX;
        lastY = e.clientY;
      };
      const onMove = (e: PointerEvent) => {
        if (!dragging) return;
        const dx = e.clientX - lastX;
        const dy = e.clientY - lastY;
        lastX = e.clientX;
        lastY = e.clientY;
        sph.theta -= dx * 0.005;
        sph.phi = Math.max(0.05, Math.min(Math.PI - 0.05, sph.phi - dy * 0.005));
      };
      const onUp = () => {
        dragging = false;
      };
      const onWheel = (e: WheelEvent) => {
        sph.radius = Math.max(0.5, Math.min(20, sph.radius + e.deltaY * 0.002));
      };
      const dom = renderer.domElement;
      dom.addEventListener("pointerdown", onDown);
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      dom.addEventListener("wheel", onWheel, { passive: true });

      const onResize = () => {
        if (!container) return;
        const w = container.clientWidth;
        const h = container.clientHeight;
        renderer.setSize(w, h);
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
      };
      window.addEventListener("resize", onResize);

      const tick = () => {
        const offset = new THREE.Vector3().setFromSpherical(sph);
        camera.position.copy(target.clone().add(offset));
        camera.lookAt(target);

        const dirVec = new THREE.Vector3();
        camera.getWorldDirection(dirVec);
        setCameraRef.current(
          [camera.position.x, camera.position.y, camera.position.z],
          [dirVec.x, dirVec.y, dirVec.z],
        );

        renderer.render(scene, camera);
        raf = requestAnimationFrame(tick);
      };
      sceneRef.current.camera = camera;
      tick();

      cleanup.push(() => {
        cancelAnimationFrame(raf);
        dom.removeEventListener("pointerdown", onDown);
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        dom.removeEventListener("wheel", onWheel);
        window.removeEventListener("resize", onResize);
        try {
          renderer.dispose();
          renderer.forceContextLoss();
          dom.remove();
        } catch {
          /* renderer disposal may race */
        }
      });
    }

    return () => {
      disposed = true;
      cleanup.forEach((fn) => {
        try {
          fn();
        } catch {
          /* viewer.dispose() can throw if a load is still in flight */
        }
      });
      // Defensive: viewer.dispose() and renderer.dispose() do not always
      // remove DOM children added by the splat library. Clear anything left
      // so React doesn't trip over foreign nodes on re-render. Each
      // removeChild is wrapped because gaussian-splats-3d may have already
      // detached some nodes inside its own dispose path.
      const c = containerRef.current;
      if (c) {
        while (c.firstChild) {
          try {
            c.removeChild(c.firstChild);
          } catch {
            break;
          }
        }
      }
    };
  }, [splatUrl, emptySplat]);

  return (
    <div className="relative h-full w-full">
      <div
        ref={containerRef}
        className="absolute inset-0 overflow-hidden bg-ink-950"
      />
      <div
        ref={overlayRef}
        className="pointer-events-none absolute inset-0 overflow-hidden"
      >
        <AnnotationOverlay
          annotations={annotations}
          getCamera={() => sceneRef.current.camera}
          containerRef={overlayRef}
        />
      </div>
      <DebugHUD debug={debug} />
      <ControlsHint
        annotations={annotations}
        onSelect={(id) => useUI.getState().setSelected(id)}
        onZoomIn={() => apiRef.current?.zoom(0.7)}
        onZoomOut={() => apiRef.current?.zoom(1.4)}
        onReset={() => apiRef.current?.reset()}
      />
      {miniPoints && (
        <Minimap
          points={miniPoints}
          onPan={(x, z) => apiRef.current?.setTarget([x, 0.1, z])}
        />
      )}
    </div>
  );
}

function ControlsHint({
  annotations,
  onSelect,
  onZoomIn,
  onZoomOut,
  onReset,
}: {
  annotations: Annotation[];
  onSelect: (id: string) => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onReset: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="pointer-events-auto absolute bottom-3 left-3 flex flex-col items-start gap-2">
      {open && (
        <div className="rounded-md border border-ink-700/60 bg-ink-900/85 px-3 py-2 text-[11px] text-ink-200 backdrop-blur">
          <div className="mb-2 font-mono text-[10px] uppercase tracking-wider text-ink-400">
            controls
          </div>
          <ul className="space-y-0.5">
            <li><kbd className="font-mono opacity-80">drag</kbd> orbit</li>
            <li><kbd className="font-mono opacity-80">shift+drag</kbd> / right-drag — pan</li>
            <li><kbd className="font-mono opacity-80">wheel</kbd> zoom</li>
            <li><kbd className="font-mono opacity-80">W A S D</kbd> move target</li>
            <li><kbd className="font-mono opacity-80">Q E</kbd> up/down</li>
            <li><kbd className="font-mono opacity-80">R</kbd> reset</li>
          </ul>
          {annotations.length > 0 && (
            <>
              <div className="mt-2 mb-1 font-mono text-[10px] uppercase tracking-wider text-ink-400">
                fly to
              </div>
              <div className="flex flex-wrap gap-1">
                {annotations.slice(0, 8).map((a) => (
                  <button
                    key={a.id}
                    onClick={() => onSelect(a.id)}
                    className="rounded border border-ink-700/70 bg-ink-800/80 px-1.5 py-0.5 text-[10px] hover:border-accent-400/60 hover:text-accent-300"
                    title={a.label}
                  >
                    {a.label.split(" ").slice(0, 2).join(" ")}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      )}
      <div className="flex gap-1">
        <button
          onClick={onZoomIn}
          className="size-7 rounded-full border border-ink-700/70 bg-ink-900/80 font-mono text-sm text-ink-200 backdrop-blur hover:border-accent-400/60 hover:text-accent-300"
          title="Zoom in"
          aria-label="Zoom in"
        >
          +
        </button>
        <button
          onClick={onZoomOut}
          className="size-7 rounded-full border border-ink-700/70 bg-ink-900/80 font-mono text-sm text-ink-200 backdrop-blur hover:border-accent-400/60 hover:text-accent-300"
          title="Zoom out"
          aria-label="Zoom out"
        >
          −
        </button>
        <button
          onClick={() => setOpen((v) => !v)}
          className="rounded-full border border-ink-700/70 bg-ink-900/80 px-2.5 py-1 font-mono text-[10px] text-ink-200 backdrop-blur hover:border-accent-400/60 hover:text-accent-300"
        >
          {open ? "× hide" : "? controls"}
        </button>
        <button
          onClick={onReset}
          className="rounded-full border border-ink-700/70 bg-ink-900/80 px-2.5 py-1 font-mono text-[10px] text-ink-200 backdrop-blur hover:border-accent-400/60 hover:text-accent-300"
          title="Reset view (R)"
        >
          ↺ reset
        </button>
      </div>
    </div>
  );
}

function Minimap({
  points,
  onPan,
}: {
  points: {
    xz: Float32Array;
    rgb: Float32Array;
    bounds: { minX: number; maxX: number; minZ: number; maxZ: number };
  };
  onPan: (x: number, z: number) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const camera = useUI((s) => s.camera);
  const SIZE = 180;
  const PAD = 12;

  const { minX, maxX, minZ, maxZ } = points.bounds;
  const spanX = Math.max(1e-3, maxX - minX);
  const spanZ = Math.max(1e-3, maxZ - minZ);
  const scale = (SIZE - 2 * PAD) / Math.max(spanX, spanZ);
  const cx = (minX + maxX) / 2;
  const cz = (minZ + maxZ) / 2;

  const worldToCanvas = (x: number, z: number): [number, number] => [
    SIZE / 2 + (x - cx) * scale,
    // Invert z so "north" is up in the minimap.
    SIZE / 2 - (z - cz) * scale,
  ];
  const canvasToWorld = (px: number, py: number): [number, number] => [
    (px - SIZE / 2) / scale + cx,
    -(py - SIZE / 2) / scale + cz,
  ];

  // Draw point cloud once (it's static after load).
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, SIZE, SIZE);
    ctx.fillStyle = "#0a0a0c";
    ctx.fillRect(0, 0, SIZE, SIZE);
    const xz = points.xz;
    const rgb = points.rgb;
    const m = xz.length / 2;
    for (let i = 0; i < m; i++) {
      const [px, py] = worldToCanvas(xz[i * 2], xz[i * 2 + 1]);
      ctx.fillStyle = `rgb(${(rgb[i * 3] * 255) | 0},${(rgb[i * 3 + 1] * 255) | 0},${(rgb[i * 3 + 2] * 255) | 0})`;
      ctx.fillRect(px | 0, py | 0, 1, 1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [points]);

  // Camera marker — drawn on top each render via a sibling canvas overlay.
  const [camPx, camPy] = worldToCanvas(camera.position[0], camera.position[2]);
  const dirAngle = Math.atan2(-camera.direction[2], camera.direction[0]);

  return (
    <div className="pointer-events-auto absolute right-3 top-3 select-none">
      <div className="relative" style={{ width: SIZE, height: SIZE }}>
        <canvas
          ref={canvasRef}
          width={SIZE}
          height={SIZE}
          className="rounded-lg border border-ink-700/70 bg-ink-950 shadow-lg"
          onClick={(e) => {
            const rect = (e.target as HTMLCanvasElement).getBoundingClientRect();
            const px = e.clientX - rect.left;
            const py = e.clientY - rect.top;
            const [wx, wz] = canvasToWorld(px, py);
            onPan(wx, wz);
          }}
          title="Click to pan camera target there"
        />
        {/* Camera marker */}
        <svg
          width={SIZE}
          height={SIZE}
          className="pointer-events-none absolute inset-0"
        >
          <g transform={`translate(${camPx}, ${camPy}) rotate(${(-dirAngle * 180) / Math.PI})`}>
            <polygon
              points="0,-7 5,5 0,2 -5,5"
              fill="#a78bfa"
              stroke="#fff"
              strokeWidth="1"
            />
          </g>
        </svg>
        <div className="absolute bottom-1 left-1 font-mono text-[9px] uppercase tracking-wider text-ink-500">
          world · top-down
        </div>
      </div>
    </div>
  );
}

function DebugHUD({ debug }: { debug: DebugState }) {
  const dot =
    debug.status === "started"
      ? "bg-emerald-400"
      : debug.status === "error"
        ? "bg-red-400"
        : debug.status === "idle"
          ? "bg-ink-500"
          : "bg-accent-400 animate-[pulse_900ms_ease-in-out_infinite]";
  return (
    <div className="pointer-events-auto absolute left-3 top-3 max-w-md rounded-md border border-ink-700/70 bg-ink-900/85 px-3 py-2 font-mono text-[10px] text-ink-200 backdrop-blur">
      <div className="mb-1 flex items-center gap-2">
        <span className={`size-2 rounded-full ${dot}`} />
        <span className="uppercase tracking-wider">{debug.status}</span>
        {debug.containerSize && (
          <span className="opacity-70">
            container {debug.containerSize[0]}×{debug.containerSize[1]}
          </span>
        )}
        <span className="opacity-70">webgl: {debug.webglOk ? "✓" : debug.webglOk === false ? "✗" : "?"}</span>
      </div>
      {debug.url && <div className="truncate opacity-70">url: {debug.url}</div>}
      <div className="opacity-70">
        fetch: {debug.fetchBytes != null ? `${debug.fetchBytes} B` : "—"}
        {debug.fetchMs != null ? ` (${debug.fetchMs}ms)` : ""}
        {debug.fetchTotal ? ` / ${debug.fetchTotal}` : ""}
      </div>
      <div className="opacity-70">
        parse: {debug.parseMs != null ? `${debug.parseMs}ms` : "—"}
        {" · "}sceneCount: {debug.sceneCount ?? "—"}
        {debug.startedMs != null ? ` · started: ${debug.startedMs}ms` : ""}
      </div>
      {debug.error && (
        <div className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap rounded bg-red-500/10 px-2 py-1 text-red-200">
          ERROR: {debug.error}
          {debug.errorStack ? `\n${debug.errorStack.split("\n").slice(0, 4).join("\n")}` : ""}
        </div>
      )}
      <details className="mt-1">
        <summary className="cursor-pointer opacity-60">log ({debug.log.length})</summary>
        <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap text-[9px] leading-tight opacity-80">
          {debug.log.join("\n")}
        </pre>
      </details>
    </div>
  );
}

function initialView(annotations: Annotation[]): {
  position: [number, number, number];
  lookAt: [number, number, number];
} {
  if (annotations.length === 0) {
    return { position: [2, 1.6, 2], lookAt: [0, 0.8, 0] };
  }
  // Center on annotation centroid average, pull the camera back along +Z+Y.
  const c = annotations.reduce<[number, number, number]>(
    (acc, a) => [
      acc[0] + a.centroid[0],
      acc[1] + a.centroid[1],
      acc[2] + a.centroid[2],
    ],
    [0, 0, 0],
  );
  const n = annotations.length;
  const center: [number, number, number] = [c[0] / n, c[1] / n, c[2] / n];
  return {
    position: [center[0] + 1.5, center[1] + 0.6, center[2] + 1.5],
    lookAt: center,
  };
}