import assert from "node:assert/strict";
import test from "node:test";
import {
  externalChannelMessagePresentation,
  externalChannelReferenceMappingsMetadata,
} from "./externalChannelMessage.ts";
import type { ChatMessage } from "./types";

function message(
  overrides: Partial<ChatMessage> = {},
  metadata: Record<string, string> = {},
): ChatMessage {
  return {
    id: "event-1",
    role: "user",
    content: "Please review the incident.",
    createdAt: "2026-07-22T01:00:00.000Z",
    metadata: {
      source: "external_channel",
      provider: "slack",
      resource_label: "#incident / thread",
      sender_display_name: "Alice",
      author_type: "human",
      authorization: "authorized_invocation",
      lifecycle: "active",
      revision_kind: "original",
      provider_created_at: "2026-07-22T00:59:00.000Z",
      ...metadata,
    },
    ...overrides,
  };
}

void test("projects validated source presentation", () => {
  const projected = externalChannelMessagePresentation(
    message({}, { original_url: "https://example.slack.com/archives/C1/p1" }),
  );

  assert.ok(projected);
  assert.equal(projected.provider, "slack");
  assert.equal(projected.resourceLabel, "#incident / thread");
  assert.equal(projected.senderDisplayName, "Alice");
  assert.equal(projected.providerTimestamp, "2026-07-22T00:59:00.000Z");
  assert.equal(
    projected.originalUrl,
    "https://example.slack.com/archives/C1/p1",
  );
});

void test("rejects unsafe original-message links", () => {
  const projected = externalChannelMessagePresentation(
    message({}, { original_url: "javascript:alert(1)" }),
  );

  assert.equal(projected?.originalUrl, null);
});

void test("keeps deleted and empty messages visible", () => {
  const deleted = externalChannelMessagePresentation(
    message(
      { content: null },
      { lifecycle: "deleted", revision_kind: "delete" },
    ),
  );
  const empty = externalChannelMessagePresentation(message({ content: " " }));

  assert.equal(deleted?.body, "[Message deleted by provider.]");
  assert.equal(empty?.body, "[Message has no text content.]");
});

void test("renders mapped Slack references without changing provider IDs", () => {
  const projected = externalChannelMessagePresentation(
    message(
      {
        content: "<@U1> asked @W2 to review <#C1|incidents> and #G2.",
      },
      {
        resource_label: "C1 / 1721600000.000100",
        provider_user_id: "U1",
        sender_display_name: "",
        reference_mappings: JSON.stringify({
          users: { U1: "Alice", W2: "Bob" },
          channels: { C1: "#incidents", G2: "#private" },
        }),
      },
    ),
  );

  assert.ok(projected);
  assert.equal(projected.resourceLabel, "#incidents");
  assert.equal(projected.senderDisplayName, "Alice");
  assert.equal(projected.providerUserId, "U1");
  assert.equal(
    projected.body,
    "@Alice asked @Bob to review #incidents and #private.",
  );
});

void test("normalizes live event reference mappings for presentation", () => {
  const referenceMappings = externalChannelReferenceMappingsMetadata({
    users: { U1: "Alice", U2: "azents", ignored: 42 },
    channels: { C1: "#incidents" },
  });

  assert.ok(referenceMappings);
  const projected = externalChannelMessagePresentation(
    message(
      { content: "<@U2> please review <#C1>." },
      { reference_mappings: referenceMappings },
    ),
  );

  assert.equal(projected?.body, "@azents please review #incidents.");
});

void test("ignores malformed reference mappings", () => {
  const projected = externalChannelMessagePresentation(
    message({ content: "<@U1>" }, { reference_mappings: "not-json" }),
  );

  assert.equal(projected?.body, "<@U1>");
});

void test("ignores ordinary Azents user messages", () => {
  assert.equal(
    externalChannelMessagePresentation(message({}, { source: "web_user" })),
    null,
  );
});
