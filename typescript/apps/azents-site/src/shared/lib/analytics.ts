import { SITE_LINKS } from "./links";

type AnalyticsPrimitive = boolean | number | string;

type AnalyticsEventParams = Record<string, AnalyticsPrimitive | null>;

interface CtaClickInput {
  ctaId: string;
  ctaLocation: string;
  destinationUrl: string;
}

interface SectionNavClickInput {
  targetSection: string;
}

interface LocaleChangeInput {
  fromLocale: string;
  toLocale: string;
}

function normalizeEventParams(
  params: AnalyticsEventParams,
): Record<string, AnalyticsPrimitive> {
  const normalizedParams: Record<string, AnalyticsPrimitive> = {};

  for (const [key, value] of Object.entries(params)) {
    if (value !== null) {
      normalizedParams[key] = value;
    }
  }

  return normalizedParams;
}

export function trackAnalyticsEvent(
  eventName: string,
  params: AnalyticsEventParams = {},
): void {
  if (typeof window === "undefined" || typeof window.gtag !== "function") {
    return;
  }

  window.gtag("event", eventName, normalizeEventParams(params));
}

export function trackCtaClick({
  ctaId,
  ctaLocation,
  destinationUrl,
}: CtaClickInput): void {
  trackAnalyticsEvent("cta_click", {
    cta_id: ctaId,
    cta_location: ctaLocation,
    destination_url: destinationUrl,
  });
}

export function trackDiscussionClick(ctaLocation: string): void {
  trackAnalyticsEvent("discussion_click", {
    cta_location: ctaLocation,
    destination_url: SITE_LINKS.issues,
  });
}

export function trackSectionNavClick({
  targetSection,
}: SectionNavClickInput): void {
  trackAnalyticsEvent("section_nav_click", {
    cta_location: "header",
    target_section: targetSection,
  });
}

export function trackLocaleChange({
  fromLocale,
  toLocale,
}: LocaleChangeInput): void {
  trackAnalyticsEvent("locale_change", {
    from_locale: fromLocale,
    to_locale: toLocale,
  });
}
