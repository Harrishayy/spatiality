import { SectionHeader } from "./SectionHeader";

const MODULES = [
  { id: "01", name: "Capture", desc: "Frames + audio from .mp4 / Ray-Ban export.", file: "capture/", api: "→ frames/*.jpg" },
  { id: "02", name: "Inference (VGGT)", desc: "Dense surfels + camera poses, FP16, A100.", file: "inference/", api: "→ surfels.npz" },
  { id: "03", name: "Segmentation", desc: "SAM 3.1 masks, clustered to objects.", file: "segmentation/", api: "→ masks.npz" },
  { id: "04", name: "Object Isolation", desc: "Tap-to-isolate; label-anchored frustum.", file: "segmentation/iso", api: "→ object.ply" },
  { id: "05", name: "Storage", desc: "Filesystem-only. manifest.json is truth.", file: "shared/storage/", api: "↔ artifacts/" },
  { id: "06", name: "Web", desc: "Next.js 16 + Three.js viewer + chat.", file: "web/", api: "GET /api/jobs/:id" },
  { id: "07", name: "Agent", desc: "Pydantic AI Gateway → Anthropic.", file: "agent/", api: "POST /agent/locate" },
  { id: "08", name: "Observability", desc: "Logfire spans on every call.", file: "shared/obs/", api: "→ logfire" },
  { id: "09", name: "Deployment", desc: "Render web · Modal pipeline · R2 blobs.", file: "deploy/", api: "render.yaml" },
];

export function LandingModules() {
  return (
    <section id="docs" className="lp-section lp-modules-sec">
      <SectionHeader
        eyebrow="03 · architecture"
        title={
          <>
            Nine modules. <em>One contract.</em>
          </>
        }
        sub="Loose-coupling over the filesystem. Swap any module without touching the rest."
      />
      <div className="lp-module-grid">
        {MODULES.map((m) => (
          <div key={m.id} className="lp-module-card">
            <div className="lp-module-head">
              <span className="lp-mono lp-module-id">{m.id}</span>
              <span className="lp-module-name">{m.name}</span>
            </div>
            <p className="lp-module-desc">{m.desc}</p>
            <div className="lp-module-foot">
              <span className="lp-mono lp-muted">{m.file}</span>
              <span className="lp-mono lp-module-api">{m.api}</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
