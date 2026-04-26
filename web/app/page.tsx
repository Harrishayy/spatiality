import { LandingHeader } from "@/components/landing/Header";
import { LandingHero } from "@/components/landing/Hero";
import { LandingPipeline } from "@/components/landing/Pipeline";
import { LandingIndustries } from "@/components/landing/Modules";
import { LandingFooter } from "@/components/landing/Footer";

export default function Home() {
  return (
    <>
      <LandingHeader />
      <LandingHero />
      <main className="lp-main">
        <LandingPipeline />
        <LandingIndustries />
        <LandingFooter />
      </main>
    </>
  );
}
