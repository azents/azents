import assert from "node:assert/strict";
import test from "node:test";
import {
  hydrateToolkitConfig,
  projectToolkitConfig,
  toolkitProjectionUsesOauth,
} from "../../shared/toolkits/toolkit-config-projection.ts";

void test("all five GitHub modes hydrate without falling back or generic OAuth discovery", () => {
  for (const mode of [
    "pat",
    "github_app",
    "github_app_platform",
    "github_app_user",
    "github_app_platform_user",
  ]) {
    const projection = projectToolkitConfig("github", {
      github_auth_type: mode,
    });
    assert.ok(projection.type === "github");
    assert.equal(projection.config.github_auth_type, mode);
    assert.deepEqual(
      hydrateToolkitConfig("github", { github_auth_type: mode }).credentials,
      mode === "github_app_platform_user" ? null : { type: mode },
    );
    assert.equal(toolkitProjectionUsesOauth(projection), false);
  }
  const defaultProjection = projectToolkitConfig("github", {});
  assert.ok(defaultProjection.type === "github");
  assert.equal(defaultProjection.config.github_auth_type, "pat");
  assert.equal(defaultProjection.config.inject_runtime_environment, false);
});

void test("known Toolkit projections preserve field filtering and historical defaults", () => {
  const mcp = projectToolkitConfig("mcp", {
    server_url: 7,
    auth_type: "invalid",
    timeout: "30",
    scopes: ["read", 2, "write"],
    extra: true,
  });
  assert.ok(mcp.type === "mcp");
  assert.deepEqual(mcp.config, {
    server_url: "",
    auth_type: "none",
    timeout: 30,
    header_name: "",
    token_url: "",
    auth_url: "",
    scopes: ["read", "write"],
    discovery_url: "",
  });
  assert.deepEqual(
    hydrateToolkitConfig("mcp", { auth_type: "oauth2" }).credentials,
    { type: "oauth2" },
  );
  assert.equal(
    toolkitProjectionUsesOauth(
      projectToolkitConfig("mcp", { auth_type: "oauth2" }),
    ),
    true,
  );
  assert.equal(toolkitProjectionUsesOauth(mcp), false);
  assert.equal(
    toolkitProjectionUsesOauth(projectToolkitConfig("notion", {})),
    true,
  );
  assert.equal(
    toolkitProjectionUsesOauth(projectToolkitConfig("sentry", {})),
    true,
  );
  assert.equal(
    toolkitProjectionUsesOauth(
      projectToolkitConfig("custom", { auth_type: "oauth2" }),
    ),
    false,
  );
});

void test("GitHub projection preserves explicit empty lists, truthiness and auth defaults", () => {
  const projected = projectToolkitConfig("github", {
    toolsets: [],
    github_auth_type: "github_app",
    inject_runtime_environment: "enabled",
    timeout: 0,
  });
  assert.ok(projected.type === "github");
  assert.deepEqual(projected.config.toolsets, []);
  assert.equal(projected.config.github_auth_type, "github_app");
  assert.equal(projected.config.inject_runtime_environment, true);
  assert.equal(projected.config.timeout, 0);
  const missing = projectToolkitConfig("github", {});
  assert.ok(missing.type === "github");
  assert.deepEqual(missing.config.toolsets, [
    "repos",
    "issues",
    "pull_requests",
    "users",
  ]);
});

void test("Shell and envvar projections preserve filtered members and explicit false", () => {
  assert.deepEqual(
    hydrateToolkitConfig("shell", {
      allowed_domains: ["example.com", 5],
      denied_domains: null,
    }),
    {
      config: { allowed_domains: ["example.com"], denied_domains: [] },
      credentials: null,
    },
  );
  assert.deepEqual(
    hydrateToolkitConfig("envvar", {
      entries: [
        { name: "TOKEN", masked: false },
        null,
        [],
        { name: 5, masked: "invalid" },
      ],
    }),
    {
      config: {
        entries: [
          { name: "TOKEN", masked: false },
          { name: "", masked: true },
        ],
      },
      credentials: { values: {} },
    },
  );
});

void test("uninspected provider configs retain exact opaque object identity", () => {
  const nested = { provider_flag: ["a", 2, null] };
  const raw = { extension: nested, arbitrary: false };
  assert.deepEqual(projectToolkitConfig("provider_extension", raw), {
    type: "other",
    toolkitType: "provider_extension",
  });
  const hydrated = hydrateToolkitConfig("provider_extension", raw);
  assert.equal(hydrated.config, raw);
  assert.equal(hydrated.config.extension, nested);
});

void test("known projection ingress rejects a non-object payload", () => {
  assert.throws(() => projectToolkitConfig("mcp", null));
  assert.throws(() => projectToolkitConfig("github", []));
});
