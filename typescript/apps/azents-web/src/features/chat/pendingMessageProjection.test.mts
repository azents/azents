import assert from "node:assert/strict";
import test from "node:test";
import { externalChannelMessagePresentation } from "./externalChannelMessage.ts";
import { pendingMailboxMessage } from "./pendingMessageProjection.ts";
import type { PendingMailboxEntry } from "./hooks/pendingMailboxState";

function scheduledEntry(
  type: "scheduled_task_trigger" | "scheduled_task_continuation",
): PendingMailboxEntry {
  const item = {
    id: `mailbox-1:${type}`,
    mailbox_item_id: "mailbox-1",
    item_key: type,
    kind: type,
    state: "pending" as const,
    created_at: "2026-08-16T00:00:00.000Z",
    presentation: {
      type,
      content: "Continue the scheduled objective until terminal.",
    },
  };
  return {
    envelope: {
      mailbox_item_id: "mailbox-1",
      session_id: "session-1",
      kind: type,
      scheduling_mode: "wake_session",
      created_at: item.created_at,
      items: [item],
    },
    item,
    deleting: false,
  };
}

for (const type of [
  "scheduled_task_trigger",
  "scheduled_task_continuation",
] as const) {
  void test(`projects ${type} without human sender provenance`, () => {
    const message = pendingMailboxMessage(scheduledEntry(type), "human-user");

    assert.equal(message.role, "user");
    assert.equal(
      message.content,
      "Continue the scheduled objective until terminal.",
    );
    assert.equal("senderUserId" in message, false);
    assert.deepEqual(message.metadata, {
      source: "scheduled_task",
      message_kind: type,
    });
  });
}

void test("renders mapped Discord mentions in pending External Channel input", () => {
  const createdAt = "2026-09-05T15:18:02.149Z";
  const presentation: Extract<
    PendingMailboxEntry["item"]["presentation"],
    { type: "external_channel_message" }
  > = {
    type: "external_channel_message",
    provider: "discord",
    resource_label: "1545815278062141480",
    resource_type: "thread",
    external_message_id: "1545815277730668735",
    sender_display_name: "Requester",
    author_type: "human",
    prompt_role: "invocation",
    body: "<@1538562331699585075> asked <@1538568337938718731> to remember.",
    reference_mappings: {
      users: {
        "1538562331699585075": "Alice",
        "1538568337938718731": "Bob",
      },
      channels: {},
    },
    original_url: null,
  };
  const item: PendingMailboxEntry["item"] = {
    id: "mailbox-1:external_channel_message:0",
    mailbox_item_id: "mailbox-1",
    item_key: "external_channel_message:0",
    kind: "external_channel_message",
    state: "pending",
    created_at: createdAt,
    presentation,
  };
  const entry: PendingMailboxEntry = {
    envelope: {
      mailbox_item_id: "mailbox-1",
      session_id: "session-1",
      kind: "external_channel_message",
      scheduling_mode: "wake_session",
      created_at: createdAt,
      items: [item],
    },
    item,
    deleting: false,
  };

  const message = pendingMailboxMessage(entry, null);
  const projected = externalChannelMessagePresentation(message);

  assert.equal(projected?.body, "@Alice asked @Bob to remember.");
});
