"use client";

import { Box } from "@mantine/core";
import { ArchitectureDeepDiveSection } from "./components/ArchitectureDeepDiveSection";
import { ArchitectureSection } from "./components/ArchitectureSection";
import { BootstrappingSection } from "./components/BootstrappingSection";
import { CtaSection } from "./components/CtaSection";
import { FeaturesSection } from "./components/FeaturesSection";
import { Header } from "./components/Header";
import { HeroSection } from "./components/HeroSection";
import { PageFooter } from "./components/PageFooter";
import { ProblemSection } from "./components/ProblemSection";
import { RoadmapSection } from "./components/RoadmapSection";
import { SelfHostedSection } from "./components/SelfHostedSection";

export function HomePage(): React.ReactElement {
  return (
    <Box bg="#070a0f" c="var(--mantine-color-dark-0)" mih="100dvh">
      <Header />
      <HeroSection />
      <ProblemSection />
      <SelfHostedSection />
      <ArchitectureSection />
      <ArchitectureDeepDiveSection />
      <BootstrappingSection />
      <FeaturesSection />
      <RoadmapSection />
      <CtaSection />
      <PageFooter />
    </Box>
  );
}
