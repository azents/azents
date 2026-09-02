import { rem } from "@mantine/core";
import { expect, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { ScheduledTasks } from "./ScheduledTasks";
import type {
  AgentResponse,
  AgentSessionResponse,
  ManagedBinding,
  ScheduledTaskCurrentCycleResponse,
  ScheduledTaskResponse,
} from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const agent: AgentResponse = {
  id: "agent_01",
  name: "Release Operator",
  description: "Coordinates release checks and recurring status updates.",
  type: "private",
  enabled: true,
  avatar: null,
  model_selection: null,
  lightweight_model_selection: null,
  selectable_model_options: [],
  main_model_label: "default",
  lightweight_model_label: "default",
  effective_context_window_tokens: 128000,
  effective_auto_compaction_threshold_tokens: 96000,
  model_parameters: null,
  system_prompt: "Coordinate release operations.",
  runtime_profile_id: null,
  runtime_profile_selection_version: 1,
  runtime_profile_available: false,
  runtime_profile_availability_reason_code: "runtime_profile_unconfigured",
  runtime_capability: "none",
  runtime_capability_version: 1,
  runtime_profile_configuration_status: "not_applicable",
  runtime_add_available: false,
  runtime_remove_available: false,
  terminal_enabled: true,
  shell_enabled: true,
  memory_enabled: true,
  tool_search_enabled: false,
  max_turns: null,
  auto_archive_ttl_days: 30,
  subagent_settings: { max_subagents: 3, max_depth: 1 },
  created_at: "2026-08-01T08:00:00Z",
  updated_at: "2026-08-01T08:00:00Z",
};

const teamSession: AgentSessionResponse = {
  id: "session_release",
  agent_id: agent.id,
  current_model_target_label: null,
  current_reasoning_effort: null,
  title: "Release coordination",
  title_source: "manual",
  status: "active",
  primary_kind: null,
  product_mode: "team",
  run_state: "idle",
  pinned: true,
  unread_terminal_run_id: null,
  auto_archive_after: null,
  archived_at: null,
  purge_after: null,
  archive_retention_days_snapshot: null,
  created_at: "2026-08-01T09:00:00Z",
  updated_at: "2026-08-16T09:00:00Z",
};

const binding: ManagedBinding = {
  id: "binding_01",
  agent_session_id: teamSession.id,
  provider: "slack",
  response_mode: "all_messages",
  resource_type: "thread",
  conversation_location: "threads",
  resource_label: "#release · weekly status thread",
  connected_at: "2026-08-02T09:00:00Z",
  disconnected_at: null,
  disconnect_reason: null,
  latest_activity_at: "2026-08-16T09:00:00Z",
  work: null,
};

const oneTimeTask: ScheduledTaskResponse = {
  id: "task_once",
  title: "Publish release readiness report",
  objective:
    "Review the release checklist, summarize blockers, and publish a concise readiness report.",
  schedule_type: "once",
  scheduled_at: "2026-08-20T16:00:00Z",
  cron_expression: null,
  timezone: null,
  next_eligible_at: "2026-08-20T16:00:00Z",
  execution_state: "idle",
  session: {
    id: teamSession.id,
    handle: "engineering",
    title: teamSession.title,
  },
  target: null,
  created_at: "2026-08-16T09:00:00Z",
  updated_at: "2026-08-16T09:00:00Z",
};

const recurringTask: ScheduledTaskResponse = {
  id: "task_cron",
  title: "Weekday release status",
  objective:
    "Collect open release blockers and post the latest status to the approved Slack thread.",
  schedule_type: "cron",
  scheduled_at: null,
  cron_expression: "0 9 * * 1-5",
  timezone: "America/Los_Angeles",
  next_eligible_at: "2026-08-17T16:00:00Z",
  execution_state: "running_with_pending",
  session: {
    id: teamSession.id,
    handle: "engineering",
    title: teamSession.title,
  },
  target: {
    channel_id: binding.id,
    provider: "slack",
    location: "threads",
    label: binding.resource_label,
  },
  created_at: "2026-08-10T09:00:00Z",
  updated_at: "2026-08-16T09:05:00Z",
};

const cycle: ScheduledTaskCurrentCycleResponse = {
  phase: "started",
  scheduled_for: "2026-08-16T16:00:00Z",
  started_at: "2026-08-16T16:00:08Z",
  progress_title: "Preparing the release status update",
  ordered_tasks: [
    "Review open release blockers",
    "Check the latest CI results",
    "Publish the approved status summary",
  ],
};

const noop = (): void => {};

const meta = {
  component: ScheduledTasks,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(1320)}>
        <div style={{ height: rem(820) }}>
          <Story />
        </div>
      </StorybookCanvas>
    ),
  ],
  args: {
    handle: "engineering",
    agent,
    sessionId: teamSession.id,
    state: {
      type: "LOADED",
      tasks: [recurringTask, oneTimeTask],
    },
    detail: {
      type: "LOADED",
      task: recurringTask,
      cycle,
      cycleLoading: false,
      cycleError: null,
    },
    form: { type: "CLOSED" },
    selectedTaskId: recurringTask.id,
    cancelTarget: null,
    mutationBusy: false,
    actionError: null,
    onSelectTask: noop,
    onOpenCreate: noop,
    onOpenEdit: noop,
    onCloseForm: noop,
    onChangeDraft: noop,
    onSave: noop,
    onRequestCancel: noop,
    onCloseCancel: noop,
    onConfirmCancel: noop,
  },
} satisfies Meta<typeof ScheduledTasks>;

