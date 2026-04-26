"use client";

import { useEffect, useState, type ReactNode } from "react";
import { SectionHeader } from "./SectionHeader";

type ChatMessage = { role: "user" | "agent"; text: string; meta: string };

export function LandingViewer() {
  return (
    <section id="viewer" className="lp-section lp-viewer-sec">
      <SectionHeader
        eyebrow="02 · viewer"
        title={
          <>
            Drag to orbit. Pinch to zoom.
            <br />
            Tap a label, isolate the object.
          </>
        }
        sub="The same gaussian-splats-3d viewer that ships in /web. Annotations are 3D-anchored billboards; chat is camera-aware."
      />

      <div className="lp-viewer-frame">
        <ViewerCanvas />
        <ChatPanel />
      </div>
    </section>
  );
}

function ViewerCanvas() {
  return (
    <div className="lp-viewer-canvas">
      <div className="lp-viewer-bg" aria-hidden="true">
        <div className="lp-viewer-noise" />
        <ViewerGrid />
      </div>

      <div className="lp-viewer-chrome lp-viewer-chrome--top">
        <span className="lp-status-pill lp-status-pill--ok">
          <span className="lp-status-dot lp-status-dot--ok" />
          ready
        </span>
        <span className="lp-mono lp-muted">living_room_03</span>
        <div className="lp-viewer-chips">
          <ModeChip active>orbit</ModeChip>
          <ModeChip>pan</ModeChip>
          <ModeChip>isolate</ModeChip>
        </div>
      </div>

      <Annotations />

      <div className="lp-viewer-chrome lp-viewer-chrome--bottom">
        <button className="lp-btn lp-btn-primary lp-where">
          <span className="lp-where-pulse" />
          Where am I?
        </button>
        <span className="lp-mono lp-muted">cam · (1.20, 1.65, 2.40)</span>
      </div>
    </div>
  );
}

function ViewerGrid() {
  const dotPositions = Array.from({ length: 90 }, (_, i) => {
    const x = (i * 137) % 1200;
    const y = 100 + ((i * 53) % 560);
    const r = 1 + ((i * 7) % 3);
    const palette = ["#ff9d6f", "#ffd29c", "#ff5d8f", "#ffb347", "#e6b9a3"];
    return {
      x,
      y,
      r,
      fill: palette[i % palette.length],
      opacity: 0.18 + ((i * 13) % 30) / 100,
    };
  });

  return (
    <svg
      className="lp-viewer-room"
      viewBox="0 0 1200 700"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="floorG" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#3d1f2c" />
          <stop offset="100%" stopColor="#1a0e14" />
        </linearGradient>
        <linearGradient id="wallG" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#ff9d6f" stopOpacity="0.35" />
          <stop offset="40%" stopColor="#ff5d8f" stopOpacity="0.22" />
          <stop offset="100%" stopColor="#26152a" />
        </linearGradient>
        <radialGradient id="splatG">
          <stop offset="0%" stopColor="#ff9d6f" stopOpacity="0.6" />
          <stop offset="100%" stopColor="#ff9d6f" stopOpacity="0" />
        </radialGradient>
        <pattern
          id="floorDots"
          x="0"
          y="0"
          width="36"
          height="36"
          patternUnits="userSpaceOnUse"
        >
          <circle cx="2" cy="2" r="1" fill="#6d4651" opacity="0.6" />
        </pattern>
      </defs>

      <polygon points="0,0 1200,0 1200,420 0,420" fill="url(#wallG)" />
      <polygon
        points="0,420 1200,420 1200,700 0,700"
        fill="url(#floorG)"
      />
      <polygon
        points="0,420 1200,420 1200,700 0,700"
        fill="url(#floorDots)"
        opacity="0.6"
      />

      <g opacity="0.92">
        <ellipse cx="370" cy="540" rx="220" ry="36" fill="#000" opacity="0.5" />
        <rect x="170" y="420" width="400" height="120" rx="14" fill="#4a2536" stroke="#6d3548" strokeWidth="1" />
        <rect x="170" y="380" width="400" height="60" rx="12" fill="#5a2c40" stroke="#6d3548" strokeWidth="1" />
      </g>

      <g opacity="0.92">
        <ellipse cx="900" cy="560" rx="160" ry="22" fill="#000" opacity="0.45" />
        <rect x="760" y="470" width="280" height="14" rx="3" fill="#5a3142" stroke="#6d3548" strokeWidth="1" />
        <rect x="775" y="484" width="6" height="80" fill="#3a1f2c" />
        <rect x="1020" y="484" width="6" height="80" fill="#3a1f2c" />
      </g>

      <circle cx="370" cy="450" r="220" fill="url(#splatG)" />
      <circle cx="900" cy="500" r="160" fill="url(#splatG)" opacity="0.7" />

      {dotPositions.map((d, i) => (
        <circle
          key={i}
          cx={d.x}
          cy={d.y}
          r={d.r}
          fill={d.fill}
          opacity={d.opacity}
        />
      ))}
    </svg>
  );
}

