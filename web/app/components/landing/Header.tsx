import Link from "next/link";
import { DEMO_SCENE_ID } from "@/lib/api";

export function LandingHeader() {
  return (
    <header className="lp-header">
      <div className="lp-header-l">
        <Link className="lp-brand" href="/">
          <div className="lp-brand-mark" />
          <span className="lp-brand-title">Spatiality</span>
        </Link>
        <span className="lp-brand-divider" aria-hidden="true" />
        <span className="lp-mono lp-muted lp-brand-tag">
          glasses → 3D twin
        </span>
      </div>

      <nav className="lp-nav" aria-label="primary">
        <a href="#pipeline">Pipeline</a>
        <a href="#viewer">Viewer</a>
        <a href="#docs">Modules</a>
        <Link href="/design-system">Docs</Link>
        <span className="lp-nav-divider" aria-hidden="true" />
        <a href="#changelog" className="lp-nav-meta">
          <span className="lp-nav-meta-dot" />
          v0.4.2
        </a>
      </nav>

      <div className="lp-header-r">
        <Link
          className="lp-btn lp-btn-ghost lp-btn-sm"
          href={`/scenes/${DEMO_SCENE_ID}`}
        >
          Live demo
        </Link>
        <Link className="lp-btn lp-btn-primary lp-btn-sm" href="/upload">
          Upload video
          <span className="lp-btn-arrow">→</span>
        </Link>
      </div>
    </header>
  );
}
