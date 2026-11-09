import assert from "node:assert/strict";
import { test } from "node:test";
import {
  deserializeGoogleDraft,
  detachGoogleDraft,
  emptyGoogleMetadata,
  googleDraftMatches,
  googleReviewDecision,
  googleUsableSelection,
  reconcileGoogleSelection,
} from "./google-editor.ts";
import { googleGroupCatalog } from "./google-group-fixtures.ts";
import { decodeGoogleResume, googleAgentReturnPath } from "./google-resume.ts";
import type {
  GoogleConnectionOutput,
  GoogleReview,
} from "@azents/public-client";
const noDrive = {
  whole_metadata_read: false,
  whole_content_read: false,
  whole_content_write: false,
  whole_metadata_write: false,
  app_file_read: false,
  app_file_write: false,
};
function review(): GoogleReview {
  return {
    attempt_id: "attempt",
    expires_at: "2030-01-01T00:00:00Z",
    identity: {
      issuer: "https://accounts.google.com",
      subject: "exact-subject",
      email: "display@example.invalid",
    },
    client_id: "client",
    ownership: "agent_only",
    reconnect_toolkit_id: "toolkit",
    services: ["calendar"],
    tool_groups: ["calendar_read"],
    oauth_request_scopes: [
      "openid",
      "email",
      "https://www.googleapis.com/auth/calendar.readonly",
    ],
    granted_scopes: ["https://www.googleapis.com/auth/calendar.readonly"],
    timeout: 30,
    accesses: [
      {
        service: "calendar",
        enabled: true,
        status: "permitted",
        permitted_tools:
          googleGroupCatalog.find((group) => group.group === "calendar_read")
            ?.operations ?? [],
        unavailable_tools: [],
      },
    ],
    drive_access: noDrive,
    grant_result: "full",
    renewable: true,
    can_confirm: true,
    service_access_verified: false,
  };
}
function saved(result: GoogleReview): GoogleConnectionOutput {
  return {
    ...result,
    granted_tools: result.accesses.flatMap((access) => access.permitted_tools),
    toolkit_id: "toolkit",
    revision: 1,
    connection_id: "connection",
    status: "connected",
  };
}
void test("normal recovery compares actual operations and verified issuer/subject, not email", () => {
  const result = review(),
    old = saved(result);
  old.identity = { ...result.identity, email: "other-display@example.invalid" };
  assert.equal(googleReviewDecision(result, old, googleGroupCatalog), "NORMAL");
  old.identity = { ...result.identity, subject: "other" };
  assert.equal(
    googleReviewDecision(result, old, googleGroupCatalog),
    "ACCOUNT",
  );
  old.identity = { ...result.identity, issuer: "https://other.invalid" };
  assert.equal(
    googleReviewDecision(result, old, googleGroupCatalog),
    "ACCOUNT",
  );
});
void test("unknown, empty, nonrenewable and expired evidence never auto-confirms", () => {
  for (const result of [
    { ...review(), granted_scopes: null },
    { ...review(), renewable: false },
    { ...review(), expires_at: "2000-01-01T00:00:00Z" },
    { ...review(), accesses: [] },
  ]) {
    assert.equal(
      googleReviewDecision(result, null, googleGroupCatalog),
      "UNUSABLE",
    );
  }
});
void test("partial decision is based on selected capability coverage, not receipt labels", () => {
  const result = review();
  result.grant_result = "partial";
  assert.equal(
    googleReviewDecision(result, null, googleGroupCatalog),
    "NORMAL",
  );
  const access = result.accesses.at(0);
  assert.ok(access);
  access.permitted_tools = ["calendar_list_events"];
  assert.equal(
    googleReviewDecision(result, null, googleGroupCatalog),
    "PARTIAL",
  );
  assert.deepEqual(googleUsableSelection(result, googleGroupCatalog), {
    services: ["calendar"],
    toolGroups: ["calendar_read"],
  });
  access.permitted_tools = [];
  assert.deepEqual(googleUsableSelection(result, googleGroupCatalog), {
    services: [],
    toolGroups: [],
  });
});
void test("bounded tab draft is exact-owner target and attempt, never credential storage", () => {
  const draft = {
    handle: "team",
    agentId: "agent",
    toolkitId: "toolkit",
    attemptId: "attempt",
    expiresAt: "2030-01-01T00:00:00Z",
    metadata: emptyGoogleMetadata,
    baseline: {
      services: ["calendar"],
      toolGroups: ["calendar_read"],
      timeout: 30,
    },
    services: ["calendar"],
    toolGroups: ["calendar_read"],
    timeout: 30,
    revision: 7,
  };
  const parsed = deserializeGoogleDraft(JSON.stringify(draft));
  assert.ok(parsed);
  assert.equal(
    googleDraftMatches(
      parsed,
      { handle: "team", agentId: "agent" },
      "toolkit",
      "attempt",
    ),
    true,
  );
  assert.equal(
    googleDraftMatches(parsed, { handle: "team" }, "toolkit", "attempt"),
    false,
  );
  assert.equal(
    googleDraftMatches(
      parsed,
      { handle: "team", agentId: "agent" },
      "other",
      "attempt",
    ),
    false,
  );
  assert.equal(
    googleDraftMatches(
      parsed,
      { handle: "team", agentId: "agent" },
      "toolkit",
      "other",
    ),
    false,
  );
  assert.equal(
    deserializeGoogleDraft(
      JSON.stringify({ ...draft, access_token: "not-allowed" }),
    ),
    null,
  );
});
void test("shared recovery can return to an exact same-Workspace Agent but not arbitrary URLs", () => {
  const context = {
    handle: "team",
    toolkitId: "toolkit",
    returnAgentId: "agent",
    attemptId: "attempt",
    expiresAt: "2030-01-01T00:00:00Z",
    stateDigest: "a".repeat(64),
    phase: "REVIEW",
    purpose: "RECOVER",
    returnPath: googleAgentReturnPath("team", "agent"),
  };
  assert.ok(decodeGoogleResume(context));
  assert.equal(
    decodeGoogleResume({
      ...context,
      returnPath: googleAgentReturnPath("other", "agent"),
    }),
    null,
  );
  assert.equal(
    decodeGoogleResume({ ...context, returnPath: "https://evil.invalid" }),
    null,
  );
});

