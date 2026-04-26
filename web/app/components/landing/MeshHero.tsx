"use client";

import { useEffect, useRef } from "react";
import * as THREE from "three";

export function MeshHero() {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const hostMaybe = ref.current;
    if (!hostMaybe) return;
    const host: HTMLDivElement = hostMaybe;

    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x1a0e14, 0.06);

    const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 100);
    camera.position.set(6.2, 3.4, 6.6);
    camera.lookAt(0, 0.2, 0);

    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x000000, 0);
    host.appendChild(renderer.domElement);

    const N = 1400;
    const targets = new Float32Array(N * 3);
    const labels = new Uint8Array(N);

    const rand = (min: number, max: number) =>
      min + Math.random() * (max - min);
    const jitter = (v: number, j: number) => v + (Math.random() - 0.5) * j;

    let i = 0;
    for (; i < 380; i++) {
      targets[i * 3 + 0] = rand(-3, 3);
      targets[i * 3 + 1] = jitter(0, 0.04);
      targets[i * 3 + 2] = rand(-3, 3);
      labels[i] = 0;
    }
    for (; i < 600; i++) {
      targets[i * 3 + 0] = rand(-3, 3);
      targets[i * 3 + 1] = rand(0, 2.6);
      targets[i * 3 + 2] = jitter(-3, 0.05);
      labels[i] = 1;
    }
    for (; i < 780; i++) {
      targets[i * 3 + 0] = jitter(-3, 0.05);
      targets[i * 3 + 1] = rand(0, 2.6);
      targets[i * 3 + 2] = rand(-3, 3);
      labels[i] = 1;
    }
    for (; i < 1020; i++) {
      const cx = -1.2,
        cy = 0.45,
        cz = 1.0;
      const sx = 1.0,
        sy = 0.45,
        sz = 0.45;
      const face = Math.floor(Math.random() * 5);
      let x = cx + rand(-sx, sx);
      let y = cy + rand(-sy, sy);
      let z = cz + rand(-sz, sz);
      if (face === 0) y = cy + sy;
      else if (face === 1) x = cx - sx;
      else if (face === 2) x = cx + sx;
      else if (face === 3) z = cz - sz;
      else if (face === 4) z = cz + sz;
      targets[i * 3 + 0] = jitter(x, 0.03);
      targets[i * 3 + 1] = jitter(y, 0.03);
      targets[i * 3 + 2] = jitter(z, 0.03);
      labels[i] = 2;
    }
    for (; i < 1200; i++) {
      const cx = 1.4,
        cy = 0.7,
        cz = -0.6;
      const sx = 0.7,
        sy = 0.05,
        sz = 0.5;
      const face = Math.floor(Math.random() * 5);
      let x = cx + rand(-sx, sx);
      let y = cy + rand(-sy, sy);
      let z = cz + rand(-sz, sz);
      if (face === 0) y = cy + sy;
      else if (face === 1) x = cx - sx;
      else if (face === 2) x = cx + sx;
      else if (face === 3) z = cz - sz;
      else if (face === 4) z = cz + sz;
      targets[i * 3 + 0] = jitter(x, 0.025);
      targets[i * 3 + 1] = jitter(y, 0.025);
      targets[i * 3 + 2] = jitter(z, 0.025);
      labels[i] = 3;
    }
    const legs: [number, number, number][] = [
      [0.85, 0.35, -0.15],
      [0.85, 0.35, -1.05],
      [1.95, 0.35, -0.15],
      [1.95, 0.35, -1.05],
    ];
    for (let li = 0; li < 4; li++, i += 50) {
      for (let k = 0; k < 50; k++) {
        targets[(i + k) * 3 + 0] = jitter(legs[li][0], 0.03);
        targets[(i + k) * 3 + 1] = jitter(legs[li][1], 0.32);
        targets[(i + k) * 3 + 2] = jitter(legs[li][2], 0.03);
        labels[i + k] = 3;
      }
    }
    const used = i;

    const origins = new Float32Array(used * 3);
    for (let k = 0; k < used; k++) {
      origins[k * 3 + 0] = rand(-7, 7);
      origins[k * 3 + 1] = rand(-3, 5);
      origins[k * 3 + 2] = rand(-7, 7);
    }

    const positions = new Float32Array(used * 3);
    const colors = new Float32Array(used * 3);
    const palette: [number, number, number][] = [
      [0.95, 0.78, 0.62],
      [0.55, 0.3, 0.42],
      [1.0, 0.42, 0.29],
      [1.0, 0.62, 0.43],
      [1.0, 0.82, 0.55],
    ];
    for (let k = 0; k < used; k++) {
      const c = palette[labels[k]] || palette[0];
      colors[k * 3 + 0] = c[0];
      colors[k * 3 + 1] = c[1];
      colors[k * 3 + 2] = c[2];
    }

    const pointGeom = new THREE.BufferGeometry();
    pointGeom.setAttribute(
      "position",
      new THREE.BufferAttribute(positions, 3),
    );
    pointGeom.setAttribute("color", new THREE.BufferAttribute(colors, 3));

    const pointMat = new THREE.PointsMaterial({
      size: 0.038,
      vertexColors: true,
      transparent: true,
      opacity: 0.9,
      depthWrite: false,
      sizeAttenuation: true,
    });
    const points = new THREE.Points(pointGeom, pointMat);
    scene.add(points);

    const edgeIndices: number[] = [];
    const groups: number[][] = [[], [], [], [], []];
    for (let k = 0; k < used; k++) groups[labels[k]].push(k);

    function pickTriangles(group: number[], count: number) {
      for (let t = 0; t < count; t++) {
        if (group.length < 3) break;
        const a = group[Math.floor(Math.random() * group.length)];
        const tries = 6;
        let b = -1,
          c = -1;
        let bd = 999,
          cd = 999;
        const ax = targets[a * 3],
          ay = targets[a * 3 + 1],
          az = targets[a * 3 + 2];
        for (let q = 0; q < tries; q++) {
          const cand = group[Math.floor(Math.random() * group.length)];
          if (cand === a) continue;
          const dx = targets[cand * 3] - ax;
          const dy = targets[cand * 3 + 1] - ay;
          const dz = targets[cand * 3 + 2] - az;
          const d = dx * dx + dy * dy + dz * dz;
          if (d < bd) {
            cd = bd;
            c = b;
            bd = d;
            b = cand;
          } else if (d < cd) {
            cd = d;
            c = cand;
          }
        }
        if (b >= 0 && c >= 0 && b !== c) {
          edgeIndices.push(a, b, b, c, c, a);
        }
      }
    }
    pickTriangles(groups[0], 90);
    pickTriangles(groups[1], 110);
    pickTriangles(groups[2], 120);
    pickTriangles(groups[3], 90);

    const edgePos = new Float32Array(edgeIndices.length * 3);
    const edgeCol = new Float32Array(edgeIndices.length * 3);
    for (let e = 0; e < edgeIndices.length; e++) {
      const idx = edgeIndices[e];
      edgePos[e * 3 + 0] = targets[idx * 3 + 0];
      edgePos[e * 3 + 1] = targets[idx * 3 + 1];
      edgePos[e * 3 + 2] = targets[idx * 3 + 2];
      const c = palette[labels[idx]] || palette[0];
      edgeCol[e * 3 + 0] = c[0];
      edgeCol[e * 3 + 1] = c[1];
      edgeCol[e * 3 + 2] = c[2];
    }
    const edgeGeom = new THREE.BufferGeometry();
    edgeGeom.setAttribute("position", new THREE.BufferAttribute(edgePos, 3));
    edgeGeom.setAttribute("color", new THREE.BufferAttribute(edgeCol, 3));
    const edgeMat = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0,
    });
    const edges = new THREE.LineSegments(edgeGeom, edgeMat);
    scene.add(edges);

    const pinSpec: { label: string; pos: [number, number, number] }[] = [
      { label: "couch", pos: [-1.2, 1.05, 1.0] },
      { label: "table", pos: [1.4, 0.95, -0.6] },
      { label: "floor", pos: [0.6, 0.05, 0.6] },
    ];
    const pins = pinSpec.map((p) => {
      const g = new THREE.SphereGeometry(0.045, 12, 12);
      const m = new THREE.MeshBasicMaterial({
        color: 0xffb347,
        transparent: true,
        opacity: 0,
      });
      const s = new THREE.Mesh(g, m);
      s.position.set(p.pos[0], p.pos[1], p.pos[2]);
      scene.add(s);
      const hg = new THREE.RingGeometry(0.07, 0.1, 24);
      const hm = new THREE.MeshBasicMaterial({
        color: 0xff9d6f,
        transparent: true,
        opacity: 0,
        side: THREE.DoubleSide,
      });
      const halo = new THREE.Mesh(hg, hm);
      halo.position.copy(s.position);
      scene.add(halo);
      return { core: s, halo, label: p.label, pos: p.pos };
    });

    const labelLayer = document.createElement("div");
    labelLayer.style.cssText =
      "position:absolute;inset:0;pointer-events:none;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;";
    host.appendChild(labelLayer);
    const labelEls = pinSpec.map((p) => {
      const el = document.createElement("div");
      el.textContent = p.label;
      el.style.cssText = [
        "position:absolute",
        "padding:2px 8px",
        "border:1px solid rgba(255,157,111,.45)",
        "background:rgba(38,21,32,.88)",
        "color:#ffd29c",
        "font-size:10px",
        "letter-spacing:.08em",
        "text-transform:uppercase",
        "border-radius:999px",
        "transform:translate(-50%,-50%)",
        "white-space:nowrap",
        "opacity:0",
        "transition:opacity 240ms ease",
        "backdrop-filter:blur(4px)",
      ].join(";");
      labelLayer.appendChild(el);
      return el;
    });

    function fit() {
      const r = host.getBoundingClientRect();
      renderer.setSize(r.width, r.height, false);
      camera.aspect = r.width / r.height || 1;
      camera.updateProjectionMatrix();
    }
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(host);

    const CYCLE_MS = 8000;
    const start = performance.now();
    let raf = 0;

    const tmpV = new THREE.Vector3();

    const easeOut = (t: number) => 1 - Math.pow(1 - t, 3);
    const smooth = (t: number) => t * t * (3 - 2 * t);

    function tick() {
      const now = performance.now();
      const elapsed = (now - start) % CYCLE_MS;
      const u = elapsed / CYCLE_MS;

      let aP = 0;
      if (u < 0.3) aP = easeOut(u / 0.3);
      else if (u < 0.95) aP = 1;
      else aP = 1 - smooth((u - 0.95) / 0.05);

      const posAttr = pointGeom.attributes.position as THREE.BufferAttribute;
      const arr = posAttr.array as Float32Array;
      for (let k = 0; k < used; k++) {
        const ox = origins[k * 3 + 0];
        const oy = origins[k * 3 + 1];
        const oz = origins[k * 3 + 2];
        const tx = targets[k * 3 + 0];
        const ty = targets[k * 3 + 1];
        const tz = targets[k * 3 + 2];
        const delay = (k % 12) / 60;
        const local = Math.max(0, Math.min(1, (u - delay) / 0.3));
        const a = u < 0.3 ? easeOut(local) : aP;
        arr[k * 3 + 0] = ox + (tx - ox) * a;
        arr[k * 3 + 1] = oy + (ty - oy) * a;
        arr[k * 3 + 2] = oz + (tz - oz) * a;
      }
      posAttr.needsUpdate = true;

      let eOp = 0;
      if (u >= 0.3 && u < 0.55) eOp = (u - 0.3) / 0.25;
      else if (u >= 0.55 && u < 0.8) eOp = 1 - (u - 0.55) / 0.5;
      else if (u >= 0.8 && u < 0.95) eOp = 0.5 - (u - 0.8) / 0.3;
      else eOp = 0;
      edgeMat.opacity = Math.max(0, Math.min(0.7, eOp));

      let splat = 0;
      if (u >= 0.55 && u < 0.95) splat = (u - 0.55) / 0.4;
      pointMat.size = 0.038 + 0.022 * smooth(splat);
      pointMat.opacity = 0.9 + 0.1 * splat;

      let pinOp = 0;
      if (u >= 0.7 && u < 0.95) pinOp = (u - 0.7) / 0.25;
      else if (u >= 0.95) pinOp = 1 - (u - 0.95) / 0.05;
      pinOp = Math.max(0, Math.min(1, pinOp));
      for (let p = 0; p < pins.length; p++) {
        (pins[p].core.material as THREE.MeshBasicMaterial).opacity = pinOp;
        (pins[p].halo.material as THREE.MeshBasicMaterial).opacity = pinOp * 0.5;
        pins[p].halo.scale.setScalar(1 + 0.6 * Math.sin(now * 0.004 + p));
        pins[p].halo.lookAt(camera.position);
      }

      const t = now * 0.00015;
      camera.position.x = Math.cos(t) * 7.0;
      camera.position.z = Math.sin(t) * 7.0;
      camera.position.y = 3.0 + Math.sin(t * 1.3) * 0.4;
      camera.lookAt(0, 0.4, 0);

      const r = host.getBoundingClientRect();
      for (let p = 0; p < pins.length; p++) {
        tmpV.set(pins[p].pos[0], pins[p].pos[1] + 0.18, pins[p].pos[2]);
        tmpV.project(camera);
        const x = (tmpV.x * 0.5 + 0.5) * r.width;
        const y = (-tmpV.y * 0.5 + 0.5) * r.height;
        labelEls[p].style.left = x + "px";
        labelEls[p].style.top = y + "px";
        labelEls[p].style.opacity = String(pinOp * 0.95);
      }

      renderer.render(scene, camera);
      raf = requestAnimationFrame(tick);
    }
    raf = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      renderer.dispose();
      pointGeom.dispose();
      edgeGeom.dispose();
      pointMat.dispose();
      edgeMat.dispose();
      pins.forEach((p) => {
        p.core.geometry.dispose();
        (p.core.material as THREE.Material).dispose();
        p.halo.geometry.dispose();
        (p.halo.material as THREE.Material).dispose();
      });
      if (renderer.domElement.parentNode === host) {
        host.removeChild(renderer.domElement);
      }
      if (labelLayer.parentNode === host) {
        host.removeChild(labelLayer);
      }
    };
  }, []);

  return (
    <div
      ref={ref}
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
      }}
    />
  );
}
