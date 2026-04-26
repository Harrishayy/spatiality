import type { ReactNode } from "react";

export function SectionHeader({
  title,
  sub,
}: {
  title: ReactNode;
  sub?: string;
}) {
  return (
    <div className="lp-section-head">
      <h2 className="lp-section-title">{title}</h2>
      {sub ? <p className="lp-section-sub">{sub}</p> : null}
    </div>
  );
}
