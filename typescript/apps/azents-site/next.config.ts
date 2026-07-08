import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  images: {
    unoptimized: true,
  },
  output: "export",
  reactStrictMode: true,
  trailingSlash: true,
};

export default withNextIntl(nextConfig);
