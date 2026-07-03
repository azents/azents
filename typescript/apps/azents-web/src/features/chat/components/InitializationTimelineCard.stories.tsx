import { InitializationTimelineCard } from "./InitializationTimelineCard";
import type {
  SessionInitializationEventResponse,
  SessionInitializationResponse,
  SessionInitializationStepResponse,
} from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

function step(
  sequence: number,
  stepKey: string,
  status: string,
  overrides: Partial<SessionInitializationStepResponse> = {},
): SessionInitializationStepResponse {
  return {
    id: `step-${sequence}`,
    sequence,
    step_key: stepKey,
    step_type: "create_git_worktree",
    status,
    blocking: true,
    retryable: false,
    attempt: 1,
    depends_on_step_keys: [],
    resource_descriptors: [],
    failure_reason: null,
    started_at: null,
    completed_at: null,
    failed_at: null,
    created_at: "2026-07-03T09:00:00Z",
    updated_at: "2026-07-03T09:00:00Z",
    ...overrides,
  };
}

function initialization(
  status: string,
  steps: SessionInitializationStepResponse[],
  overrides: Partial<SessionInitializationResponse> = {},
): SessionInitializationResponse {
  return {
    id: "init-1",
    status,
    failure_summary: null,
    retry_count: 0,
    started_at: "2026-07-03T09:00:00Z",
    completed_at: null,
    failed_at: null,
    canceled_at: null,
    cleaned_at: null,
    updated_at: "2026-07-03T09:02:00Z",
    steps,
    ...overrides,
  };
}

function event(
  sequence: number,
  stepId: string,
  kind: string,
  content: string,
  overrides: Partial<SessionInitializationEventResponse> = {},
): SessionInitializationEventResponse {
  return {
    id: `event-${sequence}`,
    step_id: stepId,
    sequence,
    kind,
    command_argv: null,
    content,
    exit_code: null,
    created_at: "2026-07-03T09:01:00Z",
    ...overrides,
  };
}

const runningInitialization = initialization("running", [
  step(1, "create_session_worktree", "completed", {
    completed_at: "2026-07-03T09:00:30Z",
  }),
  step(2, "register_workspace_project", "running", {
    started_at: "2026-07-03T09:00:31Z",
  }),
  step(3, "refresh_project_status", "pending"),
]);

const failedStep = step(1, "run_workspace_setup_script", "failed", {
  step_type: "run_workspace_setup_script",
  retryable: true,
  failure_reason: "The setup command exited with a non-zero status.",
  started_at: "2026-07-03T09:00:00Z",
  failed_at: "2026-07-03T09:00:08Z",
});

const failedInitialization = initialization("failed", [failedStep], {
  failure_summary: "Workspace setup failed before the first model turn.",
  failed_at: "2026-07-03T09:00:08Z",
});

const failureEvents = [
  event(1, failedStep.id, "command_started", "", {
    command_argv: ["pnpm", "install"],
  }),
  event(2, failedStep.id, "stdout", "Resolving packages…"),
  event(3, failedStep.id, "stderr", "ERR_PNPM_FETCH_404 package not found"),
  event(4, failedStep.id, "command_completed", "", { exit_code: 1 }),
  event(5, failedStep.id, "failed", "Setup dependency installation failed."),
];

const meta = {
  title: "chat/InitializationTimelineCard",
  component: InitializationTimelineCard,
  args: {
    initialization: runningInitialization,
    detailState: { type: "IDLE" },
    pendingInputCount: 1,
    onLoadDetails: () => {},
    onDeletePendingInputs: () => {},
  },
} satisfies Meta<typeof InitializationTimelineCard>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Pending: Story = {
  args: {
    initialization: initialization("pending", [
      step(1, "create_session_worktree", "pending"),
    ]),
  },
};

export const Running: Story = {};

export const Ready: Story = {
  args: {
    initialization: initialization(
      "ready",
      [
        step(1, "noop_ready", "completed", {
          blocking: false,
          completed_at: "2026-07-03T09:00:01Z",
        }),
      ],
      {
        completed_at: "2026-07-03T09:00:01Z",
      },
    ),
    pendingInputCount: 0,
  },
};

export const BlockingFailure: Story = {
  args: {
    initialization: failedInitialization,
    detailState: { type: "READY", events: failureEvents },
  },
};

export const NonBlockingWarning: Story = {
  args: {
    initialization: initialization("ready", [
      step(1, "optional_project_refresh", "failed", {
        blocking: false,
        retryable: false,
        failure_reason:
          "Project status refresh timed out, but runs may continue.",
        failed_at: "2026-07-03T09:00:12Z",
      }),
    ]),
    detailState: {
      type: "READY",
      events: [
        event(
          1,
          "step-1",
          "warning",
          "Project status refresh timed out and will be retried later.",
        ),
      ],
    },
    pendingInputCount: 0,
  },
};

export const CleanupRequired: Story = {
  args: {
    initialization: initialization("cleanup_required", [failedStep], {
      failure_summary: "Initialization left a partially-created workspace.",
      failed_at: "2026-07-03T09:00:08Z",
    }),
    detailState: { type: "READY", events: failureEvents },
  },
};

export const CleanupFailed: Story = {
  args: {
    initialization: initialization("cleanup_required", [
      step(1, "remove_session_worktree", "failed", {
        step_type: "create_git_worktree",
        retryable: true,
        failure_reason: "The worktree path is locked by another process.",
        failed_at: "2026-07-03T09:02:00Z",
      }),
    ]),
    detailState: {
      type: "READY",
      events: [
        event(1, "step-1", "stderr", "fatal: worktree is locked"),
        event(2, "step-1", "failed", "Manual cleanup is required."),
      ],
    },
  },
};
