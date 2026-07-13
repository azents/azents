import "server-only";
import { z } from "zod/v4";

// --- Enums ---
const NodeEnvSchema = z.enum(["development", "production", "test"]);

// --- Server Config (server-only) ---
const ServerConfigSchema = z.object({
  nodeEnv: NodeEnvSchema,
  /** URL for browser → API server communication (public URL, WebSocket, etc.) */
  publicApiUrl: z.string(),
  /** URL for server → API server communication (k8s internal URL; uses publicApiUrl if unset) */
  internalApiUrl: z.string(),
  /** Optional external Admin Web URL shown only to system administrators. */
  adminWebUrl: z.string().url().nullable(),
});

export type ServerConfig = z.infer<typeof ServerConfigSchema>;

// --- Loader ---
function loadServerConfig(): ServerConfig {
  const publicApiUrl = process.env.PUBLIC_API_URL || "http://localhost:8010";
  return ServerConfigSchema.parse({
    nodeEnv: process.env.NODE_ENV,
    publicApiUrl,
    internalApiUrl: process.env.INTERNAL_API_URL || publicApiUrl,
    adminWebUrl: process.env.ADMIN_WEB_URL || null,
  });
}

// --- Caching ---
let cachedServerConfig: ServerConfig | null = null;

// --- Getter ---
export function getServerConfig(): ServerConfig {
  if (!cachedServerConfig) {
    cachedServerConfig = loadServerConfig();
  }
  return cachedServerConfig;
}
