import { rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { SessionChannels } from "./SessionChannels";
import type {
  AgentResponse,
  AgentSessionResponse,
  ManagedBinding,
  ManagedGrant,
} from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const agent: AgentResponse = {
  id: "agent_01",
  name: "Incident Coordinator",
  description: "Coordinates incident response in approved Slack channels.",
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
  system_prompt: "Coordinate incident response.",
  runtime_provider_id: null,
  shell_enabled: true,
  memory_enabled: true,
  tool_search_enabled: false,
  max_turns: null,
  subagent_settings: { max_subagents: 3, max_depth: 1 },
  created_at: "2026-07-22T01:00:00Z",
  updated_at: "2026-07-22T01:00:00Z",
};

const session: AgentSessionResponse = {
  id: "session_01",
  agent_id: agent.id,
  current_model_target_label: null,
  current_reasoning_effort: null,
  title: "Database incident",
  title_source: "manual",
  status: "active",
  primary_kind: null,
  run_state: "idle",
  unread_terminal_run_id: null,
  archived_at: null,
  purge_after: null,
  archive_retention_days_snapshot: null,
  created_at: "2026-07-22T02:00:00Z",
  updated_at: "2026-07-22T05:00:00Z",
};

const binding: ManagedBinding = {
  id: "binding_01",
  agent_session_id: session.id,
  provider: "slack",
  resource_type: "private_channel_thread",
  resource_label: "#incident-database · thread",
  status: "active",
  activation_status: "active",
  truncated_message_count: 4,
  truncated_size: 1832,
  connected_at: "2026-07-22T02:05:00Z",
  disconnected_at: null,
  disconnect_reason: null,
  latest_activity_at: "2026-07-22T05:00:00Z",
  work: {
    id: "work_01",
    status: "active",
    tasks: [{ title: "Identify the failing shard" }, { title: "Post update" }],
    state_revision: 6,
    desired_progress_revision: 8,
    progress_projected: false,
    finished_at: null,
  },
  deliveries: [
    {
      id: "delivery_01",
      operation: "progress_update",
      status: "unknown",
      error_kind: "timeout",
      error_summary: "Provider outcome could not be confirmed.",
      attempted_at: "2026-07-22T04:55:00Z",
      completed_at: "2026-07-22T04:56:00Z",
      created_at: "2026-07-22T04:55:00Z",
    },
    {
      id: "delivery_02",
      operation: "reply",
      status: "delivered",
      error_kind: null,
      error_summary: null,
      attempted_at: "2026-07-22T04:45:00Z",
      completed_at: "2026-07-22T04:45:02Z",
      created_at: "2026-07-22T04:45:00Z",
    },
  ],
};

const grant: ManagedGrant = {
  id: "grant_01",
  agent_id: agent.id,
  principal_id: "principal_01",
  principal_label: "Morgan Lee",
  scope: "session",
  agent_session_id: session.id,
  created_at: "2026-07-22T02:06:00Z",
  revoked_at: null,
};

const noop = (): void => {};

const meta = {
  component: SessionChannels,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(1020)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    handle: "engineering",
    agent,
    sessionId: session.id,
    state: {
      type: "LOADED",
      session,
      bindings: [binding],
      grants: [grant],
    },
    actionError: null,
    disconnectingId: null,
    onDisconnect: noop,
  },
} satisfies Meta<typeof SessionChannels>;

export default meta;

type Story = StoryObj<typeof meta>;

export const ActiveWithDrift = {} satisfies Story;

export const Archived = {
  args: {
    state: {
      type: "LOADED",
      session: {
        ...session,
        status: "archived",
        archived_at: "2026-07-22T05:30:00Z",
        purge_after: "2026-08-21T05:30:00Z",
        archive_retention_days_snapshot: 30,
      },
      bindings: [
        {
          ...binding,
          status: "disconnected",
          disconnected_at: "2026-07-22T05:30:00Z",
          disconnect_reason: "Session archived.",
        },
      ],
      grants: [grant],
    },
  },
} satisfies Story;

export const Empty = {
  args: {
    state: {
      type: "LOADED",
      session,
      bindings: [],
      grants: [],
    },
  },
} satisfies Story;

export const Loading = {
  args: { state: { type: "LOADING" } },
} satisfies Story;

export const Error = {
  args: {
    state: {
      type: "ERROR",
      message: "Session channel projection could not be loaded.",
    },
  },
} satisfies Story;

export const Busy = {
  args: {
    disconnectingId: binding.id,
  },
} satisfies Story;