void test("recovery keeps draft deltas without resurrecting denied groups", () => {
  assert.deepEqual(
    reconcileGoogleSelection(
      ["calendar_read", "gmail_read"],
      ["calendar_read", "gmail_read", "drive_read"],
      ["calendar_read"],
    ),
    ["calendar_read", "drive_read"],
  );
  assert.deepEqual(
    reconcileGoogleSelection(
      ["calendar_read", "gmail_read"],
      ["calendar_read"],
      ["calendar_read", "gmail_read"],
    ),
    ["calendar_read"],
  );
});

void test("detached editor intent gets a fresh one-hour lifetime without extending OAuth authority", () => {
  const now = Date.parse("2026-11-09T00:00:00Z");
  const draft = deserializeGoogleDraft(
    JSON.stringify({
      handle: "team",
      toolkitId: "toolkit",
      attemptId: "attempt",
      expiresAt: new Date(now - 1).toISOString(),
      metadata: { ...emptyGoogleMetadata, name: "Unapplied" },
      services: ["calendar"],
      toolGroups: ["calendar_read"],
      timeout: 12,
      revision: 7,
      baseline: null,
    }),
  );
  assert.ok(draft);
  const detached = detachGoogleDraft(draft, now);
  const restored = deserializeGoogleDraft(JSON.stringify(detached));
  assert.ok(restored);
  assert.equal(restored.attemptId, void 0);
  assert.equal(Date.parse(restored.expiresAt), now + 60 * 60 * 1000);
  assert.equal(restored.metadata.name, "Unapplied");
  assert.equal(restored.revision, 7);
  assert.equal(draft.expiresAt, new Date(now - 1).toISOString());
});
