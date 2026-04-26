import Link from "next/link";
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
        <h1 className="lp-hero-title">
          <span className="lp-serif">Fast inference</span>
          <br />
          <span className="lp-serif lp-serif-accent">3D meshes.</span>{" "}
          <span className="lp-sans">Built for prototyping.</span>
        </h1>

        <p className="lp-hero-sub">
          Capture with Ray-Ban Meta glasses. Reconstruct your view in seconds.
          <br />
          Production-grade 3D twins for robotics, AR, VR, and frontline response —
          on demand, at the speed of decisions.
        </p>

        <div className="lp-hero-cta">
          <Link className="lp-btn lp-btn-primary lp-btn-lg" href="/upload">
            Capture a scene
            <span className="lp-btn-arrow">→</span>
          </Link>
          <Link className="lp-btn lp-btn-ghost lp-btn-lg" href="/demos">
            Browse live demos
          </Link>
          <span className="lp-hero-meta">
            <span className="lp-mono">~90s end-to-end · runs from any phone</span>
          </span>
        </div>

        <div className="lp-hero-stats">
          <Stat label="reconstruction" value="<90s" unit="end-to-end" />
          <Stat label="spatial query" value="≤3s" unit="round-trip" />
          <Stat label="rendered at" value="60fps" unit="any device" />
          <Stat label="deployments" value="cloud" unit="or on-prem" />
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
