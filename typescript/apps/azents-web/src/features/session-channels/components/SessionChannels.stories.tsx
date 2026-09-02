import { rem } from "@mantine/core";
import { expect, fn, userEvent, within } from "storybook/test";
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
  product_mode: "team",
  run_state: "idle",
  pinned: false,
  unread_terminal_run_id: null,
  auto_archive_after: null,
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
  response_mode: "all_messages",
  resource_type: "thread",
  conversation_location: "threads",
  resource_label: "#incident-database · thread",
  connected_at: "2026-07-22T02:05:00Z",
  disconnected_at: null,
  disconnect_reason: null,
  latest_activity_at: "2026-07-22T05:00:00Z",
  work: {
    id: "work_01",
    status: "active",
    title: "Investigating database replication errors…",
    tasks: [
      {
        id: "identify-shard",
        title: "Identify the failing shard",
        status: "completed",
        details: "Compared replication lag across all database shards.",
        output: "Shard 7 is missing two WAL segments.",
        sources: [
          {
            url: "https://status.example.com/incidents/database",
            label: "Database incident dashboard",
          },
        ],
      },
      {
        id: "post-update",
        title: "Post the channel update",
        status: "failed",
        details: "Preparing a concise incident summary for participants.",
        output: "The provider rejected the first progress update.",
        sources: [],
      },
    ],
    state_revision: 6,
    desired_progress_revision: 8,
    progress_projected: false,
    projection_state: "stale",
    finished_at: null,
  },
};

const grant: ManagedGrant = {
  id: "grant_01",
  agent_id: agent.id,
  principal_id: "principal_01",
  principal_label: "Morgan Lee",
  principal_provider_user_id: "U01MORGANLEE",
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
    responseModeDrafts: {},
    updatingResponseModeId: null,
    responseModeError: null,
    onDisconnect: noop,
    onResponseModeChange: noop,
    onSaveResponseMode: noop,
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
        auto_archive_after: null,
        purge_after: "2026-08-21T05:30:00Z",
        archive_retention_days_snapshot: 30,
      },
      bindings: [
        {
          ...binding,
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

export const MentionsOnly = {
  args: {
    state: {
      type: "LOADED",
      session,
      bindings: [{ ...binding, response_mode: "mention_only" }],
      grants: [grant],
    },
  },
} satisfies Story;

export const ParentChannel = {
  args: {
    state: {
      type: "LOADED",
      session,
      bindings: [
        {
          ...binding,
          id: "binding_parent_01",
          resource_type: "parent_channel",
          conversation_location: "channel",
          resource_label: "#incident-database",
        },
      ],
      grants: [grant],
    },
  },
} satisfies Story;

export const ModeDraftChanged = {
  args: {
    responseModeDrafts: { [binding.id]: "mention_only" },
  },
} satisfies Story;

export const ModeSaving = {
  args: {
    responseModeDrafts: { [binding.id]: "mention_only" },
    updatingResponseModeId: binding.id,
  },
} satisfies Story;

export const ModeError = {
  args: {
    responseModeDrafts: { [binding.id]: "mention_only" },
    responseModeError: {
      bindingId: binding.id,
      message: "The response mode could not be saved.",
    },
  },
} satisfies Story;

export const ConfirmDisconnect = {
  args: {
    onDisconnect: fn(),
  },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: /^disconnect$/i }),
    );
    await expect(args.onDisconnect).not.toHaveBeenCalled();
    const dialog = await within(canvasElement.ownerDocument.body).findByRole(
      "dialog",
    );
    await userEvent.click(
      within(dialog).getByRole("button", { name: /^disconnect$/i }),
    );
    await expect(args.onDisconnect).toHaveBeenCalledWith(binding);
  },
} satisfies Story;
