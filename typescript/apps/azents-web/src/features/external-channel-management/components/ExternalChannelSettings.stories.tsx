import { rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { ExternalChannelSettings } from "./ExternalChannelSettings";
import type {
  AgentResponse,
  ManagedBlock,
  ManagedConnection,
  ManagedGrant,
  SlackManifestGuidance,
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

const connection: ManagedConnection = {
  id: "connection_01",
  route_id: "route_01",
  agent_id: agent.id,
  provider: "slack",
  transport: "socket",
  status: "active",
  route_status: "active",
  provider_app_id: "A0123456789",
  provider_tenant_id: "Engineering Workspace",
  provider_bot_user_id: "U0123456789",
  credentials_configured: true,
  capabilities: {
    inbound_events: true,
    thread_history: true,
    post_messages: true,
    update_messages: true,
    delete_messages: true,
  },
  last_verified_at: "2026-07-22T04:30:00Z",
  last_health_at: "2026-07-22T05:00:00Z",
  socket_gap_detected_at: null,
  socket_gap_reason: null,
  disconnected_at: null,
};

const grant: ManagedGrant = {
  id: "grant_01",
  agent_id: agent.id,
  principal_id: "principal_01",
  principal_label: "Morgan Lee",
  scope: "agent",
  agent_session_id: null,
  created_at: "2026-07-22T02:00:00Z",
  revoked_at: null,
};

const block: ManagedBlock = {
  id: "block_01",
  agent_id: agent.id,
  principal_id: "principal_02",
  principal_label: "Unverified contractor",
  reason: "Blocked after an approval review.",
  created_at: "2026-07-22T03:00:00Z",
  removed_at: null,
};

const manifest: SlackManifestGuidance = {
  provider: "slack",
  transport: "socket",
  bot_scopes: ["channels:history", "chat:write", "groups:history"],
  event_subscriptions: ["message.channels", "message.groups"],
  socket_mode_enabled: true,
  app_token_scope: "connections:write",
  callback_path_template: null,
};

const noop = (): void => {};

const meta = {
  component: ExternalChannelSettings,
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
    state: {
      type: "LOADED",
      connections: [connection],
      grants: [grant],
      blocks: [block],
    },
    manifestState: { type: "LOADED", manifest },
    dialogState: null,
    actionError: null,
    actionTarget: null,
    actionsBusy: false,
    onOpenSetup: noop,
    onOpenReconnect: noop,
    onCloseDialog: noop,
    onDialogChange: noop,
    onSubmitDialog: noop,
    onValidate: noop,
    onSwitchTransport: noop,
    onDisconnect: noop,
    onRevokeGrant: noop,
    onRemoveBlock: noop,
  },
} satisfies Meta<typeof ExternalChannelSettings>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Active = {} satisfies Story;

export const Empty = {
  args: {
    state: {
      type: "LOADED",
      connections: [],
      grants: [],
      blocks: [],
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
      message: "External Channel management is temporarily unavailable.",
    },
  },
} satisfies Story;

export const Setup = {
  args: {
    dialogState: {
      type: "SETUP",
      appId: "A0123456789",
      transport: "socket",
      credentials: {
        botToken: "",
        signingSecret: "",
        appToken: "",
      },
    },
  },
} satisfies Story;

export const Degraded = {
  args: {
    state: {
      type: "LOADED",
      connections: [
        {
          ...connection,
          status: "degraded",
          socket_gap_detected_at: "2026-07-22T05:10:00Z",
          socket_gap_reason:
            "Socket reconnect exceeded the observation window.",
        },
      ],
      grants: [grant],
      blocks: [],
    },
  },
} satisfies Story;

export const Busy = {
  args: {
    actionTarget: connection.id,
    actionsBusy: true,
  },
} satisfies Story;
