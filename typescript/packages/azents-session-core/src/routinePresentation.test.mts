import assert from "node:assert/strict";
import test from "node:test";
import { isLivePartialHistoryEvent } from "./chatLiveHistoryProjection.ts";
import {
  decodeRoutineInput,
  decodeRoutineJudgment,
  isRoutineToolCall,
  routineEventMessage,
} from "./routinePresentation.ts";
import { projectChatPresentationItems } from "./toolActivityPresentation.ts";
import type { ChatMessage } from "./types.ts";
import type { ChatEventResponse } from "@azents/public-client/types";

function event(
  kind: ChatEventResponse["kind"],
  id: string,
  payload: Record<string, unknown>,
): ChatEventResponse {
  return {
    id,
    kind,
    session_id: "session-1",
    payload,
    external_id: null,
    provider: "openai",
    model: "saved-model",
    schema_version: "1",
    created_at: "2026-10-19T00:00:00Z",
  };
}
function payload(): Record<string, unknown> {
  return {
    judgment_id: "judgment-1",
    considered: [
      { routine_id: "routine-a", slug: "traffic", title: "Traffic anomalies" },
      { routine_id: "routine-b", slug: "releases", title: "Release news" },
    ],
    status: "completed",
    decision: {
      decisions: [
        { routine_id: "routine-b", act: false },
        { routine_id: "routine-a", act: true },
      ],
    },
    error: null,
    usage: {
      prompt_tokens: 99000,
      completion_tokens: 999,
      total_tokens: 99999,
      cached_tokens: 0,
      cost_usd: 1.25,
    },
  };
}

void test("Routine tool identity requires both the reserved source slug and type", () => {
  const call = {
    id: "call",
    name: "list_routines",
    arguments: "{}",
    status: "completed" as const,
  };
  assert.equal(isRoutineToolCall(call), true);
  assert.equal(isRoutineToolCall({ ...call, toolkitSource: null }), true);
  for (const [toolkit_slug, toolkit_type, expected] of [
    ["routine", "routine", false],
    ["routine", "mcp", false],
    ["foreign", "routine", false],
  ] as const) {
    assert.equal(
      isRoutineToolCall({
        ...call,
        toolkitSource: {
          toolkit_config_id: "source",
          toolkit_name: "Source",
          toolkit_slug,
          toolkit_type,
        },
      }),
      expected,
    );
  }
});

void test("joint Structured judgment preserves false decisions and considered ordering", () => {
  const view = decodeRoutineJudgment(payload());
  assert.equal(view.type, "AVAILABLE");
  if (view.type !== "AVAILABLE") {
    throw new Error("Expected available judgment");
  }
  assert.equal(view.status, "completed");
  assert.deepEqual(
    view.items.map((item) => [item.routineId, item.act]),
    [
      ["routine-a", true],
      ["routine-b", false],
    ],
  );
  assert.equal(view.callUsage?.totalTokens, 99999);
  assert.equal(view.callUsage?.cachedTokens, 0);
  assert.equal(view.callUsage?.reasoningTokens, null);
});

for (const status of ["failed", "cancelled"]) {
  void test(`${status} judgment retains failure and unknown usage without no-action decisions`, () => {
    const view = decodeRoutineJudgment({
      ...payload(),
      status,
      decision: null,
      error: "The model operation could not complete.",
      usage: null,
    });
    assert.equal(view.type, "AVAILABLE");
    if (view.type !== "AVAILABLE") {
      throw new Error("Expected available judgment");
    }
    assert.equal(view.status, status);
    assert.equal(view.callUsage, null);
    assert.ok(view.items.every((item) => item.act === null));
    assert.equal(view.error, "The model operation could not complete.");
  });
}