function Annotations() {
  const pins = [
    { label: "couch", x: 28, y: 60, sub: "0.96" },
    { label: "coffee table", x: 73, y: 67, sub: "0.91" },
    { label: "wall · north", x: 50, y: 26, sub: "0.99" },
    { label: "rug", x: 42, y: 86, sub: "0.84" },
  ];
  return (
    <>
      {pins.map((p, i) => (
        <div
          key={i}
          className="lp-pin"
          style={{ left: p.x + "%", top: p.y + "%" }}
        >
          <span className="lp-pin-core" />
          <span className="lp-pin-halo" />
          <span className="lp-pin-label">
            <span className="lp-mono">{p.label}</span>
            <span className="lp-mono lp-muted">· conf {p.sub}</span>
          </span>
        </div>
      ))}
    </>
  );
}

function ModeChip({
  children,
  active,
}: {
  children: ReactNode;
  active?: boolean;
}) {
  return (
    <span
      className={
        "lp-mode-chip lp-mono" + (active ? " lp-mode-chip--on" : "")
      }
    >
      {children}
    </span>
  );
}

function ChatPanel() {
  const [msgs, setMsgs] = useState<ChatMessage[]>([
    {
      role: "user",
      text: "where am I right now?",
      meta: "cam · (1.20, 1.65, 2.40)",
    },
    {
      role: "agent",
      text:
        "You're standing roughly in the centre of the living room, facing the north wall. The grey couch is about 1.2m to your left; the coffee table is 1.8m ahead and slightly right.",
      meta: "haiku-4-5 · 1.94s · 3 nearby",
    },
    {
      role: "user",
      text: "what's that on the table?",
      meta: "frustum: 5 obj",
    },
  ]);
  const [typing, setTyping] = useState(true);

  useEffect(() => {
    const timers: ReturnType<typeof setTimeout>[] = [];
    timers.push(
      setTimeout(() => {
        setTyping(false);
        setMsgs((m) => [
          ...m,
          {
            role: "agent",
            text:
              "Closest match: a ceramic mug, then a paperback book and a pair of glasses. The mug has the highest mask confidence (0.92).",
            meta: "haiku-4-5 · 1.71s · 5 nearby",
          },
        ]);
      }, 2200),
    );
    timers.push(
      setTimeout(() => {
        setMsgs((m) => [
          ...m,
          { role: "user", text: "isolate the couch", meta: "tap → label" },
        ]);
      }, 4200),
    );
    return () => timers.forEach(clearTimeout);
  }, []);

  return (
    <aside className="lp-chat">
      <div className="lp-chat-head">
        <h4 className="lp-chat-title">Agent</h4>
        <span className="lp-mono lp-muted">/api/agent/locate</span>
      </div>
      <div className="lp-chat-body">
        {msgs.map((m, i) => (
          <Bubble key={i} m={m} />
        ))}
        {typing ? (
          <div className="lp-bubble lp-bubble--agent">
            <div className="lp-typing">
              <span /> <span /> <span />
            </div>
          </div>
        ) : null}
      </div>
      <div className="lp-chat-input">
        <span className="lp-mono lp-muted">›</span>
        <span className="lp-mono lp-muted">ask the room…</span>
        <button className="lp-mic" aria-label="voice">
          <svg viewBox="0 0 24 24" width="14" height="14">
            <rect x="9" y="3" width="6" height="12" rx="3" fill="currentColor" />
            <path
              d="M5 11a7 7 0 0 0 14 0"
              stroke="currentColor"
              strokeWidth="1.5"
              fill="none"
            />
            <line
              x1="12"
              y1="18"
              x2="12"
              y2="22"
              stroke="currentColor"
              strokeWidth="1.5"
            />
          </svg>
        </button>
      </div>
    </aside>
  );
}

function Bubble({ m }: { m: ChatMessage }) {
  return (
    <div className={"lp-bubble lp-bubble--" + m.role}>
      <div className="lp-bubble-text">{m.text}</div>
      <div className="lp-bubble-meta lp-mono">{m.meta}</div>
    </div>
  );
}
