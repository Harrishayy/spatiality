import Link from "next/link";

export function LandingFooter() {
  return (
    <>
      <section id="upload" className="lp-section lp-cta-sec">
        <div className="lp-cta-card">
          <div className="lp-cta-grid" aria-hidden="true" />
          <div className="lp-cta-inner">
            <h2 className="lp-cta-title">
              <span className="lp-serif">Capture a space.</span>{" "}
              <span className="lp-serif lp-serif-accent">Walk away with a 3D twin.</span>
            </h2>
            <p className="lp-cta-sub">
              Spatiality is built for teams that move fast: robotics, AR/VR,
              field operations, and emergency response. Try it on your own
              walkthrough — or talk to us about deploying it inside your stack.
            </p>
            <div className="lp-hero-cta">
              <Link className="lp-btn lp-btn-primary lp-btn-lg" href="/upload">
                Capture a scene <span className="lp-btn-arrow">→</span>
              </Link>
              <Link
                className="lp-btn lp-btn-ghost lp-btn-lg"
                href="/demos"
              >
                Browse live demos
              </Link>
            </div>
          </div>
        </div>
      </section>

      <footer className="lp-footer">
        <div className="lp-footer-l">
          <div className="lp-brand-mark lp-brand-mark--sm" />
          <span className="lp-mono lp-muted">spatiality</span>
        </div>
        <div className="lp-footer-links">
          <Link href="/#pipeline">Pipeline</Link>
          <Link href="/demos">Live demo</Link>
          <Link href="/#industries">Use cases</Link>
          <Link href="/upload">Capture</Link>
        </div>
      </footer>
    </>
  );
}
