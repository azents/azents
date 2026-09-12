import "server-only";
import { z } from "zod/v4";

// --- Enums ---
const NodeEnvSchema = z.enum(["development", "production", "test"]);
const RuntimeWebAuthModeSchema = z.enum(["shared_cookie", "separate_domain"]);

// --- Server Config (server-only) ---
const ServerConfigSchema = z.object({
  nodeEnv: NodeEnvSchema,
  /** URL for browser → API server communication (public URL, WebSocket, etc.) */
  publicApiUrl: z.string(),
  /** URL for server → API server communication (k8s internal URL; uses publicApiUrl if unset) */
  internalApiUrl: z.string(),
  /** Optional external Admin Web URL shown only to system administrators. */
  adminWebUrl: z.string().url().nullable(),
  runtimeWebGatewayEnabled: z.boolean(),
  runtimeWebGatewayAuthMode: RuntimeWebAuthModeSchema,
  runtimeWebGatewayMainWebOrigin: z.string().url().nullable(),
  runtimeWebGatewayBrokerOrigin: z.string().url().nullable(),
  runtimeWebGatewayCookieDomain: z.string().min(1).nullable(),
  runtimeWebGatewayIdentityCookieName: z.string().min(1),
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
    runtimeWebGatewayEnabled:
      process.env.RUNTIME_WEB_GATEWAY_ENABLED === "true",
    runtimeWebGatewayAuthMode:
      process.env.RUNTIME_WEB_GATEWAY_AUTH_MODE || "shared_cookie",
    runtimeWebGatewayMainWebOrigin:
      process.env.RUNTIME_WEB_GATEWAY_MAIN_WEB_ORIGIN || null,
    runtimeWebGatewayBrokerOrigin:
      process.env.RUNTIME_WEB_GATEWAY_BROKER_ORIGIN || null,
    runtimeWebGatewayCookieDomain:
      process.env.RUNTIME_WEB_GATEWAY_COOKIE_DOMAIN || null,
    runtimeWebGatewayIdentityCookieName:
      process.env.RUNTIME_WEB_GATEWAY_IDENTITY_COOKIE_NAME ||
      "__Http-Azents-Runtime-Web",
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
