import { LandingHeader } from "@/components/landing/Header";
import { LandingHero } from "@/components/landing/Hero";
import { LandingPipeline } from "@/components/landing/Pipeline";
import { LandingViewer } from "@/components/landing/Viewer";
import { LandingModules } from "@/components/landing/Modules";
import { LandingFooter } from "@/components/landing/Footer";

export default function Home() {
  return (
    <>
      <LandingHeader />
      <LandingHero />
      <main className="lp-main">
        <LandingPipeline />
        <LandingViewer />
        <LandingModules />
        <LandingFooter />
      </main>
    </>
  );
}
