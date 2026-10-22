import assert from "node:assert/strict";
import { test } from "node:test";
import {
  googlePresetGroups,
  googleScopesForGroups,
} from "../../shared/toolkits/google-access.ts";
import { googleGroupCatalog } from "../../shared/toolkits/google-group-fixtures.ts";
import {
  decodeGoogleResume,
  deserializeGoogleResume,
  googleResumeMatches,
  googleResumeScope,
  googleReturnPath,
  googleStateDigest,
} from "../../shared/toolkits/google-resume.ts";
import {
  googleDesiredSchema,
  googleFinalSettingsSchema,
  googleReconnectSettingsSchema,
} from "../../shared/toolkits/google-schemas.ts";
import { canPublishGoogleReview } from "../../shared/toolkits/google-types.ts";
import type { GoogleReview } from "@azents/public-client";

const fixture = {
  handle: "team",
  agentId: "agent",
  attemptId: "candidate",
  expiresAt: "2026-10-15T00:00:00Z",
  stateDigest: "a".repeat(64),
  phase: "AUTHORIZING",
  returnPath: googleReturnPath({ handle: "team", agentId: "agent" }),
};
void test("Google resume validates exact shared/Agent return destination", () => {
  const context = decodeGoogleResume(fixture);
  assert.ok(context);
  assert.ok(
    decodeGoogleResume({ ...fixture, expiresAt: "2026-10-15T00:00:00+09:00" }),
  );
  assert.equal(
    googleResumeMatches(context, { handle: "team", agentId: "other" }),
    false,
  );
  assert.equal(
    googleResumeMatches(context, { handle: "team", agentId: "agent" }, "saved"),
    false,
  );
  for (const invalid of [
    { returnPath: "/w/other/toolkits/new" },
    { returnPath: "https://example.invalid" },
    { code: "secret-code" },
    { state: "encrypted-state" },
  ]) {
    assert.equal(decodeGoogleResume({ ...fixture, ...invalid }), null);
  }
  assert.equal(deserializeGoogleResume("not-json"), null);
});
void test("Personal Google resume is account-scoped without a workload Workspace", () => {
  const personal = {
    owner: "user",
    handle: "workspace",
    toolkitId: "saved",
    attemptId: "personal-attempt",
    expiresAt: fixture.expiresAt,
    stateDigest: fixture.stateDigest,
    phase: "AUTHORIZING",
    returnPath: googleReturnPath(
      { owner: "user", handle: "workspace" },
      "saved",
    ),
  };
  const decoded = decodeGoogleResume(personal);
  assert.ok(decoded);
  assert.deepEqual(googleResumeScope(decoded), {
    owner: "user",
    handle: "workspace",
  });
  assert.ok(
    googleResumeMatches(
      decoded,
      { owner: "user", handle: "workspace" },
      "saved",
    ),
  );
  assert.equal(
    googleResumeMatches(decoded, { handle: "team", agentId: "agent" }, "saved"),
    false,
  );
  for (const invalid of [
    { handle: "team" },
    { agentId: "agent" },
    { userId: "foreign" },
    { returnPath: "/w/team/agents/agent/settings/capabilities#agent-toolkits" },
    { returnPath: "https://example.invalid/return" },
  ]) {
    assert.equal(decodeGoogleResume({ ...personal, ...invalid }), null);
  }
});
void test("nonsecret state digests distinguish sibling callbacks", async () => {
  const first = await googleStateDigest("opaque-first-state");
  assert.match(first, /^[a-f0-9]{64}$/);
  assert.notEqual(first, await googleStateDigest("opaque-second-state"));
  assert.equal(first, await googleStateDigest("opaque-first-state"));
});
void test("Google service and request contracts preserve explicit reconnect intent", () => {
  assert.equal(
    googleDesiredSchema.safeParse({
      services: [],
      oauth_request_scopes: [],
      timeout: 30,
    }).success,
    false,
  );
  assert.equal(
    googleDesiredSchema.safeParse({
      services: ["unknown"],
      oauth_request_scopes: [],
      timeout: 30,
    }).success,
    false,
  );
  assert.equal(
    googleDesiredSchema.safeParse({
      services: ["drive"],
      tool_groups: ["drive_read"],
      oauth_request_scopes: googleScopesForGroups(
        ["drive_read"],
        googleGroupCatalog,
      ),
      timeout: 30,
    }).success,
    true,
  );
  assert.equal(
    googleDesiredSchema.safeParse({
      services: ["gmail"],
      oauth_request_scopes: [],
      timeout: 0,
    }).success,
    false,
  );
  assert.equal(
    googleFinalSettingsSchema.safeParse({
      services: ["calendar"],
      oauth_request_scopes: [],
      timeout: 30,
    }).success,
    false,
  );
  assert.equal(
    googleReconnectSettingsSchema.safeParse({
      services: [],
      tool_groups: [],
      oauth_request_scopes: [],
      timeout: 30,
    }).success,
    true,
  );
});
void test("editable presets request only the selected tool groups' permissions", () => {
  const selected = googlePresetGroups(
    "read_only",
    ["drive", "gmail"],
    googleGroupCatalog,
  );
  assert.deepEqual(selected, ["drive_read", "gmail_read"]);
  assert.deepEqual(googleScopesForGroups(selected, googleGroupCatalog), [
    "email",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "openid",
  ]);
  selected.push("gmail_send");
  assert.ok(
    new Set(googleScopesForGroups(selected, googleGroupCatalog)).has(
      "https://www.googleapis.com/auth/gmail.compose",
    ),
  );
  assert.deepEqual(
    googlePresetGroups("clear", ["gmail"], googleGroupCatalog),
    [],
  );
});
void test("publication requires a renewable reviewed service with actual usable evidence", () => {
  const review: GoogleReview = {
    attempt_id: "attempt",
    expires_at: "2026-10-15T00:00:00Z",
    identity: {
      issuer: "https://accounts.google.com",
      subject: "subject",
      email: null,
    },
    client_id: "client",
    ownership: "workspace_shared",
    reconnect_toolkit_id: null,
    services: ["calendar", "gmail"],
    tool_groups: ["calendar_read", "gmail_read"],
    oauth_request_scopes: ["openid", "email"],
    granted_scopes: [
      "https://www.googleapis.com/auth/calendar.events.readonly",
    ],
    timeout: 30,
    drive_access: {
      whole_content_read: false,
      whole_content_write: false,
      whole_metadata_read: false,
      whole_metadata_write: false,
      app_file_read: false,
      app_file_write: false,
    },
    accesses: [
      {
        service: "calendar",
        enabled: true,
        status: "partial",
        permitted_tools: ["calendar_list_events"],
        unavailable_tools: ["calendar_list_calendars"],
      },
      {
        service: "gmail",
        enabled: true,
        status: "not_granted",
        permitted_tools: [],
        unavailable_tools: ["gmail_search_messages"],
      },
    ],
    grant_result: "partial",
    renewable: true,
    can_confirm: true,
    service_access_verified: false,
  };
  const now = Date.parse("2026-10-14T00:00:00Z");
  assert.equal(canPublishGoogleReview(review, ["calendar"], now), true);
  assert.equal(canPublishGoogleReview(review, [], now), false);
  assert.equal(canPublishGoogleReview(review, ["gmail"], now), false);
  assert.equal(canPublishGoogleReview(review, ["drive"], now), false);
  assert.equal(
    canPublishGoogleReview({ ...review, renewable: false }, ["calendar"], now),
    false,
  );
  assert.equal(
    canPublishGoogleReview({ ...review, accesses: [] }, ["calendar"], now),
    false,
  );
  assert.equal(
    canPublishGoogleReview(review, ["calendar"], Date.parse(review.expires_at)),
    false,
  );
});
