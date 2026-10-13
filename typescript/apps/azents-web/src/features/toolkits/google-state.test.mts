import assert from "node:assert/strict";
import { test } from "node:test";
import {
  decodeGoogleResume,
  deserializeGoogleResume,
  googleResumeMatches,
  googleReturnPath,
  googleStateDigest,
} from "../../shared/toolkits/google-resume.ts";
import {
  googleDesiredSchema,
  googleFinalSettingsSchema,
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
  returnPath: googleReturnPath("team", "agent"),
};
void test("Google resume validates exact shared/Agent return destination", () => {
  const context = decodeGoogleResume(fixture);
  assert.ok(context);
  assert.ok(
    decodeGoogleResume({ ...fixture, expiresAt: "2026-10-15T00:00:00+09:00" }),
  );
  assert.equal(googleResumeMatches(context, "team", "other"), false);
  assert.equal(googleResumeMatches(context, "team", "agent", "saved"), false);
  assert.equal(
    decodeGoogleResume({ ...fixture, returnPath: "/w/other/toolkits/new" }),
    null,
  );
  assert.equal(
    decodeGoogleResume({ ...fixture, returnPath: "https://example.invalid" }),
    null,
  );
  assert.equal(decodeGoogleResume({ ...fixture, code: "secret-code" }), null);
  assert.equal(
    decodeGoogleResume({ ...fixture, state: "encrypted-state" }),
    null,
  );
  assert.equal(deserializeGoogleResume("not-json"), null);
});
void test("nonsecret state digests distinguish sibling callbacks", async () => {
  const first = await googleStateDigest("opaque-first-state");
  assert.match(first, /^[a-f0-9]{64}$/);
  assert.notEqual(first, await googleStateDigest("opaque-second-state"));
  assert.equal(first, await googleStateDigest("opaque-first-state"));
});
void test("Google task selection is explicit and bounded", () => {
  assert.equal(
    googleDesiredSchema.safeParse({ tasks: [], timeout: 30 }).success,
    false,
  );
  assert.equal(
    googleDesiredSchema.safeParse({ tasks: ["gmail_send"], timeout: 30 })
      .success,
    false,
  );
  assert.equal(
    googleDesiredSchema.safeParse({ tasks: ["drive_files"], timeout: 30 })
      .success,
    true,
  );
  assert.equal(
    googleDesiredSchema.safeParse({ tasks: ["gmail_read"], timeout: 0 })
      .success,
    false,
  );
  assert.equal(
    googleFinalSettingsSchema.safeParse({
      tasks: ["calendar_read"],
      timeout: 30,
    }).success,
    false,
  );
});

void test("publication requires fresh acknowledgement and actual usable task evidence", () => {
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
    requested_tasks: ["calendar_read", "gmail_read"],
    timeout: 30,
    tasks: [
      {
        task: "calendar_read",
        service: "calendar",
        status: "partial",
        permitted_tools: ["list_events"],
        unavailable_tools: ["list_calendars"],
      },
      {
        task: "gmail_read",
        service: "gmail",
        status: "not_granted",
        permitted_tools: [],
        unavailable_tools: ["list_messages"],
      },
    ],
    grant_result: "partial",
    renewable: true,
    can_confirm: true,
    service_access_verified: false,
    security_notice: "Known-pattern limitations.",
  };
  const now = Date.parse("2026-10-14T00:00:00Z");
  assert.equal(
    canPublishGoogleReview(review, ["calendar_read"], true, now),
    true,
  );
  assert.equal(
    canPublishGoogleReview(review, ["calendar_read"], false, now),
    false,
  );
  assert.equal(
    canPublishGoogleReview(review, ["gmail_read"], true, now),
    false,
  );
  assert.equal(
    canPublishGoogleReview(review, ["calendar_edit"], true, now),
    false,
  );
  assert.equal(
    canPublishGoogleReview(
      { ...review, renewable: false },
      ["calendar_read"],
      true,
      now,
    ),
    false,
  );
  assert.equal(
    canPublishGoogleReview(
      { ...review, tasks: [] },
      ["calendar_read"],
      true,
      now,
    ),
    false,
  );
  assert.equal(
    canPublishGoogleReview(
      review,
      ["calendar_read"],
      true,
      Date.parse(review.expires_at),
    ),
    false,
  );
});
