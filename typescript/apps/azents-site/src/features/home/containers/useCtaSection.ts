"use client";

import { trackCtaClick } from "@/shared/lib/analytics";
import { SITE_LINKS } from "@/shared/lib/links";

export interface CtaSectionViewProps {
  onGithub: () => void;
}

export function useCtaSection(): CtaSectionViewProps {
  return {
    onGithub: () =>
      trackCtaClick({
        ctaId: "final_cta_github",
        ctaLocation: "final_cta",
        destinationUrl: SITE_LINKS.github,
      }),
  };
}
