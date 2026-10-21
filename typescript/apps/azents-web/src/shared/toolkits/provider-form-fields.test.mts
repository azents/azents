import assert from "node:assert/strict";
import { test } from "node:test";
import {
  braveFieldCallbacks,
  githubFieldCallbacks,
  projectBraveFormFields,
  projectGithubFormFields,
} from "./provider-form-fields.ts";

for (const value of [
  void 0,
  null,
  false,
  0,
  "",
  "partial",
  [],
  {},
  ["repos", 1, "repos"],
]) {
  void test(`editable projections preserve prior field coercion for ${JSON.stringify(value)}`, () => {
    const config = {
      country: value,
      search_lang: value,
      safesearch: value,
      timeout: value,
      github_auth_type: value,
      toolsets: value,
      inject_runtime_environment: value,
    };
    const credentials = {
      api_key: value,
      token: value,
      app_id: value,
      private_key: value,
      client_id: value,
      client_secret: value,
    };
    const before = structuredClone({ config, credentials });
    const brave = projectBraveFormFields(config, credentials);
    assert.deepEqual(brave, {
      apiKey: typeof value === "string" ? value : "",
      country: typeof value === "string" ? value : "US",
      language: typeof value === "string" ? value : "en",
      safesearch: typeof value === "string" ? value : "strict",
      timeout: typeof value === "number" ? value : 10,
    });
    const github = projectGithubFormFields(config, credentials);
    const text = typeof value === "string" ? value : "";
    assert.equal(github.auth, text || "pat");
    assert.deepEqual(github.credentials, {
      token: text,
      app_id: text,
      private_key: text,
      client_id: text,
      client_secret: text,
    });
    assert.equal(github.injectRuntimeEnvironment, Boolean(value));
    assert.deepEqual(
      github.toolsets,
      Array.isArray(value)
        ? value.filter((item) => typeof item === "string")
        : ["repos", "issues", "pull_requests", "users"],
    );
    assert.deepEqual({ config, credentials }, before);
  });
}

void test("Brave field edits retain opaque config and partial inputs; blank key clears edits", () => {
  const config = { opaque: { future: null }, country: "US" };
  const changes: unknown[] = [];
  const credentials: unknown[] = [];
  const callbacks = braveFieldCallbacks(
    config,
    (next) => changes.push(next),
    (next) => credentials.push(next),
  );
  callbacks.onCountryChange("kr");
  callbacks.onLanguageChange("KO");
  callbacks.onSafesearchChange(null);
  callbacks.onTimeoutChange("");
  callbacks.onApiKeyChange("k");
  callbacks.onApiKeyChange("");
  assert.deepEqual(changes, [
    { ...config, country: "KR" },
    { ...config, search_lang: "ko" },
    { ...config, safesearch: "strict" },
    { ...config, timeout: "" },
  ]);
  assert.deepEqual(credentials, [{ api_key: "k" }, null]);
  assert.deepEqual(config, { opaque: { future: null }, country: "US" });
});

void test("GitHub named edits preserve opaque fields and auth-change publication order", () => {
  const config = { github_auth_type: "github_app", opaque: [null] };
  const credentials = { private_key: "draft", opaque: { retained: true } };
  const events: unknown[] = [];
  const callbacks = githubFieldCallbacks(
    config,
    credentials,
    (next) => events.push(["config", next]),
    (next) => events.push(["credentials", next]),
  );
  callbacks.onCredentialFieldChange("client_secret", "");
  callbacks.onToolsetsChange([]);
  callbacks.onInjectRuntimeEnvironmentChange(false);
  callbacks.onAuthChange(null);
  assert.deepEqual(events, [
    ["credentials", { ...credentials, client_secret: "" }],
    ["config", { ...config, toolsets: [] }],
    ["config", { ...config, inject_runtime_environment: false }],
    ["config", { ...config, github_auth_type: "pat", auth_type: "bearer" }],
    ["credentials", { type: "pat" }],
  ]);
});
