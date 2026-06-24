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
  // t t SENTRY_AUTH_TOKENt t sourcemap upload
  org: process.env.SENTRY_ORG,
  project: process.env.SENTRY_PROJECT,
  authToken: process.env.SENTRY_AUTH_TOKEN,

  // client bundlet sourcemap remove (Sentryt upload)
  sourcemaps: {
    deleteSourcemapsAfterUpload: true,
  },

  // local development t Sentry warning hide
  silent: !process.env.CI,

  // Telemetry disable
  telemetry: false,
});
