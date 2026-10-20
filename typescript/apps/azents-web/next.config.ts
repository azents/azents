import { withSentryConfig } from "@sentry/nextjs/config";
import createNextIntlPlugin from "next-intl/plugin";
import { getBuildConfig } from "./src/config/build";
import type { NextConfig } from "next";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");
const buildConfig = getBuildConfig();

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone",
  allowedDevOrigins: ["127.0.0.1"],
};

export default withSentryConfig(withNextIntl(nextConfig), {
  // Upload source maps only when SENTRY_AUTH_TOKEN is available.
  org: buildConfig.sentryOrg,
  project: buildConfig.sentryProject,
  authToken: buildConfig.sentryAuthToken,

  // Remove client source maps after Sentry uploads them.
  sourcemaps: {
    deleteSourcemapsAfterUpload: true,
  },

  // Hide Sentry configuration warnings during local development.
  silent: buildConfig.silentSentry,

  // Disable Sentry telemetry.
  telemetry: false,
});
