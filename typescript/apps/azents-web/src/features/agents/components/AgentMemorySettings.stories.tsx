import { Box, rem } from "@mantine/core";
import { useState } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { useMemoryScrollPagination } from "../containers/useAgentMemorySettingsContainer";
import { AgentMemorySettings } from "./AgentMemorySettings";
import type {
  AgentResponse,
  HistoricalMemoryResponse,
  MemoryResponse,
} from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const agent: AgentResponse = {
  id: "agent_01",
  name: "Release Operator",
  description: "Coordinates release checklists and CI follow-up.",
  type: "private",
  enabled: true,
  avatar: null,
  selectable_model_options: [],
  main_model_label: "default",
  lightweight_model_label: "default",
  effective_context_window_tokens: 128000,
  effective_auto_compaction_threshold_tokens: 96000,
  model_parameters: null,
  system_prompt: "Help the workspace team with release operations.",
  runtime_profile_id: null,
  runtime_profile_selection_version: 1,
  runtime_profile_available: false,
  runtime_profile_availability_reason_code: "runtime_profile_unconfigured",
  runtime_capability: "none",
  runtime_capability_version: 1,
  runtime_profile_configuration_status: "not_applicable",
  runtime_add_available: false,
  runtime_remove_available: false,
  toolkit_management_available: true,
  terminal_enabled: true,
  infrastructure_terminal_enabled: true,
  workspace_terminal_enabled: true,
  effective_terminal_enabled: true,
  terminal_denied_scope: null,
  memory_enabled: true,
  tool_search_enabled: false,
  max_turns: null,
  auto_archive_ttl_days: 30,
  subagent_settings: { max_subagents: 3, max_depth: 1 },
  created_at: "2026-06-25T08:00:00Z",
  updated_at: "2026-06-25T08:00:00Z",
};

const noop = (): void => {};

const memories: MemoryResponse[] = [
  {
    id: "mem_01",
    agent_id: agent.id,
    user_id: null,
    scope: "agent",
    type: "project",
    name: "release-checklist",
    description: "Release checklist conventions for this workspace.",
    content:
      "Always verify CI, migrations, and rollback notes before announcing a release.",
    created_at: "2026-06-25T08:00:00Z",
    updated_at: "2026-06-25T08:00:00Z",
  },
  {
    id: "mem_02",
    agent_id: agent.id,
    user_id: null,
    scope: "agent",
    type: "feedback",
    name: "pr-language",
    description: "PR titles and bodies must be written in English.",
    content:
      "Use concise English for PR titles, descriptions, and review comments.",
    created_at: "2026-06-25T08:00:00Z",
    updated_at: "2026-06-25T08:00:00Z",
  },
];

const historicalMemories: HistoricalMemoryResponse[] = [
  {
    source_session_id: "session_01",
    scope: "team",
    source_title: "October release readiness",
    source_activity_through: "2026-10-01T08:30:00Z",
    prepared_at: "2026-10-01T15:00:00Z",
    summary:
      "The team completed migration verification and kept the deployment blocked until the required CI matrix passed. The next step is to confirm the rollback note before publishing the release.",
    source_path: "/w/engineering/agents/agent_01/sessions/session_01",
  },
  {
    source_session_id: "session_02",
    scope: "team",
    source_title: "Dependency security follow-up",
    source_activity_through: "2026-09-30T06:00:00Z",
    prepared_at: "2026-09-30T13:00:00Z",
    summary:
      "A transitive dependency remained blocked by its parent constraint. The agreed follow-up was to update the parent dependency instead of adding an override.",
    source_path: "/w/engineering/agents/agent_01/sessions/session_02",
  },
];

const meta = {
  component: AgentMemorySettings,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(980)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    handle: "engineering",
    agent,
    memoryEnabled: true,
    kind: "saved",
    savedScope: "agent",
    historicalScope: "team",
    savedQuery: "",
    historicalQuery: "",
    savedListState: { type: "LOADED", memories },
    historicalListState: {
      type: "LOADED",
      memories: historicalMemories,
      hasMore: false,
    },
    draftState: null,
    actionError: null,
    saving: false,
    deletingId: null,
    togglingMemory: false,
    historicalView: "overview",
    consolidatedState: {
      type: "LOADED",
      markdown:
        "## Release context\n\nCI must pass before release. Verify the rollback note.",
      publishedAt: "2026-10-01T15:00:00Z",
    },
    paginationState: { type: "END" },
    scrollRootRef: noop,
    scrollEndRef: noop,
    onHistoricalViewChange: noop,
    onRetryNextPage: noop,
    onKindChange: noop,
    onSavedScopeChange: noop,
    onHistoricalScopeChange: noop,
    onSavedQueryChange: noop,
    onHistoricalQueryChange: noop,
    onMemoryEnabledChange: noop,
    onStartCreate: noop,
    onStartEdit: noop,
    onCancelDraft: noop,
    onDraftChange: noop,
    onSaveDraft: noop,
    onDeleteMemory: noop,
  },
} satisfies Meta<typeof AgentMemorySettings>;

