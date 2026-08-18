import { withSentryConfig } from "@sentry/nextjs";
import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone",
  allowedDevOrigins: ["127.0.0.1"],
};

export default withSentryConfig(withNextIntl(nextConfig), {
  // Upload source maps only when SENTRY_AUTH_TOKEN is available.
  org: process.env.SENTRY_ORG,
  project: process.env.SENTRY_PROJECT,
  authToken: process.env.SENTRY_AUTH_TOKEN,

  // Remove client source maps after Sentry uploads them.
  sourcemaps: {
    deleteSourcemapsAfterUpload: true,
  },

  // Hide Sentry configuration warnings during local development.
  silent: !process.env.CI,

  // Disable Sentry telemetry.
  telemetry: false,
});
