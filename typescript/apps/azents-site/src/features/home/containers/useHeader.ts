"use client";
import { trackCtaClick } from "@/shared/lib/analytics";
import { SITE_LINKS } from "@/shared/lib/links";
export interface HeaderViewProps {
  onGithub: () => void;
  onMobileGithub: () => void;
}
export function useHeader(): HeaderViewProps {
  return {
    onGithub: () =>
      trackCtaClick({
        ctaId: "header_github",
        ctaLocation: "header",
        destinationUrl: SITE_LINKS.github,
      }),
    onMobileGithub: () =>
      trackCtaClick({
        ctaId: "header_mobile_github",
        ctaLocation: "header_mobile",
        destinationUrl: SITE_LINKS.github,
      }),
  };
}
