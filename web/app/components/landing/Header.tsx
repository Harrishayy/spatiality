import Link from "next/link";

export function LandingHeader() {
  return (
    <header className="lp-header">
      <div className="lp-header-l">
        <Link className="lp-brand" href="/">
          <div className="lp-brand-mark" />
          <span className="lp-brand-title">Spatiality</span>
        </Link>
      </div>

      <nav className="lp-nav" aria-label="primary">
        <Link href="/#pipeline">Pipeline</Link>
        <Link href="/demos">Live demo</Link>
        <Link href="/#industries">Use cases</Link>
      </nav>

      <div className="lp-header-r">
        <Link className="lp-btn lp-btn-ghost lp-btn-sm" href="/demos">
          Live demo
        </Link>
        <Link className="lp-btn lp-btn-primary lp-btn-sm" href="/upload">
          Capture a scene
          <span className="lp-btn-arrow">→</span>
        </Link>
      </div>
    </header>
  );
}