export default meta;

type Story = StoryObj<typeof meta>;

export const RunningWithPending = {} satisfies Story;

export const SessionScopedManagement = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("button", { name: "Cancel task" }),
    ).toBeVisible();
    await expect(
      canvas.queryByText("Release coordination"),
    ).not.toBeInTheDocument();
  },
} satisfies Story;

export const OneTime = {
  args: {
    selectedTaskId: oneTimeTask.id,
    detail: {
      type: "LOADED",
      task: oneTimeTask,
      cycle: null,
      cycleLoading: false,
      cycleError: null,
    },
  },
} satisfies Story;

export const Empty = {
  args: {
    state: {
      type: "LOADED",
      tasks: [],
    },
    selectedTaskId: null,
    detail: null,
  },
} satisfies Story;

export const Loading = {
  args: {
    state: { type: "LOADING" },
    selectedTaskId: null,
    detail: null,
  },
} satisfies Story;

export const Error = {
  args: {
    state: {
      type: "ERROR",
      message: "Scheduled Tasks could not be loaded.",
    },
    selectedTaskId: null,
    detail: null,
  },
} satisfies Story;

export const DetailLoading = {
  args: {
    detail: { type: "LOADING" },
  },
} satisfies Story;

export const CycleLoading = {
  args: {
    detail: {
      type: "LOADED",
      task: recurringTask,
      cycle: null,
      cycleLoading: true,
      cycleError: null,
    },
  },
} satisfies Story;

export const CreateOneTime = {
  args: {
    selectedTaskId: null,
    detail: null,
    form: {
      type: "CREATE",
      taskId: null,
      draft: {
        sessionId: teamSession.id,
        title: "Publish release readiness report",
        objective: "Review the checklist and summarize remaining blockers.",
        scheduleType: "once",
        at: "2026-08-20T09:00",
        cron: "",
        timezone: "America/Los_Angeles",
        channelId: null,
      },
      bindings: [binding],
      bindingsLoading: false,
      bindingsError: null,
      error: null,
    },
  },
} satisfies Story;

export const EditRecurring = {
  args: {
    form: {
      type: "EDIT",
      taskId: recurringTask.id,
      draft: {
        sessionId: teamSession.id,
        title: recurringTask.title,
        objective: recurringTask.objective,
        scheduleType: "cron",
        at: "",
        cron: recurringTask.cron_expression ?? "",
        timezone: recurringTask.timezone ?? "UTC",
        channelId: binding.id,
      },
      bindings: [binding],
      bindingsLoading: false,
      bindingsError: null,
      error: null,
    },
  },
} satisfies Story;

export const BindingLoading = {
  args: {
    form: {
      type: "CREATE",
      taskId: null,
      draft: {
        sessionId: teamSession.id,
        title: "Daily status",
        objective: "Prepare the daily release status.",
        scheduleType: "cron",
        at: "",
        cron: "0 9 * * 1-5",
        timezone: "America/Los_Angeles",
        channelId: null,
      },
      bindings: [],
      bindingsLoading: true,
      bindingsError: null,
      error: null,
    },
  },
} satisfies Story;

export const ValidationError = {
  args: {
    form: {
      type: "CREATE",
      taskId: null,
      draft: {
        sessionId: teamSession.id,
        title: "",
        objective: "",
        scheduleType: "once",
        at: "",
        cron: "",
        timezone: "UTC",
        channelId: null,
      },
      bindings: [],
      bindingsLoading: false,
      bindingsError: null,
      error: "titleRequired",
    },
  },
} satisfies Story;

export const CancelConfirmation = {
  args: {
    cancelTarget: recurringTask,
  },
} satisfies Story;

export const Conflict = {
  args: {
    actionError: { type: "CONFLICT" },
  },
} satisfies Story;
