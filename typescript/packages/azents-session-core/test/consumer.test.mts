import assert from "node:assert/strict";
import test from "node:test";
import {
  emptyPendingMailboxState,
  pendingMailboxCorrelation,
  pendingMailboxReducer,
  selectPendingMailboxEntries,
} from "@azents/session-core/pendingMailboxState";
import {
  applyProviderToolCallItem,
  providerToolCallFromPayload,
} from "@azents/session-core/providerToolCallProjection";
import { projectChatPresentationItems } from "@azents/session-core/toolActivityPresentation";
import {
  applyFunctionCallItem,
  applyFunctionCallOutput,
} from "@azents/session-core/toolCallMerge";
import { toolInputPresentation } from "@azents/session-core/toolInputPresentation";
import type { ChatMessage } from "@azents/session-core/types";

const createdAt = "2026-10-15T00:00:00Z";
type TimelineEvent = Parameters<typeof projectChatPresentationItems>[0][number];

function event(
  id: string,
  kind: TimelineEvent["kind"],
  payload: Record<string, unknown>,
): TimelineEvent {
  return {
    id,
    session_id: "session",
    kind,
    payload,
    created_at: createdAt,
    external_id: null,
    adapter: null,
    provider: null,
    model: null,
    native_format: null,
    schema_version: "1",
  };
}

void test("a host composes unknown-tool projection and ordered Activity through public exports", () => {
  const call = {
    id: "call",
    name: "future_tool",
    arguments: '{"query":"new feature"}',
    status: "running" as const,
  };
  const initial: ChatMessage[] = [];
  const running = applyFunctionCallItem(initial, call, "call", createdAt);
  const completed = applyFunctionCallOutput(running, {
    callId: "call",
    content: "Completed by a tool the host does not specialize.",
    attachments: [],
    status: "completed",
  });
  const items = projectChatPresentationItems(
    [
      event("call", "client_tool_call", {
        call_id: "call",
        name: call.name,
        arguments: call.arguments,
      }),
      event("result", "client_tool_result", {
        call_id: "call",
        status: "completed",
        output: "Completed by a tool the host does not specialize.",
      }),
    ],
    completed,
  );

  assert.equal(initial.length, 0);
  assert.equal(running[0]?.toolCalls?.[0]?.status, "running");
  assert.equal(items.length, 1);
  const item = items[0];
  assert.ok(item);
  assert.equal(item.type, "activity");
  if (item.type !== "activity") {
    assert.fail("Expected ordered tool Activity");
  }
  assert.equal(item.activity.events.length, 1);
  assert.equal(item.activity.events[0]?.status, "complete");
  const activityCall = item.activity.events[0]?.toolCall;
  assert.ok(activityCall);
  assert.equal(activityCall.type, "client");
  assert.equal(activityCall.toolCall.name, "future_tool");
  assert.deepEqual(toolInputPresentation(call.arguments), {
    type: "fields",
    fields: [{ name: "query", text: "new feature" }],
  });
});

void test("a host replaces live provider identity without duplicating the durable call", () => {
  const payload = {
    call_id: "provider-call",
    name: "future_provider_tool",
    status: "running",
    semantic: { input: null, output: "", references: [] },
  };
  const live = providerToolCallFromPayload(payload, "partial");
  const durable = providerToolCallFromPayload(
    {
      ...payload,
      status: "completed",
      semantic: { ...payload.semantic, output: "Done." },
    },
    "complete",
  );
  assert.ok(live);
  assert.ok(durable);
  const messages = applyProviderToolCallItem(
    applyProviderToolCallItem([], live, "live-id", createdAt, "partial"),
    durable,
    "durable-id",
    createdAt,
    "complete",
  );
  assert.equal(messages.length, 1);
  assert.equal(messages[0]?.id, "durable-id");
  assert.equal(messages[0]?.providerToolCalls?.[0]?.semanticOutput, "Done.");
});

void test("a host does not resurrect promoted mailbox input during baseline recovery", () => {
  const envelope = {
    mailbox_item_id: "mailbox",
    session_id: "session",
    kind: "user_message",
    scheduling_mode: "fifo",
    created_at: createdAt,
    items: [
      {
        id: "input",
        mailbox_item_id: "mailbox",
        item_key: "entry",
        kind: "user_message",
        state: "pending" as const,
        created_at: createdAt,
        presentation: { type: "user_message" as const, content: "Continue." },
      },
    ],
  };
  const pending = pendingMailboxReducer(emptyPendingMailboxState(), {
    type: "UPSERTED",
    envelope,
  });
  const promoted = pendingMailboxReducer(pending, {
    type: "DURABLE_PROMOTED",
    correlation: pendingMailboxCorrelation("mailbox", "entry"),
  });
  const recovered = pendingMailboxReducer(promoted, {
    type: "BASELINE_REPLACED",
    envelopes: [envelope],
  });
  assert.equal(selectPendingMailboxEntries(pending).length, 1);
  assert.deepEqual(selectPendingMailboxEntries(recovered), []);
});
