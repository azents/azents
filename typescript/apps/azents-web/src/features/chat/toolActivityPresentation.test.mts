import assert from "node:assert/strict";
import test from "node:test";
import { projectChatPresentationItems } from "./toolActivityPresentation.ts";
import type { ChatMessage } from "./types.ts";

type TimelineEvent = Parameters<typeof projectChatPresentationItems>[0][number];

const createdAt = "2026-07-20T00:00:00.000Z";

function event(
  id: string,
  kind: TimelineEvent["kind"],
  payload: Record<string, unknown>,
): TimelineEvent {
  return {
    id,
    session_id: "session-1",
    kind,
    payload,
    model_order: 1,
    external_id: null,
    adapter: null,
    provider: null,
    model: null,
    native_format: null,
    schema_version: "1",
    created_at: createdAt,
  };
}

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

function clientToolMessage(
  id: string,
  callId: string,
  toolName = "github__issue_write",
  toolkitSource?: NonNullable<
    ChatMessage["toolCalls"]
  >[number]["toolkitSource"],
): ChatMessage {
  return message(id, {
    toolCalls: [
      {
        id: callId,
        callId,
        name: toolName,
        arguments: "{}",
        status: "completed",
        result: "ok",
        toolkitSource,
      },
    ],
  });
}

function activityAt(
  items: ReturnType<typeof projectChatPresentationItems>,
  index: number,
) {
  const item = items[index];
  assert.ok(item);
  if (item.type !== "activity") {
    assert.fail(`Expected activity at index ${index}`);
  }
  return item.activity;
}

void test("preserves reasoning and client tool chronology from raw events", () => {
  const tool = clientToolMessage("tool-message", "call-1");
  const items = projectChatPresentationItems(
    [
      event("reasoning-1", "reasoning", { summary: "Inspect the issue." }),
      event("call-1", "client_tool_call", {
        call_id: "call-1",
        name: "github__issue_write",
        arguments: "{}",
      }),
      event("result-1", "client_tool_result", {
        call_id: "call-1",
        status: "completed",
        output: "ok",
      }),
      event("reasoning-2", "reasoning", { summary: "Verify the result." }),
    ],
    [
      message("reasoning-1", {
        metadata: { event_render_key: "reasoning:event:reasoning-1" },
        reasoningSummary: "Inspect the issue.",
      }),
      tool,
      message("reasoning-2", {
        metadata: { event_render_key: "reasoning:event:reasoning-2" },
        reasoningSummary: "Verify the result.",
      }),
    ],
  );

  assert.equal(items.length, 1);
  assert.deepEqual(
    activityAt(items, 0).events.map((activityEvent) => activityEvent.kind),
    ["reasoning", "tool", "reasoning"],
  );
  assert.equal(activityAt(items, 0).startedAt, createdAt);
});

void test("matches native reasoning identity from the raw event", () => {
  const reasoningMessage = message("reasoning-message", {
    metadata: { event_render_key: "reasoning:native:reasoning-native-1" },
    reasoningSummary: "Inspect native reasoning.",
  });
  const items = projectChatPresentationItems(
    [
      event("reasoning-event", "reasoning", {
        native_artifact: { item: { id: "reasoning-native-1" } },
      }),
    ],
    [reasoningMessage],
  );

  const activityEvent = activityAt(items, 0).events[0];
  assert.ok(activityEvent);
  assert.equal(activityEvent.message?.id, reasoningMessage.id);
});

void test("keeps skill-loaded messages inside Activity", () => {
  const skillMessage = message("skill-message", {
    role: "skill_loaded",
    content: "Loaded skill body.",
    metadata: { name: "frontend-design" },
  });
  const items = projectChatPresentationItems(
    [
      event("skill-message", "skill_loaded", {
        name: "frontend-design",
      }),
    ],
    [skillMessage],
  );

  assert.equal(items.length, 1);
  const activity = activityAt(items, 0);
  assert.deepEqual(
    activity.events.map((activityEvent) => activityEvent.kind),
    ["skill"],
  );
  assert.equal(activity.events[0]?.message?.id, skillMessage.id);
});

void test("uses immutable Toolkit source identity as the summary category", () => {
  const toolkitSource = {
    toolkit_config_id: "toolkit-config-1",
    toolkit_type: "github",
    toolkit_name: "GitHub",
    toolkit_slug: "github",
  };
  const items = projectChatPresentationItems(
    [
      event("call-1", "client_tool_call", {
        call_id: "call-1",
        name: "github__issue_write",
        arguments: "{}",
        toolkit_source: toolkitSource,
      }),
    ],
    [
      clientToolMessage(
        "tool-message",
        "call-1",
        "github__issue_write",
        toolkitSource,
      ),
    ],
  );

  const activityEvent = activityAt(items, 0).events[0];
  assert.ok(activityEvent);
  assert.deepEqual(activityEvent.category, {
    key: "toolkit:toolkit-config-1",
    label: "GitHub",
  });
});

