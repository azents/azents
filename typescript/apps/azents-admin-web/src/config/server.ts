import "server-only";
import { z } from "zod/v4";

const NodeEnvSchema = z.enum(["development", "production", "test"]);

const ServerConfigSchema = z.object({
  nodeEnv: NodeEnvSchema,
  adminApiUrl: z.string().url(),
  publicApiUrl: z.string().url(),
  publicWebUrl: z.string().url(),
});

export type ServerConfig = z.infer<typeof ServerConfigSchema>;

function loadServerConfig(): ServerConfig {
  return ServerConfigSchema.parse({
    nodeEnv: process.env.NODE_ENV,
    adminApiUrl: process.env.INTERNAL_ADMIN_API_URL ?? "http://localhost:8011",
    publicApiUrl:
      process.env.INTERNAL_PUBLIC_API_URL ?? "http://localhost:8010",
    publicWebUrl: process.env.PUBLIC_WEB_URL ?? "http://localhost:3003",
  });
}

let cachedServerConfig: ServerConfig | null = null;

export function getServerConfig(): ServerConfig {
  if (!cachedServerConfig) {
    cachedServerConfig = loadServerConfig();
  }
  return cachedServerConfig;
}
