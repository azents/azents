import { ActionExecutionTimelineCard } from "./ActionExecutionTimelineCard";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: ActionExecutionTimelineCard,
} satisfies Meta<typeof ActionExecutionTimelineCard>;

export default meta;

type Story = StoryObj<typeof meta>;

export const FailedWorktreeAction = {
  args: {
    actionExecution: {
      provenance: "durable",
      execution: {
        id: "action-execution-1",
        input_buffer_id: "buffer-action-1",
        action_type: "create_git_worktree",
        action: {
          type: "create_git_worktree",
          source_project_path: "/workspace/agent/project",
          starting_ref: "main",
        },
        status: "failed",
        failure_summary:
          "Git worktree creation failed because the branch already exists.",
        started_at: "2026-05-19T00:00:00Z",
        completed_at: "2026-05-19T00:00:05Z",
        updated_at: "2026-05-19T00:00:05Z",
      },
      events: [
        {
          id: "action-event-1",
          action_execution_id: "action-execution-1",
          sequence: 1,
          kind: "command_started",
          step_key: "create_worktree",
          command_argv: ["git", "worktree", "add", "../project-feature"],
          content: null,
          created_at: "2026-05-19T00:00:00Z",
        },
        {
          id: "action-event-2",
          action_execution_id: "action-execution-1",
          sequence: 2,
          kind: "command_failed",
          step_key: "create_worktree",
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
      execution: {
        id: "action-execution-2",
        input_buffer_id: "buffer-action-2",
        action_type: "create_git_worktree",
        action: {
          type: "create_git_worktree",
          source_project_path: "/workspace/agent/project",
          starting_ref: "main",
        },
        status: "completed",
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
          step_key: "create_worktree",
          command_argv: ["git", "worktree", "add", "../project-feature"],
          content: "Worktree created.",
          created_at: "2026-05-19T00:00:04Z",
        },
      ],
    },
  },
} satisfies Story;

export const RunningWorktreeAction = {
  args: {
    actionExecution: {
      provenance: "durable",
      execution: {
        id: "action-execution-3",
        input_buffer_id: "buffer-action-3",
        action_type: "create_git_worktree",
        action: {
          type: "create_git_worktree",
          source_project_path: "/workspace/agent/project",
          starting_ref: "main",
        },
        status: "running",
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
          step_key: "create_worktree",
          command_argv: ["git", "worktree", "add", "../project-feature"],
          content: null,
          created_at: "2026-05-19T00:00:00Z",
        },
      ],
    },
  },
} satisfies Story;
