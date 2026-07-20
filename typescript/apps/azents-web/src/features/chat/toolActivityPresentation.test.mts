import assert from "node:assert/strict";
import test from "node:test";
import { projectChatPresentationItems } from "./toolActivityPresentation.ts";
import type {
  ChatPresentationItem,
  MessagePresentationItem,
  ToolActivityPresentationItem,
} from "./toolActivityPresentation.ts";
import type { ChatMessage } from "./types.ts";

const createdAt = "2026-07-20T00:00:00.000Z";

function message(id: string, overrides: Partial<ChatMessage>): ChatMessage {
  return {
    id,
    role: "assistant",
    content: null,
    createdAt,
    status: "complete",
    ...overrides,
  };
}

function toolMessage(id: string, callId: string): ChatMessage {
  return message(id, {
    toolCalls: [
      {
        id: callId,
        callId,
        name: "unknown.tool",
        arguments: JSON.stringify({ callId }),
        status: "completed",
        result: JSON.stringify({ ok: true }),
      },
    ],
  });
}

function activityItem(
  items: ChatPresentationItem[],
  index: number,
): ToolActivityPresentationItem {
  const item = items[index];
  assert.ok(item);
  if (item.type !== "activity") {
    assert.fail(`Expected activity at index ${index}`);
  }
  return item;
}

function messageItem(
  items: ChatPresentationItem[],
  index: number,
): MessagePresentationItem {
  const item = items[index];
  assert.ok(item);
  if (item.type !== "message") {
    assert.fail(`Expected message at index ${index}`);
  }
  return item;
}

void test("groups tool-only work across model turns", () => {
  const items = projectChatPresentationItems([
    toolMessage("tool-1", "call-1"),
    message("turn-1", { role: "turn_complete", usage: { total: 10 } }),
    message("reasoning-1", { reasoningSummary: "Continue inspecting." }),
    toolMessage("tool-2", "call-2"),
    message("turn-2", { role: "turn_complete", usage: { total: 20 } }),
    toolMessage("tool-3", "call-3"),
  ]);

  assert.equal(items.length, 1);
  const item = activityItem(items, 0);
  assert.equal(item.activity.calls.length, 3);
  assert.equal(item.activity.turnCount, 3);
  assert.deepEqual(item.activity.reasoningSummaries, ["Continue inspecting."]);
  assert.deepEqual(item.activity.usage, { total: 20 });
});

void test("visible assistant delivery closes the group", () => {
  const items = projectChatPresentationItems([
    toolMessage("tool-1", "call-1"),
    message("answer", { content: "Here is the result." }),
    toolMessage("tool-2", "call-2"),
  ]);

  assert.deepEqual(
    items.map((item) => item.type),
    ["activity", "message", "activity"],
  );
});

void test("assistant attachment delivery closes the group", () => {
  const items = projectChatPresentationItems([
    toolMessage("tool-1", "call-1"),
    message("attachment", {
      attachments: [
        {
          attachmentId: "assistant-file",
          uri: "exchange://assistant/file",
          mediaType: "text/plain",
          name: "result.txt",
        },
      ],
    }),
    toolMessage("tool-2", "call-2"),
  ]);

  assert.deepEqual(
    items.map((item) => item.type),
    ["activity", "message", "activity"],
  );
});

void test("message-owned delivery renders after its tool activity", () => {
  const items = projectChatPresentationItems([
    message("combined", {
      content: "The export is ready.",
      toolCalls: [
        {
          id: "call-1",
          callId: "call-1",
          name: "unknown.tool",
          arguments: "{}",
          status: "completed",
        },
      ],
    }),
  ]);

  assert.deepEqual(
    items.map((item) => item.type),
    ["activity", "message"],
  );
  const delivery = messageItem(items, 1);
  assert.equal(delivery.message.content, "The export is ready.");
  assert.ok(!("toolCalls" in delivery.message));
});

void test("validated deliverables close activity before later tool work", () => {
  const items = projectChatPresentationItems([
    toolMessage("tool-1", "call-1"),
    message("image", {
      providerToolCalls: [
        {
          id: "image-call",
          callId: "image-call",
          name: "image_generation",
          arguments: JSON.stringify({ prompt: "A calm activity timeline" }),
          status: "completed",
          output: "Generated one image.",
          attachments: [
            {
              attachmentId: "image-1",
              uri: "exchange://generated/image-1",
              mediaType: "image/png",
              name: "activity.png",
            },
          ],
        },
      ],
    }),
    toolMessage("tool-2", "call-2"),
  ]);

  assert.deepEqual(
    items.map((item) => item.type),
    ["activity", "deliverable", "activity"],
  );
});

void test("compaction and reasoning do not split activity", () => {
  const items = projectChatPresentationItems([
    toolMessage("tool-1", "call-1"),
    message("compaction", {
      role: "compaction",
      content: "Earlier context summary",
    }),
    message("reasoning", { reasoningSummary: "Continue after compaction." }),
    toolMessage("tool-2", "call-2"),
  ]);

  assert.equal(items.length, 1);
  const item = activityItem(items, 0);
  assert.equal(item.activity.compactionCount, 1);
  assert.equal(item.activity.calls.length, 2);
});

void test("terminal run and action placement create boundaries", () => {
  const items = projectChatPresentationItems(
    [
      toolMessage("tool-1", "call-1"),
      message("run-end", { role: "run_complete" }),
      toolMessage("tool-2", "call-2"),
      toolMessage("tool-3", "call-3"),
    ],
    new Set(["tool-3"]),
  );

  assert.equal(items.filter((item) => item.type === "activity").length, 3);
});

void test("preserves client and provider tool order", () => {
  const items = projectChatPresentationItems([
    message("mixed", {
      toolCalls: [
        {
          id: "client-call",
          name: "client.tool",
          arguments: "{}",
          status: "running",
        },
      ],
      providerToolCalls: [
        {
          id: "provider-call",
          name: "web_search",
          arguments: "{}",
          status: "running",
        },
      ],
    }),
  ]);

  const item = activityItem(items, 0);
  assert.deepEqual(
    item.activity.calls.map((call) => call.type),
    ["client", "provider"],
  );
});
