"use client";

/**
 * Home page entry point.
 *
 * Dark mode is applied with forceColorScheme="dark" in (landing) root layout,
 * so no separate color scheme override is needed inside component.
 */
import { Box } from "@mantine/core";
import { CtaSection } from "./components/CtaSection";
import { FeaturesSection } from "./components/FeaturesSection";
import { Header } from "./components/Header";
import { HeroSection } from "./components/HeroSection";
import { PageFooter } from "./components/PageFooter";
import { UseCasesSection } from "./components/UseCasesSection";

export function HomePage(): React.ReactElement {
  return (
    <Box
      style={{
        backgroundColor: "var(--mantine-color-body)",
        minHeight: "100dvh",
      }}
    >
      <Header />
      <HeroSection />
      <FeaturesSection />
      <UseCasesSection />
      <CtaSection />
      <PageFooter />
    </Box>
  );
}
