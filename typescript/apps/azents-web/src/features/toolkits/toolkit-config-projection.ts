import { z } from "zod/v4";
import { isRecord, isString } from "../../shared/lib/unknown-value.ts";

const text = z.string().catch("");
const historicalNumber = z
  .custom<number>((value) => typeof value === "number")
  .catch(30);
/** Opaque JSON exists only at the form/provider transport boundary. */
export const toolkitConfigWireSchema = z.record(z.string(), z.unknown());
const strings = z.preprocess(
  (value) => (Array.isArray(value) ? value.filter(isString) : []),
  z.array(z.string()),
);
const mcpAuth = z.enum(["none", "header", "bearer", "oauth2"]).catch("none");
const githubAuth = z
  .enum(["pat", "github_app", "github_app_platform"])
  .catch("pat");
const shellSchema = z.object({
  allowed_domains: strings,
  denied_domains: strings,
});
const mcpSchema = z.object({
  server_url: text,
  auth_type: mcpAuth,
  timeout: historicalNumber,
  header_name: text,
  token_url: text,
  auth_url: text,
  scopes: strings,
  discovery_url: text,
});
const githubSchema = z.object({
  server_url: z.string().catch("https://api.githubcopilot.com/mcp/"),
  auth_type: z.literal("bearer").catch("bearer"),
  github_auth_type: githubAuth,
  toolsets: z.preprocess(
    (value) =>
      Array.isArray(value)
        ? value.filter(isString)
        : ["repos", "issues", "pull_requests", "users"],
    z.array(z.string()),
  ),
  timeout: historicalNumber,
  inject_runtime_environment: z.unknown().optional().transform(Boolean),
});
const envvarSchema = z.object({
  entries: z.preprocess(
    (value) => (Array.isArray(value) ? value.filter(isRecord) : []),
    z.array(z.object({ name: text, masked: z.boolean().catch(true) })),
  ),
});

export type ToolkitConfigProjection =
  | { type: "shell"; config: z.infer<typeof shellSchema> }
  | { type: "mcp"; config: z.infer<typeof mcpSchema> }
  | { type: "github"; config: z.infer<typeof githubSchema> }
  | { type: "envvar"; config: z.infer<typeof envvarSchema> }
  | { type: "other"; toolkitType: string };

/** Decode only the known form projection; preserve historical normalization defaults. */
export function projectToolkitConfig(
  toolkitType: string,
  value: unknown,
): ToolkitConfigProjection {
  switch (toolkitType) {
    case "shell":
      return { type: "shell", config: shellSchema.parse(value) };
    case "mcp":
      return { type: "mcp", config: mcpSchema.parse(value) };
    case "github":
      return { type: "github", config: githubSchema.parse(value) };
    case "envvar":
      return { type: "envvar", config: envvarSchema.parse(value) };
    default:
      return { type: "other", toolkitType };
  }
}

export function toolkitProjectionUsesOauth(
  projection: ToolkitConfigProjection,
): boolean {
  switch (projection.type) {
    case "mcp":
      return projection.config.auth_type === "oauth2";
    case "other":
      return (
        projection.toolkitType === "notion" ||
        projection.toolkitType === "sentry"
      );
    default:
      return false;
  }
}

export interface ToolkitConfigHydration {
  config: Record<string, unknown>;
  credentials: Record<string, unknown> | null;
}

/** Form transport adapter: known projections match prior hydration; plugins relay opaquely. */
export function hydrateToolkitConfig(
  toolkitType: string,
  value: Record<string, unknown>,
): ToolkitConfigHydration {
  const projection = projectToolkitConfig(toolkitType, value);
  switch (projection.type) {
    case "shell":
      return { config: projection.config, credentials: null };
    case "mcp":
      return {
        config: projection.config,
        credentials: { type: projection.config.auth_type },
      };
    case "github":
      return {
        config: projection.config,
        credentials: { type: projection.config.github_auth_type },
      };
    case "envvar":
      return { config: projection.config, credentials: { values: {} } };
    case "other":
      return { config: value, credentials: null };
  }
}
