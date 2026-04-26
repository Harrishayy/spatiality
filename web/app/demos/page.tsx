"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { LandingHeader } from "@/components/landing/Header";
import { LandingFooter } from "@/components/landing/Footer";
import { DemoPattern } from "@/components/DemoPattern";
import { fetchScenes, type SceneSummary } from "@/lib/api";

type LoadState =
  | { kind: "loading" }
  | { kind: "ok"; scenes: SceneSummary[] }
  | { kind: "err"; msg: string };

export default function DemosPage() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    let alive = true;
    fetchScenes()
      .then((scenes) => {
        if (alive) setState({ kind: "ok", scenes });
      })
      .catch((err: Error) => {
        if (alive) setState({ kind: "err", msg: err.message });
      });
    return () => {
      alive = false;
    };
  }, []);

  return (
    <>
      <LandingHeader />

      <section className="lp-demos-page">
        <div className="lp-demos-page-inner">
          <header className="lp-demos-page-head">
            <h1 className="lp-demos-page-title">
              <span className="lp-serif">Walk through</span>{" "}
              <span className="lp-serif lp-serif-accent">a real reconstruction.</span>
            </h1>
            <p className="lp-demos-page-sub">
              Every scene below was captured from a single walkthrough and
              reconstructed end-to-end — same pipeline, any camera. Pick one to
              explore — point cloud, segmentation, chat, the works.
            </p>
          </header>

          <DemosBody state={state} />
        </div>
      </section>

      <LandingFooter />
    </>
  );
}

function DemosBody({ state }: { state: LoadState }) {
  if (state.kind === "loading") {
    return (
      <div className="lp-demos-page-grid">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="lp-demo-card lp-demo-card--skel" />
        ))}
      </div>
    );
  }

  if (state.kind === "err") {
    return (
      <div className="lp-demos-page-empty">
        <p>
          Couldn&rsquo;t load the gallery just now. Give it a moment and try
          again.
        </p>
      </div>
    );
  }

  if (state.scenes.length === 0) {
    return (
      <div className="lp-demos-page-empty">
        <p>
          Nothing here yet — capture your first scene to see it appear.
        </p>
      </div>
    );
  }

  return (
    <div className="lp-demos-page-grid">
      {state.scenes.map((s) => (
        <DemoCard key={s.scene_id} scene={s} />
      ))}
    </div>
  );
}

function DemoCard({ scene }: { scene: SceneSummary }) {
  return (
    <Link
      href={`/scenes/${encodeURIComponent(scene.scene_id)}`}
      className="lp-demo-card"
    >
      <div className="lp-demo-card-thumb">
        <DemoPattern seed={scene.scene_id} />
        {scene.status && (
          <span
            className={[
              "lp-demo-card-status",
              `lp-demo-card-status--${
                scene.status === "ready"
                  ? "ok"
                  : scene.status === "failed"
                    ? "err"
                    : "warn"
              }`,
            ].join(" ")}
          >
            {scene.status}
          </span>
        )}
      </div>

      <div className="lp-demo-card-body">
        <div className="lp-demo-card-title">{scene.scene_id}</div>
        <div className="lp-demo-card-stats">
          <Stat label="frames" value={fmtNum(scene.stats?.frame_count)} />
          <Stat label="objects" value={fmtNum(scene.stats?.object_count)} />
          <Stat
            label="pipeline"
            value={
              scene.total_duration_s != null
                ? `${scene.total_duration_s.toFixed(1)}s`
                : "—"
            }
          />
        </div>
        <div className="lp-demo-card-foot">
          <span className="lp-demo-card-when">
            {scene.created_at
              ? new Date(scene.created_at).toLocaleDateString(undefined, {
                  month: "short",
                  day: "numeric",
                  year: "numeric",
                })
              : "—"}
          </span>
          <span className="lp-demo-card-cta">
            Open viewer <span className="lp-btn-arrow">→</span>
          </span>
        </div>
      </div>
    </Link>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="lp-demo-card-stat">
      <div className="lp-demo-card-stat-value">{value}</div>
      <div className="lp-demo-card-stat-label">{label}</div>
    </div>
  );
}

function fmtNum(n: number | undefined): string {
  if (n == null) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}
