import assert from "node:assert/strict";
import test from "node:test";
import {
  projectToolkitDetails,
  safeToolkitResourceUrl,
} from "./toolkit-detail-projection.ts";
import type { ToolkitConfigResponse } from "@azents/public-client";

function toolkit(
  toolkitType: string,
  config: Record<string, unknown>,
): ToolkitConfigResponse {
  return {
    id: "test",
    workspace_id: "workspace",
    toolkit_type: toolkitType,
    slug: "test",
    name: "Test",
    description: null,
    config,
    prompt: null,
    has_credentials: true,
    enabled: true,
    always_expose_tools: false,
    oauth_connection: null,
    authorization_state: null,
    created_at: "2026-10-08T00:00:00Z",
    updated_at: "2026-10-08T00:00:00Z",
  };
}

void test("detail projection never dumps credentials or unknown config fields", () => {
  const secret = "must-not-render";
  const view = projectToolkitDetails(
    toolkit("mcp", {
      server_url: "https://example.com/mcp?token=secret#private",
      auth_type: "oauth2",
      scopes: ["read"],
      client_secret: secret,
      token: secret,
      credentials: { value: secret },
      unknown: secret,
    }),
  );
  assert.equal(JSON.stringify(view).includes(secret), false);
  assert.deepEqual(
    view.find((field) => field.label === "server"),
    { label: "server", value: "https://example.com" },
  );
  assert.deepEqual(
    projectToolkitDetails(toolkit("plugin", { api_key: secret })),
    [{ label: "slug", value: "test" }],
  );
});

void test("environment entries reveal names only, including unmasked entries", () => {
  const view = projectToolkitDetails(
    toolkit("envvar", {
      entries: [{ name: "API_KEY", value: "hidden-value", masked: false }],
    }),
  );
  assert.deepEqual(view, [
    { label: "slug", value: "test" },
    { label: "variables", value: "API_KEY" },
  ]);
});

void test("configured scopes remain distinct from granted OAuth token scope", () => {
  const value = toolkit("mcp", { scopes: ["read", "write"] });
  value.oauth_connection = {
    status: "connected",
    issuer: null,
    resource: null,
    scope: "read",
    expires_at: null,
  };
  const view = projectToolkitDetails(value);
  assert.equal(
    view.find((field) => field.label === "configuredScope")?.value,
    "read, write",
  );
  assert.equal(
    view.find((field) => field.label === "grantedScope")?.value,
    "read",
  );
});

void test("server details omit credential-bearing paths without changing stored URLs", () => {
  const value = toolkit("mcp", {
    server_url:
      "https://example.com:8443/mcp/private-api-key?key=secret#private",
  });
  assert.deepEqual(
    projectToolkitDetails(value).find((field) => field.label === "server"),
    { label: "server", value: "https://example.com:8443" },
  );
  assert.equal(
    value.config.server_url,
    "https://example.com:8443/mcp/private-api-key?key=secret#private",
  );
  assert.equal(
    safeToolkitResourceUrl("https://example.com/mcp/%73ecret-key"),
    "https://example.com",
  );
});

void test("server URLs reject userinfo and unsafe schemes", () => {
  assert.equal(
    safeToolkitResourceUrl("https://user:password@example.com/mcp"),
    null,
  );
  assert.equal(safeToolkitResourceUrl("javascript:alert(1)"), null);
  assert.equal(safeToolkitResourceUrl("not a url"), null);
});

void test("safe existing fields from every Provider remain available without defaults", () => {
  const cases: Array<[string, Record<string, unknown>, string]> = [
    [
      "github",
      { toolsets: ["repos"], inject_runtime_environment: false },
      "runtimeInjection",
    ],
    ["sentry", { enabled_skills: ["inspect"] }, "features"],
    [
      "gcp",
      {
        project_id: "example-project",
        services: ["logging"],
        writable_services: ["logging"],
      },
      "writeServices",
    ],
    ["aws", { region: "us-east-1" }, "region"],
    ["google_analytics", { default_property_id: "12345" }, "property"],
    [
      "brave_search",
      { country: "KR", search_lang: "ko", safesearch: "strict" },
      "country",
    ],
    [
      "kubernetes",
      {
        clusters: [{ name: "dev", token: "not-displayed" }],
        read_only: true,
        denied_kinds: ["Secret"],
      },
      "readOnly",
    ],
  ];
  for (const [type, config, label] of cases) {
    const result = projectToolkitDetails(
      toolkit(type, { ...config, private_key: "not-displayed" }),
    );
    assert.ok(
      result.some((field) => field.label === label),
      type,
    );
    assert.equal(JSON.stringify(result).includes("not-displayed"), false);
    assert.deepEqual(projectToolkitDetails(toolkit(type, {})), [
      { label: "slug", value: "test" },
      ...(type === "sentry" ? [{ label: "authType", value: "OAuth" }] : []),
    ]);
  }
});

void test("malformed optional detail payloads cannot invent booleans or capability lists", () => {
  assert.deepEqual(
    projectToolkitDetails(
      toolkit("github", { toolsets: [12], inject_runtime_environment: "true" }),
    ),
    [{ label: "slug", value: "test" }],
  );
});
