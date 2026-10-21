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
  picker_status: "not_configured",
  picker_api_key: null,
  picker_app_id: null,
  picker_api_key_source: "unset",
  picker_app_id_source: "unset",
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

void test("Optional Picker fields preserve omission, environment display and explicit clears", () => {
  const draft = googleApplicationDraft({
    ...detail,
    picker_api_key: "browser-key",
    picker_api_key_source: "environment",
    picker_app_id: "1234",
    picker_app_id_source: "admin",
  });
  assert.equal(draft.pickerApiKey, "browser-key");
  assert.equal(draft.pickerAppId, "1234");
  assert.deepEqual(googleApplicationPatch(draft, 4), { expected_version: 4 });
  assert.deepEqual(
    googleApplicationPatch(
      {
        ...draft,
        pickerApiKey: " ",
        pickerApiKeyTouched: true,
        pickerAppId: "4567",
        pickerAppIdTouched: true,
      },
      4,
    ),
    { expected_version: 4, picker_api_key: null, picker_app_id: "4567" },
  );
});
