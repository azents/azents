import { z } from "zod/v4";
import type { ToolkitConfigResponse } from "@azents/public-client";

export interface ToolkitDetailField {
  label:
    | "slug"
    | "authType"
    | "server"
    | "configuredScope"
    | "grantedScope"
    | "expires"
    | "features"
    | "region"
    | "project"
    | "clusters"
    | "variables"
    | "runtimeInjection"
    | "writeServices"
    | "readOnly"
    | "allowedNamespaces"
    | "deniedKinds"
    | "property"
    | "country"
    | "language"
    | "safeSearch";
  value: string;
}

// Detail-only projections never materialize form defaults or unreturned grants.
const text = z.string().max(1000).nullish().catch(null);
const strings = z.array(z.string().max(100)).max(30).nullish().catch(null);
const boolean = z.boolean().nullish().catch(null);
const names = z
  .array(z.object({ name: text }))
  .max(30)
  .nullish()
  .catch(null);
const mcp = z.object({ server_url: text, auth_type: text, scopes: strings });
const github = z.object({
  github_auth_type: text,
  toolsets: strings,
  inject_runtime_environment: boolean,
});
const sentry = z.object({ enabled_skills: strings });
const gcp = z.object({
  project_id: text,
  services: strings,
  writable_services: strings,
});
const aws = z.object({ region: text });
const kubernetes = z.object({
  clusters: names,
  read_only: boolean,
  allowed_namespaces: strings,
  denied_kinds: strings,
});
const envvar = z.object({ entries: names });
const analytics = z.object({ default_property_id: text });
const brave = z.object({ country: text, search_lang: text, safesearch: text });

function displayText(value?: string | null): string | null {
  return value != null && value.trim() !== "" ? value : null;
}
function displayList(value?: string[] | null): string | null {
  return value != null && value.length > 0 ? value.join(", ") : null;
}

/** Display only HTTP(S) origin; credentials may also occur in URL paths. */
export function safeToolkitResourceUrl(value: unknown): string | null {
  const parsed = text.parse(value);
  if (parsed == null) {
    return null;
  }
  try {
    const url = new URL(parsed);
    if (
      !["https:", "http:"].includes(url.protocol) ||
      url.username ||
      url.password
    ) {
      return null;
    }
    return url.origin;
  } catch {
    return null;
  }
}

/** Decode an allowlisted Provider payload before constructing detail fields. */
export function projectToolkitDetails(
  toolkit: ToolkitConfigResponse,
): ToolkitDetailField[] {
  const fields: ToolkitDetailField[] = [{ label: "slug", value: toolkit.slug }];
  function add(label: ToolkitDetailField["label"], value: string | null): void {
    if (value != null) {
      fields.push({ label, value });
    }
  }
  switch (toolkit.toolkit_type) {
    case "mcp": {
      const config = mcp.parse(toolkit.config);
      add("server", safeToolkitResourceUrl(config.server_url));
      add("authType", displayText(config.auth_type));
      add("configuredScope", displayList(config.scopes));
      break;
    }
    case "github": {
      const config = github.parse(toolkit.config);
      add("authType", displayText(config.github_auth_type));
      add("features", displayList(config.toolsets));
      if (config.inject_runtime_environment != null) {
        add("runtimeInjection", String(config.inject_runtime_environment));
      }
      break;
    }
    case "notion":
      add("authType", "OAuth");
      break;
    case "sentry": {
      const config = sentry.parse(toolkit.config);
      add("authType", "OAuth");
      add("features", displayList(config.enabled_skills));
      break;
    }
    case "gcp": {
      const config = gcp.parse(toolkit.config);
      add("project", displayText(config.project_id));
      add("features", displayList(config.services));
      add("writeServices", displayList(config.writable_services));
      break;
    }
    case "aws": {
      const config = aws.parse(toolkit.config);
      add("region", displayText(config.region));
      break;
    }
    case "kubernetes": {
      const config = kubernetes.parse(toolkit.config);
      add(
        "clusters",
        displayList(
          config.clusters?.flatMap((entry) => (entry.name ? [entry.name] : [])),
        ),
      );
      if (config.read_only != null) {
        add("readOnly", String(config.read_only));
      }
      add("allowedNamespaces", displayList(config.allowed_namespaces));
      add("deniedKinds", displayList(config.denied_kinds));
      break;
    }
    case "envvar": {
      const config = envvar.parse(toolkit.config);
      add(
        "variables",
        displayList(
          config.entries?.flatMap((entry) => (entry.name ? [entry.name] : [])),
        ),
      );
      break;
    }
    case "google_analytics": {
      const config = analytics.parse(toolkit.config);
      add("property", displayText(config.default_property_id));
      break;
    }
    case "brave_search": {
      const config = brave.parse(toolkit.config);
      add("country", displayText(config.country));
      add("language", displayText(config.search_lang));
      add("safeSearch", displayText(config.safesearch));
      break;
    }
  }
  if (toolkit.oauth_connection != null) {
    add("grantedScope", displayText(toolkit.oauth_connection.scope));
    add("expires", displayText(toolkit.oauth_connection.expires_at));
  }
  return fields;
}
