import { rem, Text } from "@mantine/core";
import { useState } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { githubUserAuthorizationFixture } from "@/shared/toolkits/components/github-user-story-fixtures";
import { GitHubUserAuthorization } from "@/shared/toolkits/components/GitHubUserAuthorization";
import { removedToolkitEditor } from "../agentToolkitManagementState";
import { ManagedAgentToolkitSectionView } from "./ManagedAgentToolkitSection";
import type { AgentToolkitEditorState } from "../types";
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
    onGithubUserPopupAccepted: () => {},
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
    onToggle: () => {},
    onRequestDelete: () => {},
    onCancelDelete: () => {},
    onConfirmDelete: () => {},
  },
} satisfies Meta<typeof ManagedAgentToolkitSectionView>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Ready = {} satisfies Story;

const sharedItem: AgentToolkitManagementItemResponse = {
  ...item,
  ownership_scope: "workspace_shared",
  agent_toolkit_id: "attachment-1",
  readiness: "ready",
  toolkit: { ...item.toolkit, name: "Shared MCP" },
};

function RemovalFixture({
  shared,
  details = false,
}: {
  shared: boolean;
  details?: boolean;
}): React.ReactElement {
  const target = shared ? sharedItem : item;
  const [items, setItems] = useState([target]);
  const [editor, setEditor] = useState<AgentToolkitEditorState>(
    details
      ? { type: "DETAIL", toolkitConfigId: target.toolkit.id }
      : { type: "CLOSED" },
  );
  const [deleteTarget, setDeleteTarget] =
    useState<AgentToolkitManagementItemResponse | null>(null);
  return (
    <ManagedAgentToolkitSectionView
      {...meta.args}
      state={{
        type: "READY",
        items,
        toolkitTypes: [],
        availableShared: [],
      }}
      editor={editor}
      deleteTarget={deleteTarget}
      onDetails={(toolkitConfigId) =>
        setEditor({ type: "DETAIL", toolkitConfigId })
      }
      onRequestDelete={setDeleteTarget}
      onCancelDelete={() => setDeleteTarget(null)}
      onCloseEditor={() => setEditor({ type: "CLOSED" })}
      onConfirmDelete={() => {
        setEditor((current) => removedToolkitEditor(current, editor));
        setDeleteTarget(null);
        setItems([]);
      }}
    />
  );
}

async function checkRemoval(
  canvasElement: HTMLElement,
  shared: boolean,
  details: boolean,
): Promise<void> {
  const page = within(canvasElement.ownerDocument.body);
  const name = shared ? "Shared MCP" : "Private MCP";
  const action = shared ? "Detach" : "Delete";
  const title = shared
    ? "Remove toolkit from this agent"
    : "Delete agent-only toolkit";
  const scope = details
    ? within(await page.findByRole("dialog", { name: "View details" }))
    : within(page.getByRole("article", { name }));
  await userEvent.click(scope.getByRole("button", { name: action }));
  let dialog = within(await page.findByRole("dialog", { name: title }));
  if (shared) {
    await waitFor(async () => {
      await expect(
        dialog.getByText(/shared toolkit and its credentials will remain/),
      ).toBeVisible();
    });
  }
  await userEvent.click(dialog.getByRole("button", { name: "Cancel" }));
  await waitFor(async () => {
    await expect(
      page.queryByRole("dialog", { name: title }),
    ).not.toBeInTheDocument();
  });
  await expect(page.getByRole("article", { name })).toBeInTheDocument();
  const retryScope = details
    ? within(await page.findByRole("dialog", { name: "View details" }))
    : within(page.getByRole("article", { name }));
  await userEvent.click(retryScope.getByRole("button", { name: action }));
  dialog = within(await page.findByRole("dialog", { name: title }));
  await userEvent.click(
    dialog.getByRole("button", {
      name: shared ? "Detach" : "Delete toolkit",
    }),
  );
  await waitFor(async () => {
    await expect(page.queryByRole("dialog")).not.toBeInTheDocument();
    await expect(page.queryByRole("article", { name })).not.toBeInTheDocument();
  });
  await expect(
    page.queryByText(/This toolkit is no longer available/),
  ).not.toBeInTheDocument();
}

export const DeleteFromList = {
  tags: ["ci-contract"],
  render: () => <RemovalFixture shared={false} />,
  play: async ({ canvasElement }) => {
    await checkRemoval(canvasElement, false, false);
  },
} satisfies Story;

export const DetachFromList = {
  tags: ["ci-contract"],
  render: () => <RemovalFixture shared />,
  play: async ({ canvasElement }) => {
    await checkRemoval(canvasElement, true, false);
  },
} satisfies Story;

export const RemovedDetailsClose = {
  tags: ["ci-contract"],
  render: () => <RemovalFixture shared details />,
  play: async ({ canvasElement }) => {
    await checkRemoval(canvasElement, true, true);
  },
} satisfies Story;

export const DeletedDetailsClose = {
  tags: ["ci-contract"],
  render: () => <RemovalFixture shared={false} details />,
  play: async ({ canvasElement }) => {
    await checkRemoval(canvasElement, false, true);
  },
} satisfies Story;

