import assert from "node:assert/strict";
import test from "node:test";
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
