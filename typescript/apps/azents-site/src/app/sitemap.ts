import { SITE_URL } from "@/shared/lib/seo";
import type { MetadataRoute } from "next";

const SITE_LAUNCH_DATE = new Date("2026-07-07");

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    {
      changeFrequency: "weekly",
      lastModified: SITE_LAUNCH_DATE,
      priority: 1,
      url: SITE_URL,
    },
  ];
}
