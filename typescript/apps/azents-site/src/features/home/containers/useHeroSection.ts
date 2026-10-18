"use client";
import { trackCtaClick } from "@/shared/lib/analytics";
import { SITE_LINKS } from "@/shared/lib/links";
export interface HeroSectionViewProps {
  onGithub: () => void;
}
export function useHeroSection(): HeroSectionViewProps {
  return {
    onGithub: () =>
      trackCtaClick({
        ctaId: "hero_github",
        ctaLocation: "hero",
        destinationUrl: SITE_LINKS.github,
      }),
  };
}