void test("groups apply_patch with file-edit activity", () => {
  const tool = clientToolMessage("tool-message", "call-1", "apply_patch");
  const items = projectChatPresentationItems(
    [
      event("call-1", "client_tool_call", {
        call_id: "call-1",
        name: "apply_patch",
        arguments: "{}",
      }),
    ],
    [tool],
  );

  const activityEvent = activityAt(items, 0).events[0];
  assert.ok(activityEvent);
  assert.deepEqual(activityEvent.category, { key: "edit", label: "edit" });
});

void test("closes Activity at an action-execution message boundary", () => {
  const firstTool = clientToolMessage("tool-message-1", "call-1");
  const secondTool = clientToolMessage("tool-message-2", "call-2");
  const items = projectChatPresentationItems(
    [
      event("call-event-1", "client_tool_call", {
        call_id: "call-1",
        name: "github__issue_write",
        arguments: "{}",
      }),
      event("call-event-2", "client_tool_call", {
        call_id: "call-2",
        name: "github__issue_write",
        arguments: "{}",
      }),
    ],
    [firstTool, secondTool],
    new Set(["tool-message-2"]),
  );

  assert.deepEqual(
    items.map((item) => item.type),
    ["activity", "activity"],
  );
  assert.equal(activityAt(items, 0).events.length, 1);
  assert.equal(activityAt(items, 1).events.length, 1);
});

void test("keeps an attachment-bearing tool outside Activity and closes the group", () => {
  const attachedTool = clientToolMessage("attached-tool", "call-2");
  const attachedCall = attachedTool.toolCalls?.[0];
  assert.ok(attachedCall);
  const attachedWithFile: ChatMessage = {
    ...attachedTool,
    toolCalls: [
      {
        ...attachedCall,
        attachments: [
          {
            attachmentId: "file-1",
            uri: "exchange://generated/report.txt",
            mediaType: "text/plain",
            name: "report.txt",
          },
        ],
      },
    ],
  };
  const items = projectChatPresentationItems(
    [
      event("reasoning-1", "reasoning", { summary: "Prepare export." }),
      event("call-2", "client_tool_call", {
        call_id: "call-2",
        name: "present_file",
        arguments: "{}",
      }),
      event("reasoning-2", "reasoning", { summary: "Continue." }),
    ],
    [
      message("reasoning-1", {
        metadata: { event_render_key: "reasoning:event:reasoning-1" },
        reasoningSummary: "Prepare export.",
      }),
      attachedWithFile,
      message("reasoning-2", {
        metadata: { event_render_key: "reasoning:event:reasoning-2" },
        reasoningSummary: "Continue.",
      }),
    ],
  );

  assert.deepEqual(
    items.map((item) => item.type),
    ["activity", "message", "activity"],
  );
});

void test("uses compaction start and result messages as Activity cutoffs", () => {
  const beforeTool = clientToolMessage("before-tool", "before-call", "read");
  const afterTool = clientToolMessage("after-tool", "after-call", "write");
  const items = projectChatPresentationItems(
    [
      event("before-call", "client_tool_call", {
        call_id: "before-call",
        name: "read",
        arguments: "{}",
      }),
      event("compaction-start", "compaction_marker", {
        compaction_id: "compaction-1",
        status: "started",
      }),
      event("compaction-result", "compaction_summary", {
        compaction_id: "compaction-1",
        content: "Compaction summary.",
      }),
      event("after-call", "client_tool_call", {
        call_id: "after-call",
        name: "write",
        arguments: "{}",
      }),
    ],
    [
      beforeTool,
      message("compaction-start", { role: "compaction_started" }),
      message("compaction-result", {
        role: "compaction",
        content: "Compaction summary.",
      }),
      afterTool,
    ],
  );

  assert.deepEqual(
    items.map((item) => item.type),
    ["activity", "message", "message", "activity"],
  );
  assert.equal(activityAt(items, 0).events.length, 1);
  assert.equal(activityAt(items, 3).events.length, 1);

  const startMarker = items[1];
  const resultMarker = items[2];
  assert.ok(startMarker?.type === "message");
  assert.ok(resultMarker?.type === "message");
  assert.equal(startMarker.message.role, "compaction_started");
  assert.equal(resultMarker.message.role, "compaction");
});
