import assert from "node:assert/strict";
import { test } from "node:test";
import {
  googleApplicationDirty,
  googleApplicationDraft,
  googleApplicationPatch,
} from "./google-application-state.ts";
import type { GoogleApplicationDetail } from "@azents/admin-client";
const detail: GoogleApplicationDetail = {
  status: "configured_unverified",
  client_id: "operator-client",
  callback_url: "https://app.example.invalid/oauth/google/callback",
  preview_verified: false,
  service_access_verified: false,
  section: "google_oauth",
  schema_version: 1,
  admin_version: 4,
  client_id_source: "admin",
  client_secret_source: "admin",
  client_secret_configured: true,
};
void test("Google operator draft never hydrates an existing secret", () => {
  const draft = googleApplicationDraft(detail);
  assert.equal(draft.secret, "");
  assert.equal(draft.clearSecret, false);
  assert.equal(googleApplicationDirty(draft), false);
  assert.deepEqual(googleApplicationPatch(draft, 4), { expected_version: 4 });
});
void test("Google operator patch preserves field omission and explicit clear", () => {
  const draft = googleApplicationDraft(detail);
  assert.deepEqual(
    googleApplicationPatch({ ...draft, clientTouched: true, clientId: " " }, 4),
    { expected_version: 4, client_id: null },
  );
  assert.deepEqual(googleApplicationPatch({ ...draft, clearSecret: true }, 4), {
    expected_version: 4,
    client_secret: { action: "clear" },
  });
  assert.equal(googleApplicationDirty({ ...draft, clearSecret: true }), true);
});
void test("Google operator replacement binds optimistic version and exact submitted secret", () => {
  const draft = { ...googleApplicationDraft(detail), secret: "TEST-SECRET" };
  assert.deepEqual(googleApplicationPatch(draft, 4), {
    expected_version: 4,
    client_secret: { action: "replace", value: "TEST-SECRET" },
  });
  assert.equal(googleApplicationDirty(draft), true);
  assert.equal(
    googleApplicationPatch({ ...draft, clearSecret: true }, 4).client_secret
      ?.action,
    "clear",
  );
});
