import { rem } from "@mantine/core";
import { expect, fn, userEvent, within } from "storybook/test";
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
    canAuthorizeShared: true,
    authorizationPending: false,
    workspaceEditHref: "/w/acme/toolkits/toolkit-1/edit",
    onAuthorize: fn(),
    onDetach: () => {},
    onEdit: () => {},
    onToggle: () => {},
    onDelete: () => {},
  },
} satisfies Meta<typeof ManagedToolkitCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const WorkspaceShared = {} satisfies Story;

export const WorkspaceSentryAuthorizationRequired = {
  args: {
    item: {
      ...shared,
      readiness: "authorization_required",
      toolkit: {
        ...shared.toolkit,
        name: "Sentry",
        toolkit_type: "sentry",
      },
    },
  },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Authorize" }));
    await expect(args.onAuthorize).toHaveBeenCalledOnce();
    await expect(canvas.getByRole("button", { name: "Detach" })).toBeVisible();
  },
} satisfies Story;

export const WorkspaceSentryAuthorizationPending = {
  args: {
    ...WorkspaceSentryAuthorizationRequired.args,
    authorizationPending: true,
  },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("button", { name: "Authorize" }),
    ).toBeDisabled();
  },
} satisfies Story;

export const WorkspaceSentryWithoutManagerPermission = {
  args: {
    ...WorkspaceSentryAuthorizationRequired.args,
    canAuthorizeShared: false,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.queryByRole("button", { name: "Authorize" }),
    ).toBeNull();
    await expect(canvas.getByRole("button", { name: "Detach" })).toBeVisible();
  },
} satisfies Story;

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
        config: { auth_type: "oauth2" },
      },
    },
  },
  play: async ({ args, canvasElement }) => {
    await userEvent.click(
      within(canvasElement).getByRole("button", { name: "Authorize" }),
    );
    await expect(args.onAuthorize).toHaveBeenCalledOnce();
  },
} satisfies Story;

export const WorkspaceGitHubAuthorizationRequired = {
  args: {
    item: {
      ...shared,
      readiness: "authorization_required",
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("link", { name: "Review authorization" }),
    ).toHaveAttribute("href", "/w/acme/toolkits/toolkit-1/edit");
    await expect(
      canvas.queryByRole("button", { name: "Authorize" }),
    ).toBeNull();
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
