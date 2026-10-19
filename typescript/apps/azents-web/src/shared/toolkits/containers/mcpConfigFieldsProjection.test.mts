import assert from "node:assert/strict";
import test from "node:test";
import { projectMcpConfigFields } from "./mcpConfigFieldsProjection.ts";

void test("MCP consumed fields normalize without closing opaque transport", () => {
  const config = {
    server_url: "https://mcp.example/sse",
    auth_type: "oauth2",
    timeout: Number.POSITIVE_INFINITY,
    scopes: ["one", 3, null, "two"],
    header_name: null,
    extension: { retained: true },
  };
  const credentials = {
    token: "secret",
    client_id: 3,
    opaque: { retained: true },
  };
  const changes: unknown[] = [];
  const view = projectMcpConfigFields({
    owner: "user",
    handle: "workspace",
    config,
    credentials,
    hasCredentials: true,
    onConfigChange: (value) => changes.push({ config: value }),
    onCredentialsChange: (value) => changes.push({ credentials: value }),
    testState: { type: "IDLE" },
    onTestConnection: () => {},
  });
  assert.equal(view.configView.auth_type, "oauth2");
  assert.equal(view.configView.timeout, Number.POSITIVE_INFINITY);
  assert.deepEqual(view.configView.scopes, ["one", "two"]);
  assert.equal(view.configView.header_name, "");
  assert.equal(view.credentialsView.token, "secret");
  assert.equal(view.credentialsView.client_id, "");
  assert.equal(view.canTest, true);
  view.onSetConfig("scopes", []);
  view.onSetCredential("client_id", "replacement");
  view.onAuthTypeChange("oauth2");
  view.onAuthTypeChange(null);
  assert.deepEqual(changes, [
    { config: { ...config, scopes: [] } },
    { credentials: { ...credentials, client_id: "replacement" } },
    { config: { ...config, auth_type: "oauth2" } },
    { credentials: null },
    { config: { ...config, auth_type: "none" } },
    { credentials: { type: "none" } },
  ]);
  assert.deepEqual(config.extension, { retained: true });
  assert.deepEqual(credentials.opaque, { retained: true });
});

void test("MCP unknown discriminators retain fallback and owner-scoped test visibility", () => {
  for (const auth_type of [
    null,
    false,
    2,
    [],
    {},
    "unknown",
    "header",
    "bearer",
  ]) {
    const view = projectMcpConfigFields({
      handle: "",
      config: { auth_type, server_url: null, timeout: "30" },
      credentials: null,
      hasCredentials: false,
      onConfigChange: () => {},
      onCredentialsChange: () => {},
      testState: { type: "IDLE" },
      onTestConnection: () => {},
    });
    assert.equal(
      view.configView.auth_type,
      auth_type === "header" || auth_type === "bearer" ? auth_type : "none",
    );
    assert.equal(view.configView.timeout, 30);
    assert.equal(view.canTest, false);
    assert.equal(view.credentialsView.value, "");
  }
});
