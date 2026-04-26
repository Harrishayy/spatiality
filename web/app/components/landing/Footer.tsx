import Link from "next/link";
import { DEMO_SCENE_ID } from "@/lib/api";

export function LandingFooter() {
  return (
    <>
      <section id="upload" className="lp-section lp-cta-sec">
        <div className="lp-cta-card">
          <div className="lp-cta-grid" aria-hidden="true" />
          <div className="lp-cta-inner">
            <span className="lp-eyebrow lp-mono">
              <span className="lp-eyebrow-dot" aria-hidden="true" />
              04 · ship it
            </span>
            <h2 className="lp-cta-title">
              <span className="lp-serif">Bring a video.</span>{" "}
              <span className="lp-serif lp-serif-accent">Leave with a twin.</span>
            </h2>
            <p className="lp-cta-sub">
              Mobile-first. Works on iPhone Safari, Pixel, desktop. No accounts, no setup.
            </p>
            <div className="lp-hero-cta">
              <Link className="lp-btn lp-btn-primary lp-btn-lg" href="/upload">
                Drop a video <span className="lp-btn-arrow">→</span>
              </Link>
              <Link
                className="lp-btn lp-btn-ghost lp-btn-lg"
                href={`/scenes/${DEMO_SCENE_ID}`}
              >
                View demo scene
              </Link>
            </div>
          </div>
        </div>
      </section>

      <footer className="lp-footer">
        <div className="lp-footer-l">
          <div className="lp-brand-mark lp-brand-mark--sm" />
          <span className="lp-mono lp-muted">
            spatiality · render branch · v0.4.2
          </span>
        </div>
        <div className="lp-footer-links lp-mono">
          <a href="https://github.com" target="_blank" rel="noreferrer">
            github
          </a>
          <Link href="/design-system">design-system</Link>
          <a href="#pipeline">logfire</a>
          <a href="#docs">CLAUDE.md</a>
        </div>
      </footer>
    </>
  );
}
