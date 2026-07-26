import { ActionExecutionTimelineCard } from "./ActionExecutionTimelineCard";
import type { JsonValue } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: ActionExecutionTimelineCard,
} satisfies Meta<typeof ActionExecutionTimelineCard>;

export default meta;

type Story = StoryObj<typeof meta>;

function cleanupStory({
  id,
  status,
  result,
  cancellationSummary = null,
}: {
  id: string;
  status: "completed" | "failed" | "cancelled" | "running";
  result: Record<string, JsonValue>;
  cancellationSummary?: string | null;
}): Story {
  return {
    args: {
      actionExecution: {
        provenance: status === "running" ? "live" : "durable",
        ...(status === "running"
          ? {}
          : {
              historyEventId: `history-cleanup-${id}`,
              historyCreatedAt: "2026-07-26T00:00:05Z",
            }),
        execution: {
          id: `cleanup-${id}`,
          input_buffer_id: `buffer-cleanup-${id}`,
          sender_user_id: null,
          action_type: "cleanup_orphan_git_worktrees",
          action: { type: "cleanup_orphan_git_worktrees" },
          result,
          status,
          owner_generation: 1,
          failure_summary:
            status === "failed"
              ? "One or more managed worktrees could not be removed."
              : null,
          cancellation_summary: cancellationSummary,
          started_at: "2026-07-26T00:00:00Z",
          completed_at: status === "completed" ? "2026-07-26T00:00:05Z" : null,
          failed_at: status === "failed" ? "2026-07-26T00:00:05Z" : null,
          cancelled_at: status === "cancelled" ? "2026-07-26T00:00:05Z" : null,
          updated_at: "2026-07-26T00:00:05Z",
        },
        events: [],
      },
    },
  };
}

export const CleanupZeroCandidates = cleanupStory({
  id: "zero",
  status: "completed",
  result: {
    phase: "completed",
    examined_count: 0,
    protected_count: 0,
    removed_count: 0,
    already_absent_count: 0,
    failed_count: 0,
    unresolved_count: 0,
    candidates: [],
  },
});

export const CleanupMixedResult = cleanupStory({
  id: "mixed",
  status: "failed",
  result: {
    phase: "failed",
    examined_count: 3,
    protected_count: 0,
    removed_count: 1,
    already_absent_count: 1,
    failed_count: 1,
    unresolved_count: 0,
    candidates: [
      {
        path: "/workspace/agent/.azents/worktrees/a/repo",
        outcome: "removed",
        reason_code: null,
        summary: null,
      },
      {
        path: "/workspace/agent/.azents/worktrees/b/repo",
        outcome: "already_absent",
        reason_code: null,
        summary: null,
      },
      {
        path: "/workspace/agent/.azents/worktrees/c/repo",
        outcome: "failed",
        reason_code: "git_command_failed",
        summary: "Git worktree removal failed.",
      },
    ],
  },
});

export const CleanupProtectedCandidate = cleanupStory({
  id: "protected",
  status: "completed",
  result: {
    phase: "completed",
    examined_count: 1,
    protected_count: 1,
    removed_count: 0,
    already_absent_count: 0,
    failed_count: 0,
    unresolved_count: 0,
    candidates: [
      {
        path: "/workspace/agent/.azents/worktrees/active/repo",
        outcome: "protected",
        reason_code: "active_connection",
        summary: "Connected to active Session work.",
      },
    ],
  },
});

export const CleanupLiveRemoval = cleanupStory({
  id: "live",
  status: "running",
  result: {
    phase: "processing",
    examined_count: 1,
    protected_count: 0,
    removed_count: 0,
    already_absent_count: 0,
    failed_count: 0,
    unresolved_count: 1,
    candidates: [
      {
        path: "/workspace/agent/.azents/worktrees/live/repo",
        outcome: "unresolved",
        reason_code: null,
        summary: null,
      },
    ],
  },
});

export const CleanupCancelledPartial = cleanupStory({
  id: "cancelled",
  status: "cancelled",
  cancellationSummary: "Operation cancelled by user stop.",
  result: {
    phase: "cancelled",
    examined_count: 2,
    protected_count: 0,
    removed_count: 1,
    already_absent_count: 0,
    failed_count: 0,
    unresolved_count: 1,
    candidates: [
      {
        path: "/workspace/agent/.azents/worktrees/done/repo",
        outcome: "removed",
        reason_code: null,
        summary: null,
      },
      {
        path: "/workspace/agent/.azents/worktrees/interrupted/repo",
        outcome: "unresolved",
        reason_code: "cancelled",
        summary: "Operation cancelled by user stop.",
      },
    ],
  },
});

