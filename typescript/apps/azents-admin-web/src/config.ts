import "server-only";
import { z } from "zod/v4";

const PublicConfigSchema = z.object({
  publicBaseUrl: z.string().url(),
});

export type PublicConfig = z.infer<typeof PublicConfigSchema>;

function loadPublicConfig(): PublicConfig {
  return PublicConfigSchema.parse({
    publicBaseUrl: process.env.PUBLIC_BASE_URL ?? "http://localhost:3002",
  });
}

let cachedPublicConfig: PublicConfig | null = null;

export function getPublicConfig(): PublicConfig {
  if (!cachedPublicConfig) {
    cachedPublicConfig = loadPublicConfig();
  }
  return cachedPublicConfig;
}
