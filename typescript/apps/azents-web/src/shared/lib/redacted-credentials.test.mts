import assert from "node:assert/strict";
import test from "node:test";
import { normalizeCredentialEdits } from "./redacted-credentials.ts";

void test("drops flat redacted credential placeholders", () => {
  assert.equal(normalizeCredentialEdits({ type: "bearer", token: "" }), null);
});

void test("drops nested redacted credential placeholders", () => {
  assert.equal(
    normalizeCredentialEdits({
      clusters: {
        production: {
          type: "kubeconfig",
          kubeconfig_yaml: "",
        },
      },
    }),
    null,
  );
});

void test("keeps a nested replacement credential", () => {
  const credentials = {
    clusters: {
      production: {
        type: "token",
        token: "replacement",
        ca_cert: "",
      },
    },
  };

  assert.equal(normalizeCredentialEdits(credentials), credentials);
});

void test("keeps non-secret credential selections", () => {
  const credentials = {
    type: "github_app_platform",
    installations: [{ installation_id: "42", account_login: "azents" }],
  };

  assert.equal(normalizeCredentialEdits(credentials), credentials);
});

void test("keeps empty editable credential selections", () => {
  const credentials = {
    type: "github_app_platform",
    installations: [],
  };

  assert.equal(normalizeCredentialEdits(credentials), credentials);
});
