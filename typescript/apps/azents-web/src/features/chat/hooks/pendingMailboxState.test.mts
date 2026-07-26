import assert from "node:assert/strict";
import test from "node:test";
import {
  emptyPendingMailboxState,
  pendingMailboxCorrelation,
  pendingMailboxReducer,
  selectPendingMailboxEntries,
} from "./pendingMailboxState.ts";

function envelope(id: string, keys: string[]) {
  return {
    mailbox_item_id: id,
    session_id: "session-1",
    kind: "user_message",
    scheduling_mode: "fifo",
    created_at: "2026-07-26T00:00:00Z",
    items: keys.map((key) => ({
      id: `${id}:${key}`,
      mailbox_item_id: id,
      item_key: key,
      kind: "user_message",
      state: "pending" as const,
      created_at: "2026-07-26T00:00:00Z",
      presentation: { type: "user_message" as const, content: key },
    })),
  };
}

void test("pending mailbox state preserves envelope/item order and replaces duplicate upserts", () => {
  let state = pendingMailboxReducer(emptyPendingMailboxState(), {
    type: "BASELINE_REPLACED",
    envelopes: [envelope("a", ["1", "2"]), envelope("b", ["1"])],
  });
  state = pendingMailboxReducer(state, {
    type: "UPSERTED",
    envelope: envelope("a", ["3"]),
  });
  assert.deepEqual(
    selectPendingMailboxEntries(state).map((entry) => entry.item.item_key),
    ["3", "1"],
  );
});

void test("pending mailbox state suppresses durable promotion and delayed upsert resurrection", () => {
  let state = pendingMailboxReducer(emptyPendingMailboxState(), {
    type: "BASELINE_REPLACED",
    envelopes: [envelope("a", ["1"])],
  });
  state = pendingMailboxReducer(state, {
    type: "DURABLE_PROMOTED",
    correlation: pendingMailboxCorrelation("a", "1"),
  });
  state = pendingMailboxReducer(state, {
    type: "UPSERTED",
    envelope: envelope("a", ["1"]),
  });
  assert.equal(selectPendingMailboxEntries(state).length, 0);
});
