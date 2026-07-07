import { AZENTS_BRAND } from "./brand";
import { SITE_LINKS } from "./links";
import { type SupportedLocale } from "./locale";

export const SITE_URL = "https://azents.io";
export const SITE_NAME = "Azents";

export const SEO_KEYWORDS = [
  "Azents",
  "managed agents",
  "remote agents",
  "agent runtime",
  "agent control plane",
  "self-hosted agents",
  "open source agents",
  "developer infrastructure",
  "AI coding agents",
];

export const LOCALE_TO_OG_LOCALE: Record<SupportedLocale, string> = {
  "en-US": "en_US",
  "fr-FR": "fr_FR",
  "ja-JP": "ja_JP",
  "ko-KR": "ko_KR",
};

export const OG_IMAGE = {
  alt: "Azents - managed agents inside your cloud",
  height: 630,
  url: AZENTS_BRAND.openGraphImage,
  width: 1200,
} as const;

export const STRUCTURED_DATA = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  applicationCategory: "DeveloperApplication",
  codeRepository: SITE_LINKS.github,
  description:
    "Azents is an open-source control plane for managed agent runtimes in your cloud.",
  image: `${SITE_URL}${AZENTS_BRAND.openGraphImage}`,
  isAccessibleForFree: true,
  license: `${SITE_LINKS.github}/blob/main/LICENSE`,
  name: SITE_NAME,
  operatingSystem: "Cloud, Linux, macOS",
  sameAs: [SITE_LINKS.github, SITE_LINKS.issues],
  url: SITE_URL,
} as const;
