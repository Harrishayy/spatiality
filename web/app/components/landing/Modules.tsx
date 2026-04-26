import { SectionHeader } from "./SectionHeader";

type Industry = {
  id: string;
  name: string;
  pitch: string;
  detail: string;
};

const INDUSTRIES: Industry[] = [
  {
    id: "01",
    name: "Robotics",
    pitch: "Geometry-grounded environments at the speed of iteration.",
    detail:
      "Capture with a phone, GoPro, or smart glasses; export a metric, mesh-ready 3D file straight into Isaac Sim, Gazebo, Unity, or Unreal the same morning. No rigs, no scan stations.",
  },
  {
    id: "02",
    name: "Augmented reality",
    pitch: "Anchor experiences to physical space, the day a venue is built.",
    detail:
      "Reconstruct any room into a 3D mesh you can drop into ARKit, ARCore, or Unity for spatial placement, occlusion, and interaction prototyping — without booking a Lidar crew or rebuilding rooms in DCC tools.",
  },
  {
    id: "03",
    name: "Virtual reality",
    pitch: "Stand up real-world locations in your engine, in minutes.",
    detail:
      "Author location-based VR from on-site capture. Outputs are clean meshes ready to import into Unity or Unreal — compact enough to stream to a headset on the same network.",
  },
  {
    id: "04",
    name: "Emergency response",
    pitch: "First-on-scene situational awareness, before the first responder.",
    detail:
      "A walkthrough from any handheld or body-worn camera delivers a measurable, labeled 3D mesh to incident command in seconds — exportable for search planning, hazard assessment, and after-action review.",
  },
  {
    id: "05",
    name: "Industrial & field",
    pitch: "As-built capture without scheduling a survey team.",
    detail:
      "Use any lightweight handheld or wearable camera for asset inspection, retrofit planning, and remote review. Every reconstruction exports as a portable 3D file — traceable, versioned, and ready for your CAD or BIM stack.",
  },
  {
    id: "06",
    name: "Spatial AI research",
    pitch: "A reproducible, instrumented pipeline you can extend.",
    detail:
      "Every stage is observable and swappable. Plug in new reconstruction or segmentation models without rebuilding the surrounding infrastructure.",
  },
];

export function LandingIndustries() {
  return (
    <section id="industries" className="lp-section lp-modules-sec">
      <SectionHeader
        title={
          <>
            Spatial intelligence, <em>where decisions happen</em>.
          </>
        }
        sub="Wherever physical space meets a deadline — robotics, AR/VR, frontline response, field operations — fast inference of a real, measurable 3D world is the unlock."
      />
      <div className="lp-module-grid">
        {INDUSTRIES.map((m) => (
          <div key={m.id} className="lp-module-card">
            <div className="lp-module-head">
              <span className="lp-mono lp-module-id">{m.id}</span>
              <span className="lp-module-name">{m.name}</span>
            </div>
            <p className="lp-module-pitch">{m.pitch}</p>
            <p className="lp-module-desc">{m.detail}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