void test("invalid or foreign Structured evidence is unavailable, never synthetic no-action", () => {
  for (const invalid of [
    { ...payload(), considered: [] },
    {
      ...payload(),
      decision: {
        decisions: [
          { routine_id: "routine-a", act: false },
          { routine_id: "routine-a", act: true },
        ],
      },
    },
    {
      ...payload(),
      decision: {
        decisions: [
          { routine_id: "routine-a", act: false },
          { routine_id: "foreign", act: true },
        ],
      },
    },
    {
      ...payload(),
      decision: { decisions: [{ routine_id: "routine-a", act: "false" }] },
    },
    { ...payload(), status: "failed", decision: null, error: null },
    {
      ...payload(),
      usage: { prompt_tokens: -1, completion_tokens: 0, total_tokens: 1 },
    },
    { ...payload(), private_reasoning: "Unrequested explanation" },
  ]) {
    assert.deepEqual(decodeRoutineJudgment(invalid), { type: "UNAVAILABLE" });
  }
});

void test("live and reload judgment use a stable separate message with call-owned usage only", () => {
  const observation = event("routine_judgment", "judgment-event", payload());
  const live = routineEventMessage(observation);
  const reload = routineEventMessage(structuredClone(observation));
  assert.deepEqual(live, reload);
  assert.equal(live?.role, "routine_judgment");
  assert.equal(live?.usage, undefined);
  assert.equal(live?.routineJudgment?.model, "saved-model");
  assert.equal(live?.routineJudgment?.provider, "openai");
  assert.equal(isLivePartialHistoryEvent("routine_judgment", false), false);
});

void test("passive judgment cannot borrow or replace ordinary activity-turn usage", () => {
  const first = event("reasoning", "reasoning-a", { summary: "Ordinary work" });
  const judgment = event("routine_judgment", "judgment-event", payload());
  const last = event("reasoning", "reasoning-b", {
    summary: "More ordinary work",
  });
  const observation = routineEventMessage(judgment);
  assert.ok(observation);
  const messages: ChatMessage[] = [
    {
      id: first.id,
      role: "assistant",
      content: null,
      reasoningSummary: "Ordinary work",
      createdAt: first.created_at,
    },
    observation,
    {
      id: last.id,
      role: "assistant",
      content: null,
      reasoningSummary: "More ordinary work",
      createdAt: last.created_at,
    },
  ];
  const items = projectChatPresentationItems(
    [
      first,
      event("turn_marker", "turn-a", {
        run_id: "run-a",
        usage: { total_tokens: 11 },
      }),
      judgment,
      last,
      event("turn_marker", "turn-b", {
        run_id: "run-b",
        usage: { total_tokens: 22 },
      }),
    ],
    messages,
  );
  assert.deepEqual(
    items.map((item) => item.type),
    ["activity", "message", "activity"],
  );
  assert.deepEqual(
    items.flatMap((item) =>
      item.type === "activity" ? [item.activity.usage?.total_tokens] : [],
    ),
    [11, 22],
  );
});

void test("ordinary admitted contexts and notifications are explicit semantic messages without usage", () => {
  const input = {
    executions: [
      {
        routine_id: "routine-a",
        execution_id: "occurrence-a",
        slug: "traffic",
        title: "Traffic anomalies",
      },
    ],
    content: "Original objective and admitted source context.",
  };
  for (const kind of ["routine_trigger", "routine_continuation"] as const) {
    const message = routineEventMessage(event(kind, kind, input));
    assert.equal(message?.role, kind);
    assert.equal(message?.routineInput?.content, input.content);
    assert.equal(message?.usage, undefined);
  }
  assert.equal(
    decodeRoutineInput({
      ...input,
      executions: [input.executions[0], input.executions[0]],
    }),
    null,
  );
  const notification = routineEventMessage(
    event("routine_notification", "notification", {
      execution_id: "occurrence-a",
      slug: "traffic",
      title: "Traffic anomalies",
      content: "A verified change needs attention.",
      attachments: [],
    }),
  );
  assert.equal(notification?.role, "assistant");
  assert.equal(notification?.content, "A verified change needs attention.");
  assert.equal(notification?.usage, undefined);
});
