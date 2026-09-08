import { rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { ManagedAgentToolkitSectionView } from "./AgentToolkitSection";
import type { AgentToolkitManagementItemResponse } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const item: AgentToolkitManagementItemResponse = {
  ownership_scope: "agent_only",
  agent_toolkit_id: null,
  readiness: "authorization_required",
  toolkit: {
    id: "toolkit-1",
    workspace_id: "workspace-1",
    toolkit_type: "mcp",
    slug: "private_mcp",
    name: "Private MCP",
    description: "Only this agent can use these settings and credentials.",
    config: {},
    prompt: null,
    has_credentials: true,
    enabled: true,
    always_expose_tools: false,
    oauth_connection: null,
    authorization_state: null,
    created_at: "2026-09-07T00:00:00Z",
    updated_at: "2026-09-07T00:00:00Z",
  },
};

const meta = {
  component: ManagedAgentToolkitSectionView,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(760)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    handle: "acme",
    agentId: "agent-1",
    state: {
      type: "READY",
      items: [item],
      toolkitTypes: [{ value: "mcp", label: "MCP" }],
      availableShared: [],
    },
    editor: { type: "CLOSED" },
    mutationState: { type: "IDLE" },
    selectedToolkitId: null,
    deleteTarget: null,
    pending: false,
    attachPending: false,
    deletePending: false,
    onSelectedToolkitChange: () => {},
    onStartAdd: () => {},
    onToolkitTypeChange: () => {},
    onConfigureSelectedType: () => {},
    onEdit: () => {},
    onCloseEditor: () => {},
    onAttach: () => {},
    onDetach: () => {},
    onToggle: () => {},
    onRequestDelete: () => {},
    onCancelDelete: () => {},
    onConfirmDelete: () => {},
  },
} satisfies Meta<typeof ManagedAgentToolkitSectionView>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Ready = {} satisfies Story;

export const Loading = {
  args: { state: { type: "LOADING" } },
} satisfies Story;

export const Error = {
  args: { state: { type: "ERROR", message: "Toolkit access is unavailable." } },
} satisfies Story;

export const MutationError = {
  args: {
    mutationState: {
      type: "ERROR",
      message: "The toolkit changed. Review the current state and try again.",
    },
  },
} satisfies Story;

export const DeleteConfirmation = {
  args: { deleteTarget: item },
} satisfies Story;

export const SelectToolkitType = {
  args: {
    editor: { type: "SELECT_TYPE", toolkitType: null },
  },
} satisfies Story;

export const SelectOwnership = {
  args: {
    editor: { type: "SELECT_TYPE", toolkitType: "mcp" },
  },
} satisfies Story;
