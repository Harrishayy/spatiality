import type { ReactNode } from "react";

export function SectionHeader({
  eyebrow,
  title,
  sub,
}: {
  eyebrow: string;
  title: ReactNode;
  sub?: string;
}) {
  return (
    <div className="lp-section-head">
      <span className="lp-eyebrow lp-mono">
        <span className="lp-eyebrow-dot" aria-hidden="true" />
        {eyebrow}
      </span>
      <h2 className="lp-section-title">{title}</h2>
      {sub ? <p className="lp-section-sub">{sub}</p> : null}
    </div>
  );
}
