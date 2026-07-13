import assert from "node:assert/strict";
import test from "node:test";
import { applyWorktreeOperationHistoryEvent } from "./worktree-operation-history.ts";
import type { ChatMessage, WorktreeOperation } from "./types.ts";

const requestMessage: ChatMessage = {
  id: "request",
  role: "user",
  content: "Create a worktree.",
  createdAt: "2026-07-13T12:00:00Z",
  status: "complete",
};

const laterMessage: ChatMessage = {
  id: "later",
  role: "user",
  content: "Inspect the Project.",
  createdAt: "2026-07-13T12:00:03Z",
  status: "complete",
};

const progressOperation: WorktreeOperation = {
  execution: {
    id: "execution-1",
    input_buffer_id: "input-1",
    action_type: "create_git_worktree",
    action: {
      type: "create_git_worktree",
      source_project_path: "/workspace/agent/azents",
      starting_ref: "main",
    },
    status: "running",
    failure_summary: null,
    started_at: "2026-07-13T12:00:01Z",
    completed_at: null,
    failed_at: null,
    updated_at: "2026-07-13T12:00:01Z",
  },
  events: [
    {
      id: "progress-1",
      action_execution_id: "execution-1",
      sequence: 1,
      kind: "step_started",
      step_key: "create_git_worktree",
      command_argv: null,
      content: "Starting Git worktree action.",
      exit_code: null,
      created_at: "2026-07-13T12:00:01Z",
    },
  ],
};

const completedOperation: WorktreeOperation = {
  execution: {
    ...progressOperation.execution,
    status: "completed",
    completed_at: "2026-07-13T12:00:04Z",
    updated_at: "2026-07-13T12:00:04Z",
  },
  events: [
    ...progressOperation.events,
    {
      id: "progress-2",
      action_execution_id: "execution-1",
      sequence: 2,
      kind: "completed",
      step_key: null,
      command_argv: null,
      content: "Git worktree action completed.",
      exit_code: 0,
      created_at: "2026-07-13T12:00:04Z",
    },
  ],
};

await test("progress and result events keep one candidate at the first history position", () => {
  let messages = applyWorktreeOperationHistoryEvent([requestMessage], {
    createdAt: "2026-07-13T12:00:01Z",
    operation: progressOperation,
  });
  messages = [...messages, laterMessage];
  messages = applyWorktreeOperationHistoryEvent(messages, {
    createdAt: "2026-07-13T12:00:04Z",
    operation: completedOperation,
  });

  assert.deepEqual(
    messages.map((message) => message.id),
    ["request", "worktree-operation:execution-1", "later"],
  );
  const candidate = messages[1];
  assert.ok(candidate);
  const operation = candidate.worktreeOperation;
  assert.ok(operation);
  assert.equal(candidate.createdAt, "2026-07-13T12:00:01Z");
  assert.equal(operation.execution.status, "completed");
  assert.deepEqual(
    operation.events.map((event) => event.id),
    ["progress-1", "progress-2"],
  );
});

await test("replayed duplicate history events remain idempotent", () => {
  const once = applyWorktreeOperationHistoryEvent([], {
    createdAt: "2026-07-13T12:00:01Z",
    operation: progressOperation,
  });
  const twice = applyWorktreeOperationHistoryEvent(once, {
    createdAt: "2026-07-13T12:00:01Z",
    operation: progressOperation,
  });

  assert.equal(twice.length, 1);
  assert.equal(twice[0]?.worktreeOperation?.events.length, 1);
});
