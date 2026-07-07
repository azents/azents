export interface PublicConfig {
  googleAnalyticsId: string | null;
}

export function getPublicConfig(): PublicConfig {
  const googleAnalyticsId = process.env.AZENTS_SITE_GOOGLE_ANALYTICS_ID?.trim();

  return {
    googleAnalyticsId:
      googleAnalyticsId && googleAnalyticsId.length > 0
        ? googleAnalyticsId
        : null,
  };
}
