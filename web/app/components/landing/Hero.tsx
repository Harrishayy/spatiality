import Link from "next/link";
import { DEMO_SCENE_ID } from "@/lib/api";
import { MeshHero } from "./MeshHero";

export function LandingHero() {
  return (
    <section className="lp-hero">
      <div className="lp-hero-canvas">
        <MeshHero />
      </div>
      <div className="lp-hero-grid" aria-hidden="true" />
      <div className="lp-hero-vignette" aria-hidden="true" />

      <div className="lp-hero-inner">
        <div className="lp-hero-top">
          <div className="lp-stack-rail" role="list" aria-label="powered by">
            <span className="lp-stack-rail-label lp-mono">Powered by</span>
            <span className="lp-stack-rail-sep" aria-hidden="true" />
            <span className="lp-stack-item" role="listitem">
              <span className="lp-stack-glyph lp-stack-glyph--coral" />
              VGGT
              <span className="lp-stack-item-sub lp-mono">surfels</span>
            </span>
            <span className="lp-stack-rail-dot" aria-hidden="true" />
            <span className="lp-stack-item" role="listitem">
              <span className="lp-stack-glyph lp-stack-glyph--gold" />
              SAM
              <span className="lp-stack-item-sub lp-mono">3.1</span>
            </span>
            <span className="lp-stack-rail-dot" aria-hidden="true" />
            <span className="lp-stack-item" role="listitem">
              <span className="lp-stack-glyph lp-stack-glyph--magenta" />
              Pydantic
              <span className="lp-stack-item-sub lp-mono">AI Gateway</span>
            </span>
            <span className="lp-stack-rail-dot" aria-hidden="true" />
            <span className="lp-stack-item" role="listitem">
              <span className="lp-stack-glyph lp-stack-glyph--amber" />
              Three.js
              <span className="lp-stack-item-sub lp-mono">+ splats</span>
            </span>
          </div>
        </div>

        <h1 className="lp-hero-title">
          <span className="lp-serif">Walk through</span>
          <br />
          <span className="lp-serif lp-serif-accent">your room.</span>{" "}
          <span className="lp-sans">Talk to it.</span>
        </h1>

        <p className="lp-hero-sub">
          Capture with Ray-Ban glasses. Reconstruct in seconds.
          <br />
          Ask the room where you are — and what you&apos;re looking at.
        </p>

        <div className="lp-hero-cta">
          <Link className="lp-btn lp-btn-primary lp-btn-lg" href="/upload">
            Upload a video
            <span className="lp-btn-arrow">→</span>
          </Link>
          <Link
            className="lp-btn lp-btn-ghost lp-btn-lg"
            href={`/scenes/${DEMO_SCENE_ID}`}
          >
            View live demo scene
          </Link>
          <span className="lp-hero-meta">
            <span className="lp-mono">~90s end-to-end · iPhone Safari</span>
          </span>
        </div>

        <div className="lp-hero-stats">
          <Stat label="reconstructed" value="2.4M" unit="surfels" />
          <Stat label="round-trip" value="≤3s" unit="where am I" />
          <Stat label="rendered at" value="60fps" unit="iPhone 13+" />
          <Stat label="modules" value="9" unit="swappable" />
        </div>
      </div>

      <div className="lp-hero-fade" aria-hidden="true" />
    </section>
  );
}

function Stat({
  label,
  value,
  unit,
}: {
  label: string;
  value: string;
  unit: string;
}) {
  return (
    <div className="lp-stat">
      <div className="lp-stat-label">{label}</div>
      <div className="lp-stat-value">
        {value} <span className="lp-stat-unit">{unit}</span>
      </div>
    </div>
  );
}
