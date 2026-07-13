import "server-only";
import { z } from "zod/v4";

const PublicConfigSchema = z.object({
  baseUrl: z.string().url(),
});

export type PublicConfig = z.infer<typeof PublicConfigSchema>;

function loadPublicConfig(): PublicConfig {
  return PublicConfigSchema.parse({
    baseUrl: process.env.BASE_URL ?? "http://localhost:3002",
  });
}

let cachedPublicConfig: PublicConfig | null = null;

export function getPublicConfig(): PublicConfig {
  if (!cachedPublicConfig) {
    cachedPublicConfig = loadPublicConfig();
  }
  return cachedPublicConfig;
}