export default meta;

type Story = StoryObj<typeof meta>;

export const SavedLoaded = {} satisfies Story;

export const SavedLoading = {
  args: { savedListState: { type: "LOADING" } },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).queryByText("release-checklist"),
    ).not.toBeInTheDocument();
  },
} satisfies Story;

export const SavedError = {
  args: {
    savedListState: {
      type: "ERROR",
      message: "Saved Memory is temporarily unavailable.",
    },
  },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByText(
        "Saved Memory is temporarily unavailable.",
      ),
    ).toBeVisible();
  },
} satisfies Story;

export const SavedCreating = {
  args: {
    draftState: {
      type: "create",
      draft: {
        type: "project",
        name: "new-memory",
        description: "A new workspace convention.",
        content: "Verify all required checks before release.",
      },
    },
    onSaveDraft: fn(),
  },
  play: async ({ canvasElement, args }) => {
    const body = within(canvasElement.ownerDocument.body);
    await expect(
      body.getByRole("dialog", { name: "Add memory" }),
    ).toBeVisible();
    await userEvent.click(body.getByRole("button", { name: "Save" }));
    await expect(args.onSaveDraft).toHaveBeenCalledTimes(1);
  },
} satisfies Story;

export const SavedSaving = {
  args: { ...SavedCreating.args, saving: true },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement.ownerDocument.body).getByRole("button", {
        name: "Save",
      }),
    ).toHaveAttribute("data-loading", "true");
  },
} satisfies Story;

export const SavedDeleting = {
  args: { deletingId: "mem_01" },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getAllByRole("button", { name: "Delete" })[0],
    ).toHaveAttribute("data-loading", "true");
  },
} satisfies Story;

export const MemoryTogglePending = {
  args: { togglingMemory: true },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("switch", { name: "Enable Memory" }),
    ).toBeDisabled();
  },
} satisfies Story;

export const SavedEmpty = {
  args: {
    savedListState: { type: "LOADED", memories: [] },
  },
} satisfies Story;

export const SavedEditing = {
  args: {
    draftState: {
      type: "edit",
      memoryId: "mem_01",
      draft: {
        type: "project",
        name: "release-checklist",
        description: "Release checklist conventions for this workspace.",
        content:
          "Always verify CI, migrations, and rollback notes before announcing a release.",
      },
    },
  },
} satisfies Story;

export const HistoricalSessions = {
  args: {
    kind: "historical",
    historicalView: "sessions",
    memoryEnabled: false,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("link", {
        name: "Open conversation: October release readiness",
      }),
    ).toBeVisible();
    await expect(
      canvas.queryByRole("button", { name: "Add memory" }),
    ).not.toBeInTheDocument();
    await expect(
      canvas.queryByRole("button", { name: "Edit" }),
    ).not.toBeInTheDocument();
    await expect(
      canvas.queryByRole("button", { name: "Delete" }),
    ).not.toBeInTheDocument();
  },
} satisfies Story;

export const HistoricalEmpty = {
  args: {
    kind: "historical",
    historicalView: "sessions",
    historicalScope: "user",
    historicalListState: {
      type: "LOADED",
      memories: [],
      hasMore: false,
    },
  },
} satisfies Story;

export const HistoricalLoading = {
  args: {
    kind: "historical",
    historicalView: "sessions",
    historicalListState: { type: "LOADING" },
  },
} satisfies Story;

export const HistoricalError = {
  args: {
    kind: "historical",
    historicalView: "sessions",
    historicalListState: {
      type: "ERROR",
      message: "Historical Memory is temporarily unavailable.",
    },
  },
} satisfies Story;

export const HistoricalOverview = {
  args: { kind: "historical", onHistoricalViewChange: fn() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Integrated memory")).toBeVisible();
    await expect(
      canvas.getByText(
        "CI must pass before release. Verify the rollback note.",
      ),
    ).toBeVisible();
    await expect(
      canvas.queryByText("October release readiness"),
    ).not.toBeInTheDocument();
    await userEvent.click(
      canvas.getByRole("button", { name: "View session memories" }),
    );
    await expect(args.onHistoricalViewChange).toHaveBeenCalledWith("sessions");
  },
} satisfies Story;

export const HistoricalOverviewEmpty = {
  args: {
    kind: "historical",
    consolidatedState: { type: "LOADED", markdown: null, publishedAt: null },
  },
} satisfies Story;

export const HistoricalOverviewLoading = {
  args: { kind: "historical", consolidatedState: { type: "LOADING" } },
} satisfies Story;

