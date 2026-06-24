import "server-only";
import { z } from "zod/v4";

// --- Enums ---
const ApiAuthMethodSchema = z.enum(["none", "oauth2"]);
const NodeEnvSchema = z.enum(["development", "production", "test"]);

export type ApiAuthMethod = z.infer<typeof ApiAuthMethodSchema>;

// --- Server Config (서버 전용) ---
const BaseServerConfigSchema = z.object({
  nodeEnv: NodeEnvSchema,
  adminApiUrl: z.string(),
  publicWebUrl: z.string(),
  githubClientId: z.string().optional(),
  githubClientSecret: z.string().optional(),
});

const NoApiAuthServerConfigSchema = BaseServerConfigSchema.extend({
  apiAuthMethod: z.literal("none"),
});

const OAuth2ApiAuthServerConfigSchema = BaseServerConfigSchema.extend({
  apiAuthMethod: z.literal("oauth2"),
  oauth2TokenUrl: z.string(),
  oauth2ClientId: z.string(),
  oauth2ClientSecret: z.string(),
});

type NoApiAuthServerConfig = z.infer<typeof NoApiAuthServerConfigSchema>;
type OAuth2ApiAuthServerConfig = z.infer<
  typeof OAuth2ApiAuthServerConfigSchema
>;

export type ServerConfig = NoApiAuthServerConfig | OAuth2ApiAuthServerConfig;

// --- Loader ---
function loadServerConfig(): ServerConfig {
  const apiAuthMethod = ApiAuthMethodSchema.parse(
    process.env.ADMIN_API_AUTH_METHOD || "none",
  );

  const baseConfig = {
    nodeEnv: process.env.NODE_ENV,
    adminApiUrl: process.env.ADMIN_API_URL || "http://localhost:8011",
    publicWebUrl: process.env.AZ_WEB_URL || "http://localhost:3000",
    apiAuthMethod,
    githubClientId: process.env.GITHUB_CLIENT_ID,
    githubClientSecret: process.env.GITHUB_CLIENT_SECRET,
  };

  if (apiAuthMethod === "oauth2") {
    return OAuth2ApiAuthServerConfigSchema.parse({
      ...baseConfig,
      oauth2TokenUrl: process.env.ADMIN_OAUTH2_TOKEN_URL,
      oauth2ClientId: process.env.ADMIN_OAUTH2_CLIENT_ID,
      oauth2ClientSecret: process.env.ADMIN_OAUTH2_CLIENT_SECRET,
    });
  }

  return NoApiAuthServerConfigSchema.parse(baseConfig);
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
