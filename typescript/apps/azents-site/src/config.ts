export interface PublicConfig {
  siteGoogleAnalyticsId: string | null;
}

export function getPublicConfig(): PublicConfig {
  const siteGoogleAnalyticsId = process.env.SITE_GOOGLE_ANALYTICS_ID?.trim();

  return {
    siteGoogleAnalyticsId:
      siteGoogleAnalyticsId && siteGoogleAnalyticsId.length > 0
        ? siteGoogleAnalyticsId
        : null,
  };
}
