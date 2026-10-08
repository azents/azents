import { rem, Text } from "@mantine/core";
import { expect, fn, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { ManagedAgentToolkitSectionView } from "./ManagedAgentToolkitSection";
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
    deleteTarget: null,
    pending: false,
    attachPending: false,
    attachPendingId: null,
    setupPending: false,
    deletePending: false,
    canAuthorizeShared: true,
    authorizationPendingId: null,
    onAuthorize: () => {},
    onStartAdd: () => {},
    onCatalogTabChange: fn(),
    onConfigureType: fn(),
    onDetails: fn(),
    onCompleteSetup: fn(),
    onSetupPendingChange: fn(),
    onRetryRead: fn(),
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

export const MobileReady = {
  parameters: { testViewport: { width: 390, height: 844 } },
  args: {
    state: {
      type: "READY",
      items: [
        {
          ...item,
          readiness: "ready",
          toolkit: {
            ...item.toolkit,
            name: "Production MCP connection for the engineering release workspace",
          },
        },
      ],
      toolkitTypes: [{ value: "mcp", label: "MCP" }],
      availableShared: [],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const view = canvasElement.ownerDocument.defaultView;
    await expect(view?.innerWidth).toBe(390);
    await expect(view?.innerHeight).toBe(844);
    const name = canvas.getByText(
      "Production MCP connection for the engineering release workspace",
    );
    const ownership = canvas.getByText("This agent only");
    const readiness = canvas.getByText("Ready");
    const action = canvas.getByRole("button", { name: "View details" });
    await expect(name).toBeVisible();
    await expect(ownership).toBeVisible();
    await expect(readiness).toBeVisible();
    await expect(action).toBeVisible();
    await expect(name.getBoundingClientRect().top).toBeLessThanOrEqual(
      ownership.getBoundingClientRect().top,
    );
    await expect(ownership.getBoundingClientRect().top).toBeLessThanOrEqual(
      readiness.getBoundingClientRect().top,
    );
    await expect(readiness.getBoundingClientRect().top).toBeLessThanOrEqual(
      action.getBoundingClientRect().top,
    );
    const documentElement = canvasElement.ownerDocument.documentElement;
    await expect(documentElement.scrollWidth).toBeLessThanOrEqual(
      documentElement.clientWidth,
    );
  },
} satisfies Story;

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
  args: { deleteTarget: item, onConfirmDelete: fn() },
  play: async ({ canvasElement, args }) => {
    const body = within(canvasElement.ownerDocument.body);
    await expect(
      body.getByRole("dialog", { name: "Delete agent-only toolkit" }),
    ).toBeVisible();
    await expect(
      body.getByText(
        "Delete Private MCP from this agent and permanently remove its stored credentials?",
      ),
    ).toBeVisible();
    await userEvent.click(body.getByRole("button", { name: "Delete toolkit" }));
    await expect(args.onConfirmDelete).toHaveBeenCalledTimes(1);
  },
} satisfies Story;

export const NewToolkitCatalog = {
  args: {
    editor: { type: "CATALOG", tab: "new" },
    state: {
      type: "READY",
      items: [],
      availableShared: [],
      toolkitTypes: [
        { value: "github", label: "GitHub" },
        { value: "notion", label: "Notion" },
        { value: "sentry", label: "Sentry" },
        { value: "mcp", label: "MCP" },
        { value: "aws", label: "AWS" },
        { value: "gcp", label: "Google Cloud" },
        { value: "google_analytics", label: "Google Analytics" },
        { value: "kubernetes", label: "Kubernetes" },
        { value: "brave_search", label: "Brave Search" },
        { value: "envvar", label: "Environment variables" },
      ],
    },
  },
  play: async ({ canvasElement, args }) => {
    const body = within(canvasElement.ownerDocument.body);
    await expect(
      body.getByRole("tab", { name: "New Toolkit" }),
    ).toHaveAttribute("aria-selected", "true");
    await userEvent.click(body.getByRole("button", { name: "MCP" }));
    await expect(args.onConfigureType).toHaveBeenCalledWith("mcp");
  },
} satisfies Story;

export const WorkspaceToolkitCatalog = {
  args: {
    editor: { type: "CATALOG", tab: "workspace" },
  },
  play: async ({ canvasElement }) => {
    const body = within(canvasElement.ownerDocument.body);
    await expect(
      body.getByText("No workspace toolkits are available to connect."),
    ).toBeVisible();
    await expect(
      body.getByRole("link", { name: /Add Workspace Toolkit/ }),
    ).toHaveAttribute("href", "/w/acme/toolkits/new");
  },
} satisfies Story;

export const ConnectionDetails = {
  args: { editor: { type: "DETAIL", toolkitConfigId: "toolkit-1" } },
} satisfies Story;

export const MobileCatalog = {
  ...NewToolkitCatalog,
  parameters: { testViewport: { width: 390, height: 844 } },
} satisfies Story;

export const RetryReadAfterCommittedWrite = {
  args: {
    state: {
      type: "ERROR",
      message: "The connection was saved. Reload the list.",
    },
    onRetryRead: fn(),
    onAttach: fn(),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Retry loading" }),
    );
    await expect(args.onRetryRead).toHaveBeenCalledOnce();
    await expect(args.onAttach).not.toHaveBeenCalled();
    await expect(
      canvas.getByRole("button", { name: "Add Toolkit" }),
    ).toBeDisabled();
  },
} satisfies Story;

export const PendingSetup = {
  args: {
    editor: { type: "CREATE", toolkitType: "mcp" },
    setupPending: true,
    setupView: <Text>Saving the provider configuration…</Text>,
    onCloseEditor: fn(),
    onCatalogTabChange: fn(),
  },
  play: async ({ canvasElement, args }) => {
    const body = within(canvasElement.ownerDocument.body);
    await expect(body.getByRole("button", { name: "Back" })).toBeDisabled();
    await userEvent.keyboard("{Escape}");
    await expect(args.onCloseEditor).not.toHaveBeenCalled();
    await expect(args.onCatalogTabChange).not.toHaveBeenCalled();
    await expect(
      body.getByRole("dialog", { name: "Toolkit settings" }),
    ).toBeVisible();
  },
} satisfies Story;

export const SharedInstanceCatalog = {
  args: {
    editor: { type: "CATALOG", tab: "workspace" },
    state: {
      type: "READY",
      items: [],
      toolkitTypes: [{ value: "mcp", label: "MCP" }],
      availableShared: [
        { value: "shared-1", label: "Production", toolkitType: "mcp" },
      ],
    },
    onAttach: fn(),
  },
  play: async ({ canvasElement, args }) => {
    const body = within(canvasElement.ownerDocument.body);
    await userEvent.click(body.getByRole("button", { name: "Production MCP" }));
    await expect(args.onAttach).toHaveBeenCalledWith("shared-1");
  },
} satisfies Story;
