import "server-only";
import { z } from "zod/v4";

// --- Public Config (서버에서만 로드, 클라이언트는 Context로 접근) ---
const PublicConfigSchema = z.object({
  authEnabled: z.boolean(),
  baseUrl: z.string(),
});

export type PublicConfig = z.infer<typeof PublicConfigSchema>;

// --- Helper ---
function parseBooleanEnv(value?: string): boolean {
  if (!value) {
    return false;
  }
  return ["true", "1", "yes", "on"].includes(value.toLowerCase());
}

// --- Loader ---
function loadPublicConfig(): PublicConfig {
  return PublicConfigSchema.parse({
    authEnabled: parseBooleanEnv(process.env.AUTH_ENABLED),
    baseUrl: process.env.BASE_URL ?? "http://localhost:3002",
  });
}

// --- Caching ---
let cachedPublicConfig: PublicConfig | null = null;

// --- Getter ---
export function getPublicConfig(): PublicConfig {
  if (!cachedPublicConfig) {
    cachedPublicConfig = loadPublicConfig();
  }
  return cachedPublicConfig;
}