export const FailedWorktreeAction = {
  args: {
    actionExecution: {
      provenance: "durable",
      historyEventId: "history-action-1",
      historyCreatedAt: "2026-05-19T00:00:05Z",
      execution: {
        id: "action-execution-1",
        input_buffer_id: "buffer-action-1",
        sender_user_id: null,
        action_type: "create_git_worktree",
        action: {
          type: "create_git_worktree",
          source_project_path: "/workspace/agent/project",
          starting_ref: "main",
        },
        status: "failed",
        owner_generation: 1,
        failure_summary:
          "Git worktree creation failed because the branch already exists.",
        started_at: "2026-05-19T00:00:00Z",
        failed_at: "2026-05-19T00:00:05Z",
        updated_at: "2026-05-19T00:00:05Z",
      },
      events: [
        {
          id: "action-event-1",
          action_execution_id: "action-execution-1",
          sequence: 1,
          kind: "command_started",
          step_key: "create_git_worktree",
          command_argv: ["git", "worktree", "add", "../project-feature"],
          content: null,
          created_at: "2026-05-19T00:00:00Z",
        },
        {
          id: "action-event-2",
          action_execution_id: "action-execution-1",
          sequence: 2,
          kind: "command_failed",
          step_key: "create_git_worktree",
          command_argv: null,
          content: "fatal: 'project-feature' is already checked out",
          created_at: "2026-05-19T00:00:05Z",
        },
      ],
    },
  },
} satisfies Story;

export const CompletedWorktreeAction = {
  args: {
    actionExecution: {
      provenance: "durable",
      historyEventId: "history-action-2",
      historyCreatedAt: "2026-05-19T00:00:04Z",
      execution: {
        id: "action-execution-2",
        input_buffer_id: "buffer-action-2",
        sender_user_id: null,
        action_type: "create_git_worktree",
        action: {
          type: "create_git_worktree",
          source_project_path: "/workspace/agent/project",
          starting_ref: "main",
        },
        status: "completed",
        owner_generation: 1,
        failure_summary: null,
        started_at: "2026-05-19T00:00:00Z",
        completed_at: "2026-05-19T00:00:04Z",
        updated_at: "2026-05-19T00:00:04Z",
      },
      events: [
        {
          id: "action-event-3",
          action_execution_id: "action-execution-2",
          sequence: 1,
          kind: "command_completed",
          step_key: "create_git_worktree",
          command_argv: ["git", "worktree", "add", "../project-feature"],
          content: "Worktree created.",
          exit_code: 0,
          created_at: "2026-05-19T00:00:04Z",
        },
      ],
    },
  },
} satisfies Story;

export const RunningWorktreeAction = {
  args: {
    actionExecution: {
      provenance: "live",
      execution: {
        id: "action-execution-3",
        input_buffer_id: "buffer-action-3",
        sender_user_id: null,
        action_type: "create_git_worktree",
        action: {
          type: "create_git_worktree",
          source_project_path: "/workspace/agent/project",
          starting_ref: "main",
        },
        status: "running",
        owner_generation: 1,
        failure_summary: null,
        started_at: "2026-05-19T00:00:00Z",
        completed_at: null,
        updated_at: "2026-05-19T00:00:02Z",
      },
      events: [
        {
          id: "action-event-4",
          action_execution_id: "action-execution-3",
          sequence: 1,
          kind: "command_started",
          step_key: "create_git_worktree",
          command_argv: ["git", "worktree", "add", "../project-feature"],
          content: null,
          created_at: "2026-05-19T00:00:00Z",
        },
      ],
    },
  },
} satisfies Story;

export const CancelledWorktreeAction = {
  args: {
    actionExecution: {
      provenance: "durable",
      historyEventId: "history-action-4",
      historyCreatedAt: "2026-05-19T00:00:03Z",
      execution: {
        id: "action-execution-4",
        input_buffer_id: "buffer-action-4",
        sender_user_id: null,
        action_type: "create_git_worktree",
        action: {
          type: "create_git_worktree",
          source_project_path: "/workspace/agent/project",
          starting_ref: "main",
        },
        status: "cancelled",
        owner_generation: 1,
        failure_summary: null,
        cancellation_summary: "Operation cancelled by user stop.",
        started_at: "2026-05-19T00:00:00Z",
        cancelled_at: "2026-05-19T00:00:03Z",
        updated_at: "2026-05-19T00:00:03Z",
      },
      events: [
        {
          id: "action-event-5",
          action_execution_id: "action-execution-4",
          sequence: 1,
          kind: "command_started",
          step_key: "create_git_worktree",
          command_argv: ["git", "worktree", "add", "../project-feature"],
          content: null,
          created_at: "2026-05-19T00:00:00Z",
        },
      ],
    },
  },
} satisfies Story;
