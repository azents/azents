import { AZENTS_BRAND } from "@/shared/lib/brand";
import { SITE_NAME } from "@/shared/lib/seo";
import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    background_color: "#070a0f",
    description:
      "Open-source control plane for managed agent runtimes in your cloud.",
    display: "standalone",
    icons: [
      {
        sizes: "32x32",
        src: "/brand/azents/favicon-32.png",
        type: "image/png",
      },
      {
        sizes: "4096x4096",
        src: AZENTS_BRAND.icon,
        type: "image/png",
      },
    ],
    name: SITE_NAME,
    short_name: SITE_NAME,
    start_url: "/",
    theme_color: "#070a0f",
  };
}
