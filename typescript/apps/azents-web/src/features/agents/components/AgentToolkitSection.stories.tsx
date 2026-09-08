import { rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { ManagedToolkitCard } from "./AgentToolkitSection";
import type { AgentToolkitManagementItemResponse } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const shared: AgentToolkitManagementItemResponse = {
  ownership_scope: "workspace_shared",
  agent_toolkit_id: "attachment-1",
  readiness: "ready",
  toolkit: {
    id: "toolkit-1",
    workspace_id: "workspace-1",
    toolkit_type: "github",
    slug: "github",
    name: "Workspace GitHub",
    description: "Shared repository operations.",
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
  component: ManagedToolkitCard,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(720)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    item: shared,
    pending: false,
    onDetach: () => {},
    onEdit: () => {},
    onToggle: () => {},
    onDelete: () => {},
  },
} satisfies Meta<typeof ManagedToolkitCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const WorkspaceShared = {} satisfies Story;

export const AgentOnlyAuthorizationRequired = {
  args: {
    item: {
      ...shared,
      ownership_scope: "agent_only",
      agent_toolkit_id: null,
      readiness: "authorization_required",
      toolkit: {
        ...shared.toolkit,
        id: "toolkit-2",
        name: "Private MCP",
        toolkit_type: "mcp",
      },
    },
  },
} satisfies Story;

export const AgentOnlyDisabled = {
  args: {
    item: {
      ...shared,
      ownership_scope: "agent_only",
      agent_toolkit_id: null,
      readiness: "disabled",
      toolkit: {
        ...shared.toolkit,
        id: "toolkit-3",
        name: "Private AWS",
        toolkit_type: "aws",
        enabled: false,
      },
    },
  },
} satisfies Story;
