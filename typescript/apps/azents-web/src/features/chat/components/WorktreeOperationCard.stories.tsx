import { rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { WorktreeOperationCard } from "./WorktreeOperationCard";
import type { WorktreeOperation } from "../types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: WorktreeOperationCard,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(860)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof WorktreeOperationCard>;

export default meta;

type Story = StoryObj<typeof meta>;

const baseOperation: WorktreeOperation = {
  execution: {
    id: "worktree-execution-1",
    input_buffer_id: "input-buffer-1",
    action_type: "create_git_worktree",
    action: {
      type: "create_git_worktree",
      source_project_path: "/workspace/agent/azents",
      starting_ref: "main",
    },
    status: "running",
    failure_summary: null,
    started_at: "2026-07-13T12:00:00Z",
    completed_at: null,
    failed_at: null,
    updated_at: "2026-07-13T12:00:01Z",
  },
  events: [
    {
      id: "worktree-event-1",
      action_execution_id: "worktree-execution-1",
      sequence: 1,
      kind: "command_started",
      step_key: "create_git_worktree",
      command_argv: [
        "git",
        "worktree",
        "add",
        "-b",
        "azents/session-1",
        "/workspace/agent/.azents/worktrees/session-1/azents",
        "main",
      ],
      content: "Starting Git worktree creation.",
      exit_code: null,
      created_at: "2026-07-13T12:00:01Z",
    },
    {
      id: "worktree-event-2",
      action_execution_id: "worktree-execution-1",
      sequence: 2,
      kind: "stdout",
      step_key: "create_git_worktree",
      command_argv: null,
      content: "Preparing worktree (new branch 'azents/session-1')\n",
      exit_code: null,
      created_at: "2026-07-13T12:00:02Z",
    },
  ],
};

export const Running = {
  args: { operation: baseOperation },
} satisfies Story;

export const Completed = {
  args: {
    operation: {
      execution: {
        ...baseOperation.execution,
        status: "completed",
        completed_at: "2026-07-13T12:00:04Z",
        updated_at: "2026-07-13T12:00:04Z",
      },
      events: [
        ...baseOperation.events,
        {
          id: "worktree-event-3",
          action_execution_id: "worktree-execution-1",
          sequence: 3,
          kind: "completed",
          step_key: null,
          command_argv: null,
          content: "Git worktree action completed.",
          exit_code: 0,
          created_at: "2026-07-13T12:00:04Z",
        },
      ],
    },
  },
} satisfies Story;

export const Failed = {
  args: {
    operation: {
      execution: {
        ...baseOperation.execution,
        status: "failed",
        failure_summary: "The starting ref does not exist.",
        failed_at: "2026-07-13T12:00:03Z",
        updated_at: "2026-07-13T12:00:03Z",
      },
      events: [
        ...baseOperation.events,
        {
          id: "worktree-event-3",
          action_execution_id: "worktree-execution-1",
          sequence: 3,
          kind: "stderr",
          step_key: "create_git_worktree",
          command_argv: null,
          content: "fatal: invalid reference: missing-ref\n",
          exit_code: null,
          created_at: "2026-07-13T12:00:03Z",
        },
      ],
    },
  },
} satisfies Story;