export const RemovalPending = {
  tags: ["ci-contract"],
  args: {
    deleteTarget: sharedItem,
    pending: true,
    deletePending: true,
    onCancelDelete: fn(),
    onConfirmDelete: fn(),
  },
  play: async ({ canvasElement, args }) => {
    const page = within(canvasElement.ownerDocument.body);
    const dialog = within(
      await page.findByRole("dialog", {
        name: "Remove toolkit from this agent",
      }),
    );
    await expect(dialog.getByRole("button", { name: "Cancel" })).toBeDisabled();
    await expect(dialog.getByRole("button", { name: "Detach" })).toBeDisabled();
    await expect(
      dialog.queryByRole("button", { name: "Close" }),
    ).not.toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await expect(args.onCancelDelete).not.toHaveBeenCalled();
    await expect(args.onConfirmDelete).not.toHaveBeenCalled();
  },
} satisfies Story;

const userItem: AgentToolkitManagementItemResponse = {
  ...item,
  toolkit: {
    ...item.toolkit,
    toolkit_type: "github",
    name: "GitHub user delegation",
    config: { github_auth_type: "github_app_user" },
  },
};
export const GitHubUserDirectAuthorize = {
  args: {
    state: {
      type: "READY",
      items: [userItem],
      toolkitTypes: [{ value: "github", label: "GitHub" }],
      availableShared: [],
    },
    onAuthorize: fn(),
  },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(
      within(canvasElement).getByRole("button", { name: "Authorize" }),
    );
    await expect(args.onAuthorize).toHaveBeenCalledWith(userItem);
  },
} satisfies Story;

export const GitHubUserDetails = {
  args: {
    ...GitHubUserDirectAuthorize.args,
    editor: { type: "DETAIL", toolkitConfigId: "toolkit-1" },
    githubUserView: (
      <GitHubUserAuthorization {...githubUserAuthorizationFixture} />
    ),
  },
} satisfies Story;

export const SharedGitHubUserRestricted = {
  args: {
    state: {
      type: "READY",
      items: [
        {
          ...userItem,
          ownership_scope: "workspace_shared",
          agent_toolkit_id: "attachment",
        },
      ],
      toolkitTypes: [{ value: "github", label: "GitHub" }],
      availableShared: [],
    },
    canAuthorizeShared: false,
    editor: { type: "DETAIL", toolkitConfigId: "toolkit-1" },
    githubUserView: <Text>Private GitHub connection controls</Text>,
  },
  play: async ({ canvasElement }) => {
    const page = within(canvasElement.ownerDocument.body);
    await expect(
      page.queryByText("Private GitHub connection controls"),
    ).not.toBeInTheDocument();
    await expect(
      page.queryByRole("button", { name: "Authorize" }),
    ).not.toBeInTheDocument();
    await expect(
      page.queryByRole("button", { name: "Disconnect account" }),
    ).not.toBeInTheDocument();
  },
} satisfies Story;

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

export const DeleteFailure = {
  tags: ["ci-contract"],
  args: {
    editor: { type: "DETAIL", toolkitConfigId: "toolkit-1" },
    deleteTarget: item,
    mutationState: {
      type: "ERROR",
      message: "The toolkit could not be deleted. Try again.",
    },
    onConfirmDelete: fn(),
    onCancelDelete: fn(),
  },
  play: async ({ canvasElement, args }) => {
    const body = within(canvasElement.ownerDocument.body);
    const dialog = within(
      body.getByRole("dialog", { name: "Delete agent-only toolkit" }),
    );
    await expect(
      dialog.getByText("The toolkit could not be deleted. Try again."),
    ).toBeVisible();
    const retry = dialog.getByRole("button", { name: "Delete toolkit" });
    await expect(retry).toBeEnabled();
    await userEvent.click(retry);
    await expect(args.onConfirmDelete).toHaveBeenCalledOnce();
    await userEvent.click(dialog.getByRole("button", { name: "Cancel" }));
    await expect(args.onCancelDelete).toHaveBeenCalledOnce();
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

export const GitHubCandidateCloseAllowed = {
  args: {
    editor: { type: "CREATE", toolkitType: "github" },
    setupPending: true,
    createPublicationPending: false,
    setupView: (
      <Text>GitHub authorization verified. Choose feature groups.</Text>
    ),
    onCloseEditor: fn(),
    onCatalogTabChange: fn(),
  },
  play: async ({ canvasElement, args }) => {
    const body = within(canvasElement.ownerDocument.body);
    const dialog = within(
      body.getByRole("dialog", { name: "Toolkit settings" }),
    );
    await expect(body.getByRole("button", { name: "Back" })).toBeEnabled();
    const close = dialog.getByRole("button", { name: "Close" });
    await expect(close).toHaveAttribute("aria-label", "Close");
    await userEvent.click(close);
    await expect(args.onCloseEditor).toHaveBeenCalledOnce();
  },
} satisfies Story;

export const GitHubPublicationCloseBlocked = {
  args: {
    editor: { type: "CREATE", toolkitType: "github" },
    setupPending: false,
    createPublicationPending: true,
    setupView: <Text>Saving the verified GitHub connection…</Text>,
    onCloseEditor: fn(),
  },
  play: async ({ canvasElement, args }) => {
    const body = within(canvasElement.ownerDocument.body);
    await expect(body.getByRole("button", { name: "Back" })).toBeDisabled();
    await expect(
      body.queryByRole("button", { name: "Close" }),
    ).not.toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await expect(args.onCloseEditor).not.toHaveBeenCalled();
  },
} satisfies Story;
