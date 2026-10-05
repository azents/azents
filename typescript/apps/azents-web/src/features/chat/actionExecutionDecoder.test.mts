import assert from "node:assert/strict";
import test from "node:test";
import {
  actionExecutionResultFromEvent,
  actionExecutionUpdatedEventFromValue,
  decodeActionExecutionProjection,
} from "./actionExecutionDecoder.ts";
import type {
  ActionExecutionProjectionResponse,
  ActionExecutionResponse,
  ChatEventResponse,
} from "@azents/public-client";

const createdAt = "2026-10-05T12:00:00Z";
const projection: ActionExecutionProjectionResponse = {
  execution: {
    id: "execution-1",
    source_mailbox_item_id: "mailbox-1",
    sender_user_id: null,
    action_type: "command",
    action: { type: "command", name: "status" },
    status: "completed",
    owner_generation: 2,
    updated_at: createdAt,
  },
  events: [
    {
      id: "event-1",
      action_execution_id: "execution-1",
      sequence: 1,
      kind: "completed",
      created_at: createdAt,
    },
  ],
};

function historyEvent(value: unknown): ChatEventResponse {
  return {
    id: "history-1",
    session_id: "session-1",
    kind: "action_execution_result",
    schema_version: "1",
    payload: { action_execution: value },
    created_at: createdAt,
  };
}

function withExecutionField(
  field: string,
  value: unknown,
): { execution: Record<string, unknown>; events: unknown[] } {
  return {
    ...projection,
    execution: { ...projection.execution, [field]: value },
  };
}

void test("complete projections decode without manufacturing optional fields", () => {
  const decoded = decodeActionExecutionProjection(projection);
  assert.deepEqual(decoded, projection);
  assert.notEqual(decoded, projection);
  assert.equal(Object.hasOwn(decoded.execution, "result"), false);
  const nullable = withExecutionField("result", null);
  assert.deepEqual(decodeActionExecutionProjection(nullable), nullable);
});

for (const field of [
  "id",
  "source_mailbox_item_id",
  "sender_user_id",
  "action_type",
  "action",
  "status",
  "owner_generation",
  "updated_at",
]) {
  void test(`rejects an execution missing ${field}`, () => {
    const execution: Record<string, unknown> = { ...projection.execution };
    delete execution[field];
    const malformed = { ...projection, execution };
    assert.equal(decodeActionExecutionProjection(malformed), null);
    assert.equal(actionExecutionResultFromEvent(historyEvent(malformed)), null);
  });
}

void test("rejects malformed execution values and action discriminants", () => {
  const malformedFields: [string, unknown][] = [
    ["sender_user_id", 1],
    ["owner_generation", 1.5],
    ["updated_at", 5],
    ["action_type", "skill"],
    ["action", { type: "unknown" }],
    ["action", { type: "command" }],
    ["action", { type: "skill", skill_path: "" }],
    ["action", { name: "status" }],
    ["failure_summary", false],
    ["completed_at", 5],
    ["result", []],
    ["result", { nested: { invalid: Number.NaN } }],
  ];
  for (const [field, value] of malformedFields) {
    assert.equal(
      decodeActionExecutionProjection(withExecutionField(field, value)),
      null,
      field,
    );
  }
});

const bridgeIdentity = {
  bridge_identity: "bridge-1",
  originating_run_id: "run-1",
  client_tool_call_id: "call-1",
  session_agent_context_id: "context-1",
  originating_agent_session_id: "session-1",
};
const supportedActions: ActionExecutionResponse["action"][] = [
  { type: "command", name: "status" },
  { type: "goal" },
  { type: "skill", skill_path: "/workspace/SKILL.md" },
  {
    type: "create_git_worktree",
    source_project_path: "/workspace/project",
    starting_ref: "main",
  },
  { type: "cleanup_orphan_git_worktrees" },
  { type: "create_session_working_folder" },
  {
    type: "agent_create_git_worktree",
    ...bridgeIdentity,
    source_project_id: "project-1",
    source_project_path: "/workspace/project",
    starting_ref: null,
    branch_name: null,
  },
  {
    type: "agent_remove_git_worktree",
    ...bridgeIdentity,
    worktree_project_id: "project-1",
    worktree_allocation_id: "allocation-1",
    worktree_path: "/workspace/worktree",
    force: false,
  },
];

