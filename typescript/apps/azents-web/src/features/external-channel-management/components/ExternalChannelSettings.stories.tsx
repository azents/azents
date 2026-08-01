import { rem } from "@mantine/core";
import { expect, fn, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { ExternalChannelSettings } from "./ExternalChannelSettings";
import type {
  AgentResponse,
  ManagedBlock,
  ManagedConnection,
  ManagedGrant,
  ManagedMultiConnection,
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
  runtime_profile_id: null,
  runtime_profile_selection_version: 1,
  runtime_profile_available: false,
  runtime_profile_availability_reason_code: "runtime_profile_unconfigured",
  shell_enabled: true,
  memory_enabled: true,
  tool_search_enabled: false,
  max_turns: null,
  auto_archive_ttl_days: 30,
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
  provider_app_id: "A0123456789",
  provider_tenant_id: "Engineering Workspace",
  provider_bot_user_id: "U0123456789",
  open_access_enabled: true,
  credentials_configured: true,
  capabilities: {
    inbound_events: true,
    thread_history: true,
    post_messages: true,
    update_messages: true,
    delete_messages: true,
  },
  provider_config: null,
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
  principal_provider_user_id: "U01MORGANLEE",
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
  principal_provider_user_id: "U02CONTRACTOR",
  reason: "Blocked after an approval review.",
  created_at: "2026-07-22T03:00:00Z",
  removed_at: null,
};

const associatedMultiApp: ManagedMultiConnection = {
  id: "multi_connection_01",
  provider: "slack",
  transport: "socket",
  app_mode: "multi",
  status: "active",
  provider_app_id: "A0987654321",
  provider_tenant_id: "Engineering Workspace",
  provider_bot_user_id: "U0987654321",
  credentials_configured: true,
  capabilities: {
    inbound_events: true,
    thread_history: true,
    post_messages: true,
  },
  provider_config: null,
  last_verified_at: "2026-07-25T04:30:00Z",
  last_health_at: "2026-07-25T05:00:00Z",
  socket_gap_detected_at: null,
  socket_gap_reason: null,
  disconnected_at: null,
  generation: "generation_01",
  active_agent_count: 3,
  configured_default_count: 2,
};

const manifest: SlackManifestGuidance = {
  provider: "slack",
  transport: "socket",
  bot_scopes: ["channels:history", "chat:write", "groups:history"],
  event_subscriptions: ["message.channels", "message.groups"],
  socket_mode_enabled: true,
  app_token_scope: "connections:write",
  callback_url: null,
  manifest: {
    display_information: { name: "Incident Coordinator" },
    settings: { socket_mode_enabled: true },
  },
  manifest_json: `{
  "display_information": {
    "name": "Incident Coordinator"
  },
  "settings": {
    "socket_mode_enabled": true
  }
}`,
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
      defaultResponseMode: "all_messages",
      connections: [connection],
      associatedMultiApps: [associatedMultiApp],
      grants: [grant],
      blocks: [block],
    },
    manifestState: { type: "LOADED", manifest },
    dialogState: null,
    discordDialogState: null,
    actionError: null,
    actionTarget: null,
    actionsBusy: false,
    defaultResponseMode: "all_messages",
    defaultResponseModeDraft: "all_messages",
    defaultResponseModeSaving: false,
    defaultResponseModeError: null,
    defaultResponseModeSaved: false,
    canManageWorkspaceMultiApps: true,
    onDefaultResponseModeChange: noop,
    onSaveDefaultResponseMode: noop,
    onOpenSetup: noop,
    onOpenDiscordSetup: noop,
    onOpenEdit: noop,
    onCloseDialog: noop,
    onDialogChange: noop,
    onSubmitDialog: noop,
    onCloseDiscordDialog: noop,
    onDiscordDialogChange: noop,
    onSubmitDiscordDialog: noop,
    onValidate: noop,
    onDisconnect: noop,
    onUpdateAccessPolicy: noop,
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
      defaultResponseMode: "all_messages",
      connections: [],
      associatedMultiApps: [],
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

export const DiscordSetup = {
  args: {
    discordDialogState: {
      type: "SETUP",
      appId: "",
      targetGuildId: "",
      botToken: "",
    },
  },
} satisfies Story;

export const Edit = {
  args: {
    dialogState: {
      type: "EDIT",
      connectionId: connection.id,
      appId: connection.provider_app_id ?? "",
      transport: connection.transport,
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
      defaultResponseMode: "all_messages",
      connections: [
        {
          ...connection,
          status: "degraded",
          socket_gap_detected_at: "2026-07-22T05:10:00Z",
          socket_gap_reason:
            "Socket reconnect exceeded the observation window.",
        },
      ],
      associatedMultiApps: [associatedMultiApp],
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

export const MentionsOnlyDefault = {
  args: {
    state: {
      type: "LOADED",
      defaultResponseMode: "mention_only",
      connections: [connection],
      associatedMultiApps: [associatedMultiApp],
      grants: [grant],
      blocks: [block],
    },
    defaultResponseMode: "mention_only",
    defaultResponseModeDraft: "mention_only",
  },
} satisfies Story;

export const DefaultModeChanged = {
  args: {
    defaultResponseModeDraft: "mention_only",
  },
} satisfies Story;

export const DefaultModeSaving = {
  args: {
    defaultResponseModeDraft: "mention_only",
    defaultResponseModeSaving: true,
  },
} satisfies Story;

export const DefaultModeError = {
  args: {
    defaultResponseModeDraft: "mention_only",
    defaultResponseModeError: "The response mode could not be saved.",
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
    await expect(args.onDisconnect).toHaveBeenCalledWith(connection);
  },
} satisfies Story;

export const ConfirmRevokeGrant = {
  args: {
    onRevokeGrant: fn(),
  },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /^revoke$/i }));
    await expect(args.onRevokeGrant).not.toHaveBeenCalled();
    const dialog = await within(canvasElement.ownerDocument.body).findByRole(
      "dialog",
    );
    await userEvent.click(
      within(dialog).getByRole("button", { name: /^revoke$/i }),
    );
    await expect(args.onRevokeGrant).toHaveBeenCalledWith(grant);
  },
} satisfies Story;
