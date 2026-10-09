import assert from "node:assert/strict";
import test from "node:test";
import {
  gitHubUserRegistrationDirty,
  missingNewGitHubUserRegistration,
  normalizeGitHubUserCredentialEdits,
} from "../../shared/toolkits/github-user-credentials.ts";

void test("untouched saved Platform user authorization is inherited, not dirty", () => {
  assert.equal(
    gitHubUserRegistrationDirty(
      "github_app_platform_user",
      "github_app_platform_user",
      { type: "github_app_platform_user" },
    ),
    false,
  );
  assert.equal(
    gitHubUserRegistrationDirty("github_app_user", "github_app_user", {
      type: "github_app_user",
      app_id: "",
      client_id: "",
      private_key: "",
      client_secret: "",
    }),
    false,
  );
  assert.equal(
    gitHubUserRegistrationDirty("github_app_user", "github_app_user", {
      type: "github_app_user",
      client_id: "changed",
    }),
    true,
  );
  assert.equal(
    gitHubUserRegistrationDirty("github_app_user", "github_app_platform_user", {
      type: "github_app_platform_user",
    }),
    true,
  );
});
void test("blank write-only registration inputs are omitted individually", () => {
  assert.deepEqual(
    normalizeGitHubUserCredentialEdits({
      type: "github_app_user",
      app_id: "",
      client_id: "",
      private_key: "",
      client_secret: "rotated",
    }),
    { type: "github_app_user", client_secret: "rotated" },
  );
  assert.equal(
    normalizeGitHubUserCredentialEdits({
      type: "github_app_user",
      app_id: "",
      client_id: "",
      private_key: "",
      client_secret: "",
    }),
    null,
  );
  assert.deepEqual(
    normalizeGitHubUserCredentialEdits({
      type: "github_app_user",
      app_id: "different",
      client_id: "new",
      private_key: "key",
      client_secret: "secret",
    }),
    {
      type: "github_app_user",
      app_id: "different",
      client_id: "new",
      private_key: "key",
      client_secret: "secret",
    },
  );
});
void test("explicit null is not confused with an omitted unchanged field", () => {
  assert.deepEqual(
    normalizeGitHubUserCredentialEdits({
      type: "github_app_user",
      client_secret: null,
    }),
    { type: "github_app_user", client_secret: null },
  );
});
void test("fresh BYOA user setup requires every registration field", () => {
  assert.equal(missingNewGitHubUserRegistration(null).length, 4);
  assert.deepEqual(
    missingNewGitHubUserRegistration({
      app_id: "1",
      client_id: "client",
      private_key: "key",
      client_secret: "",
    }),
    ["client_secret"],
  );
  assert.deepEqual(
    missingNewGitHubUserRegistration({
      app_id: "1",
      client_id: "client",
      private_key: "key",
      client_secret: "secret",
    }),
    [],
  );
});
void test("Platform user creation retains its server-bound source discriminator", () => {
  assert.deepEqual(
    normalizeGitHubUserCredentialEdits({ type: "github_app_platform_user" }),
    { type: "github_app_platform_user" },
  );
});
void test("old PAT and installation edit normalization remains unchanged", () => {
  assert.equal(
    normalizeGitHubUserCredentialEdits({ type: "pat", token: "" }),
    null,
  );
  assert.deepEqual(
    normalizeGitHubUserCredentialEdits({
      type: "github_app",
      installations: [],
    }),
    { type: "github_app", installations: [] },
  );
});