void test("accepts all supported actions and rejects missing payload fields", () => {
  for (const action of supportedActions) {
    const value = {
      ...projection,
      execution: { ...projection.execution, action_type: action.type, action },
    };
    assert.deepEqual(decodeActionExecutionProjection(value), value);
    for (const field of Object.keys(action)) {
      const incomplete: Record<string, unknown> = { ...action };
      delete incomplete[field];
      assert.equal(
        decodeActionExecutionProjection({
          ...value,
          execution: { ...value.execution, action: incomplete },
        }),
        null,
        `${action.type}.${field}`,
      );
    }
  }
});

void test("validates required and optional nested event fields", () => {
  const event = projection.events[0];
  assert.ok(event);
  for (const field of [
    "id",
    "action_execution_id",
    "sequence",
    "kind",
    "created_at",
  ]) {
    const incomplete: Record<string, unknown> = { ...event };
    delete incomplete[field];
    assert.equal(
      decodeActionExecutionProjection({ ...projection, events: [incomplete] }),
      null,
      field,
    );
  }
  const malformedFields: [string, unknown][] = [
    ["sequence", 1.5],
    ["kind", null],
    ["command_argv", ["git", 1]],
    ["exit_code", 0.5],
    ["content", {}],
    ["created_at", 5],
  ];
  for (const [field, value] of malformedFields) {
    assert.equal(
      decodeActionExecutionProjection({
        ...projection,
        events: [{ ...event, [field]: value }],
      }),
      null,
    );
  }
  assert.equal(
    decodeActionExecutionProjection({ ...projection, events: [null] }),
    null,
  );
});

void test("preserves the wire string contract for timestamps and nullable Git refs", () => {
  const value: ActionExecutionProjectionResponse = {
    execution: {
      ...projection.execution,
      action_type: "agent_create_git_worktree",
      action: {
        type: "agent_create_git_worktree",
        ...bridgeIdentity,
        source_project_id: "project-1",
        source_project_path: "/workspace/project",
        starting_ref: "",
        branch_name: "",
      },
      updated_at: "2026-10-05T12:00:00",
    },
    events: projection.events.map((event) => ({
      ...event,
      created_at: "2026-10-05T12:00:00",
    })),
  };
  assert.deepEqual(decodeActionExecutionProjection(value), value);
  assert.equal(
    decodeActionExecutionProjection({
      ...value,
      execution: {
        ...value.execution,
        action_type: "create_git_worktree",
        action: {
          type: "create_git_worktree",
          source_project_path: "/workspace/project",
          starting_ref: "",
        },
      },
    }),
    null,
  );
});

void test("allows additive response fields but strips them at ingress", () => {
  assert.deepEqual(
    decodeActionExecutionProjection({
      ...projection,
      future: true,
      execution: {
        ...projection.execution,
        future: true,
        action: { ...projection.execution.action, future: true },
      },
      events: projection.events.map((event) => ({ ...event, future: true })),
    }),
    projection,
  );
});

void test("history decoding preserves provenance and skips malformed results", () => {
  assert.deepEqual(actionExecutionResultFromEvent(historyEvent(projection)), {
    ...projection,
    provenance: "durable",
    historyEventId: "history-1",
    historyCreatedAt: createdAt,
  });
  assert.equal(actionExecutionResultFromEvent(historyEvent(null)), null);
  assert.equal(
    actionExecutionResultFromEvent({
      ...historyEvent(projection),
      kind: "user_message",
    }),
    null,
  );
});

void test("live decoding validates session identity and the complete projection", () => {
  const event = {
    type: "action_execution_updated",
    session_id: "session-1",
    action_execution: projection,
  };
  assert.deepEqual(actionExecutionUpdatedEventFromValue(event, "session-1"), {
    ...event,
    action_execution: { ...projection, provenance: "live" },
  });
  assert.equal(actionExecutionUpdatedEventFromValue(event, "session-2"), null);
  assert.equal(
    actionExecutionUpdatedEventFromValue(
      { ...event, action_execution: {} },
      "session-1",
    ),
    null,
  );
  assert.equal(actionExecutionUpdatedEventFromValue(null, "session-1"), null);
});
