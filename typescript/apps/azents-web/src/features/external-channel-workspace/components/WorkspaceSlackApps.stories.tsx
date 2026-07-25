import { rem } from "@mantine/core";
import { fn } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { WorkspaceSlackApps } from "./WorkspaceSlackApps";
import type { WorkspaceSlackAppsContainerOutput } from "../containers/useWorkspaceSlackAppsContainer";
import type {
  ManagedChannelDefault,
  ManagedMultiConnection,
  ManagedMultiRoute,
  ManagedSlackManagementHandoff,
} from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import type { ReactElement } from "react";

const connection: ManagedMultiConnection = {
  id: "multi_connection_01",
  provider: "slack",
  transport: "socket",
  app_mode: "multi",
  status: "active",
  provider_app_id: "A0123456789",
  provider_tenant_id: "Engineering Workspace",
  provider_bot_user_id: "U0123456789",
  credentials_configured: true,
  capabilities: {
    inbound_events: true,
    thread_history: true,
    post_messages: true,
  },
  last_verified_at: "2026-07-25T04:30:00Z",
  last_health_at: "2026-07-25T05:00:00Z",
  socket_gap_detected_at: null,
  socket_gap_reason: null,
  disconnected_at: null,
  generation: "generation_01",
};

const availableRoute: ManagedMultiRoute = {
  id: "multi_route_01",
  agent_id: "agent_incident",
  agent_id_snapshot: "agent_incident",
  agent_name: "Incident Coordinator",
  catalog_status: "available",
  catalog_removed_at: null,
  created_at: "2026-07-25T01:00:00Z",
  updated_at: "2026-07-25T01:00:00Z",
};

const removedRoute: ManagedMultiRoute = {
  id: "multi_route_02",
  agent_id: null,
  agent_id_snapshot: "agent_archive",
  agent_name: "Archive Helper",
  catalog_status: "removed",
  catalog_removed_at: "2026-07-25T03:00:00Z",
  created_at: "2026-07-25T01:00:00Z",
  updated_at: "2026-07-25T03:00:00Z",
};

const routes: ManagedMultiRoute[] = [availableRoute, removedRoute];

const activeDefault: ManagedChannelDefault = {
  id: "channel_default_01",
  provider_channel_id: "C0123456789",
  route_id: availableRoute.id,
  agent_id: availableRoute.agent_id,
  agent_name: availableRoute.agent_name,
  status: "active",
  configured_by_user_id: "user_01",
  invalidated_at: null,
  invalidation_reason: null,
  created_at: "2026-07-25T02:00:00Z",
  updated_at: "2026-07-25T02:00:00Z",
};

const defaults: ManagedChannelDefault[] = [activeDefault];

const handoff: ManagedSlackManagementHandoff = {
  interaction_id: "interaction_01",
  connection_id: connection.id,
  provider: "slack",
  provider_app_id: connection.provider_app_id,
  provider_channel_id: activeDefault.provider_channel_id,
  provider_thread_id: null,
  expires_at: "2026-07-25T08:00:00Z",
};

const noop = (): void => {};

const args: WorkspaceSlackAppsContainerOutput = {
  handle: "engineering",
  state: { type: "LOADED", connections: [connection] },
  selectedConnectionId: connection.id,
  selectedConnection: connection,
  routeItems: routes,
  defaultItems: defaults,
  routeOffset: 0,
  defaultOffset: 0,
  routeImpact: null,
  connectionImpact: null,
  previewRouteId: null,
  previewDisconnect: false,
  setupDraft: {
    appId: "",
    transport: "http",
    credentials: { botToken: "", signingSecret: "", appToken: "" },
  },
  editDraft: {
    appId: connection.provider_app_id ?? "",
    transport: connection.transport,
    credentials: { botToken: "", signingSecret: "", appToken: "" },
  },
  agentId: "",
  providerChannelId: "",
  defaultRouteId: "",
  focusedHandoff: false,
  handoffState: { handoff: null, message: null },
  busy: false,
  actionError: null,
  canManage: true,
  onSelectConnection: noop,
  onSetupDraftChange: noop,
  onEditDraftChange: noop,
  onAgentIdChange: noop,
  onProviderChannelIdChange: noop,
  onDefaultRouteIdChange: noop,
  onCreate: noop,
  onSaveConnection: noop,
  onValidate: noop,
  onPreviewRouteRemoval: noop,
  onRemoveRoute: noop,
  onReenableRoute: noop,
  onAddRoute: noop,
  onSetDefault: noop,
  onClearDefault: noop,
  onPreviewDisconnect: noop,
  onDisconnect: noop,
  onCancelPreview: noop,
  onRoutePage: noop,
  onDefaultPage: noop,
};

const meta = {
  title: "External channels/Workspace Slack Apps",
  component: WorkspaceSlackApps,
  decorators: [
    (Story: () => ReactElement): ReactElement => (
      <StorybookCanvas maxWidth={rem(1320)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args,
} satisfies Meta<typeof WorkspaceSlackApps>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Active = {} satisfies Story;

export const Loading = {
  args: { state: { type: "LOADING" } },
} satisfies Story;

export const Empty = {
  args: {
    state: { type: "LOADED", connections: [] },
    selectedConnectionId: null,
    selectedConnection: null,
    routeItems: [],
    defaultItems: [],
  },
} satisfies Story;

export const PermissionDenied = {
  args: {
    state: {
      type: "FORBIDDEN",
      message: "Workspace permission is required.",
    },
    canManage: false,
  },
} satisfies Story;

export const ReconnectRequired = {
  args: {
    selectedConnection: { ...connection, status: "reconnect_required" },
    state: {
      type: "LOADED",
      connections: [{ ...connection, status: "reconnect_required" }],
    },
  },
} satisfies Story;

export const RouteImpactPreview = {
  args: {
    previewRouteId: availableRoute.id,
    routeImpact: {
      route_id: availableRoute.id,
      generation: "generation_02",
      active_default_count: 1,
      active_binding_count: 2,
      bound_resource_count: 2,
      open_admission_count: 1,
      pending_access_request_count: 0,
      pending_context_count: 0,
      affected_defaults: [],
      affected_bindings: [],
    },
    onRemoveRoute: fn(),
  },
} satisfies Story;

export const DisconnectImpactPreview = {
  args: {
    previewDisconnect: true,
    connectionImpact: {
      connection_id: connection.id,
      generation: "generation_02",
      active_route_count: 1,
      active_default_count: 1,
      active_binding_count: 2,
      bound_resource_count: 2,
      open_admission_count: 1,
      pending_access_request_count: 0,
      pending_context_count: 0,
      affected_defaults: [],
      affected_bindings: [],
    },
    onDisconnect: fn(),
  },
} satisfies Story;

export const FocusedSlackHandoff = {
  args: {
    focusedHandoff: true,
    providerChannelId: handoff.provider_channel_id,
    handoffState: { handoff, message: null },
  },
} satisfies Story;

export const ExpiredSlackHandoff = {
  args: {
    focusedHandoff: true,
    handoffState: {
      handoff: null,
      message: "The Slack management handoff has expired.",
    },
  },
} satisfies Story;
