"use client";

/**
 * Splat viewer: wraps @mkkellogg/gaussian-splats-3d Viewer, mounts a Three.js
 * canvas, optionally renders a placeholder scene when the splat is empty (stub
 * scene). Forwards camera position + direction every frame so the UI store
 * always knows where the user is looking — that's what `Where am I?` reads.
 */

import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import * as Splat from "@mkkellogg/gaussian-splats-3d";
import type { Annotation } from "@/lib/types";
import { useUI } from "@/store/ui";
import { AnnotationOverlay } from "./AnnotationOverlay";

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

  // Initial camera derived from annotation centroid spread, so the placeholder
  // path looks reasonable even with an empty splat.
  const initial = useMemo(() => initialView(annotations), [annotations]);

  useEffect(() => {
    if (!containerRef.current) return;
    let disposed = false;

    const useViewer = !emptySplat;
    let raf = 0;

    const cleanup: (() => void)[] = [];

    if (useViewer) {
      const viewer = new (Splat as unknown as { Viewer: any }).Viewer({
        cameraUp: [0, 1, 0],
        initialCameraPosition: initial.position,
        initialCameraLookAt: initial.lookAt,
        sharedMemoryForWorkers: false,
        gpuAcceleratedSort: true,
        rootElement: containerRef.current,
        useBuiltInControls: true,
        showLoadingUI: false,
      });

      void viewer
        .addSplatScene(splatUrl, {
          showLoadingUI: false,
          // Progressive load needs crossOriginIsolated (SharedArrayBuffer →
          // COOP/COEP headers). Next dev doesn't set those, and the library
          // can silently fail the stream parse. Load whole-file instead.
          progressiveLoad: false,
        })
        .then(() => {
          if (!disposed) viewer.start();
        })
        .catch((err: unknown) => {
          // Was silently swallowed before — left the user with a black canvas
          // and no signal. Surface it instead.
          console.error("[SplatViewer] addSplatScene failed:", splatUrl, err);
        });

      sceneRef.current.camera = viewer.camera ?? null;
      cleanup.push(() => {
        try {
          viewer.dispose?.();
        } catch {
          /* dispose may throw on early teardown */
        }
      });

      const tickViewerCamera = () => {
        const cam = viewer.camera;
        if (cam) {
          const pos = cam.position;
          const dir = new THREE.Vector3();
          cam.getWorldDirection(dir);
          setCamera([pos.x, pos.y, pos.z], [dir.x, dir.y, dir.z]);
        }
        raf = requestAnimationFrame(tickViewerCamera);
      };
      raf = requestAnimationFrame(tickViewerCamera);
      cleanup.push(() => cancelAnimationFrame(raf));
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

      annotations.forEach((a) => {
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
        setCamera(
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
      cleanup.forEach((fn) => fn());
      // Defensive: viewer.dispose() and renderer.dispose() do not always
      // remove DOM children added by the splat library. Clear anything left
      // so React doesn't trip over foreign nodes on re-render.
      const c = containerRef.current;
      if (c) while (c.firstChild) c.removeChild(c.firstChild);
    };
  }, [splatUrl, emptySplat, annotations, initial, setCamera]);

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