export const HistoricalOverviewError = {
  args: {
    kind: "historical",
    consolidatedState: {
      type: "ERROR",
      message: "Integrated memory is unavailable.",
    },
  },
} satisfies Story;

export const HistoricalBack = {
  args: {
    kind: "historical",
    historicalView: "sessions",
    onHistoricalViewChange: fn(),
  },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(
      within(canvasElement).getByRole("button", {
        name: "Back to integrated memory",
      }),
    );
    await expect(args.onHistoricalViewChange).toHaveBeenCalledWith("overview");
  },
} satisfies Story;

export const NextPageError = {
  args: {
    paginationState: {
      type: "ERROR",
      message: "The next page could not be loaded.",
    },
    onRetryNextPage: fn(),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("release-checklist")).toBeVisible();
    await userEvent.click(canvas.getByRole("button", { name: "Retry" }));
    await expect(args.onRetryNextPage).toHaveBeenCalledTimes(1);
    await expect(
      canvas.queryByRole("button", { name: "Load more" }),
    ).not.toBeInTheDocument();
  },
} satisfies Story;

function InfiniteScrollHarness(
  props: React.ComponentProps<typeof AgentMemorySettings>,
): React.ReactElement {
  const [loaded, setLoaded] = useState(false);
  const [view, setView] = useState(props.historicalView);
  const refs = useMemoryScrollPagination({
    enabled: !loaded && (props.kind === "saved" || view === "sessions"),
    pageKey: `${props.kind}:${loaded}`,
    listKey: `${props.kind}:${view}`,
    onNextPage: () => setLoaded(true),
  });
  const savedSeed = memories.at(0);
  const savedNext = memories.at(1);
  const historicalSeed = historicalMemories.at(0);
  const historicalNext = historicalMemories.at(1);
  if (!savedSeed || !savedNext || !historicalSeed || !historicalNext) {
    throw new Error("Infinite scroll story fixtures are missing.");
  }
  const savedItems = Array.from({ length: 12 }, (_, i) => ({
    ...savedSeed,
    id: `long-saved-${i}`,
    name: `Saved entry ${i}`,
  }));
  const historicalItems = Array.from({ length: 12 }, (_, i) => ({
    ...historicalSeed,
    source_session_id: `long-session-${i}`,
    source_title: `Session entry ${i}`,
  }));
  return (
    <Box h={rem(420)} style={{ display: "flex", flexDirection: "column" }}>
      <AgentMemorySettings
        {...props}
        {...refs}
        historicalView={view}
        onHistoricalViewChange={setView}
        savedListState={{
          type: "LOADED",
          memories: loaded
            ? [...savedItems, { ...savedNext, name: "Next saved page" }]
            : savedItems,
        }}
        historicalListState={{
          type: "LOADED",
          memories: loaded
            ? [
                ...historicalItems,
                { ...historicalNext, source_title: "Next session page" },
              ]
            : historicalItems,
          hasMore: !loaded,
        }}
        paginationState={loaded ? { type: "END" } : { type: "IDLE" }}
      />
    </Box>
  );
}

export const SavedInfiniteScroll = {
  render: (args) => <InfiniteScrollHarness {...args} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByText("Next saved page")).not.toBeInTheDocument();
    const root = canvas.getByTestId("memory-scroll-root");
    root.scrollTop = root.scrollHeight;
    await waitFor(() =>
      expect(canvas.getByText("Next saved page")).toBeInTheDocument(),
    );
    root.scrollTop = root.scrollHeight;
    await expect(canvas.getAllByText("Next saved page")).toHaveLength(1);
    await expect(
      canvas.queryByRole("button", { name: "Load more" }),
    ).not.toBeInTheDocument();
  },
} satisfies Story;

export const HistoricalInfiniteScroll = {
  args: { kind: "historical", historicalView: "sessions" },
  render: (args) => <InfiniteScrollHarness {...args} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.queryByText("Next session page"),
    ).not.toBeInTheDocument();
    const root = canvas.getByTestId("memory-scroll-root");
    root.scrollTop = root.scrollHeight;
    await waitFor(() =>
      expect(canvas.getByText("Next session page")).toBeInTheDocument(),
    );
    await expect(
      canvas.queryByRole("button", { name: "Load more" }),
    ).not.toBeInTheDocument();
  },
} satisfies Story;

export const MobileHeader = {
  decorators: [
    (Story) => (
      <Box w={rem(320)}>
        <Story />
      </Box>
    ),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const description = canvas.getByTestId("memory-description");
    const control = canvas.getByRole("switch", { name: "Enable Memory" });
    await expect(description).toBeVisible();
    await expect(
      description.getBoundingClientRect().top,
    ).toBeGreaterThanOrEqual(control.getBoundingClientRect().bottom);
    await expect(description.getBoundingClientRect().width).toBeGreaterThan(
      200,
    );
  },
} satisfies Story;
