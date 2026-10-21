/** Build-only inputs, independent of the server-only runtime initializer. */
export interface BuildConfig {
  sentryOrg?: string;
  sentryProject?: string;
  sentryAuthToken?: string;
  silentSentry: boolean;
}

export function getBuildConfig(): BuildConfig {
  return {
    sentryOrg: process.env.SENTRY_ORG,
    sentryProject: process.env.SENTRY_PROJECT,
    sentryAuthToken: process.env.SENTRY_AUTH_TOKEN,
    silentSentry: !process.env.CI,
  };
}
