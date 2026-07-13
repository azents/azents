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
    adminApiUrl: process.env.ADMIN_API_URL ?? "http://localhost:8011",
    publicApiUrl: process.env.PUBLIC_API_URL ?? "http://localhost:8000",
    publicWebUrl: process.env.AZ_WEB_URL ?? "http://localhost:3000",
  });
}

let cachedServerConfig: ServerConfig | null = null;

export function getServerConfig(): ServerConfig {
  if (!cachedServerConfig) {
    cachedServerConfig = loadServerConfig();
  }
  return cachedServerConfig;
}
