import { rem } from "@mantine/core";
import { expect, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
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
    loadingMoreHistorical: false,
    onKindChange: noop,
    onSavedScopeChange: noop,
    onHistoricalScopeChange: noop,
    onSavedQueryChange: noop,
    onHistoricalQueryChange: noop,
    onLoadMoreHistorical: noop,
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

export const HistoricalLoaded = {
  args: {
    kind: "historical",
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
    historicalListState: { type: "LOADING" },
  },
} satisfies Story;

export const HistoricalError = {
  args: {
    kind: "historical",
    historicalListState: {
      type: "ERROR",
      message: "Historical Memory is temporarily unavailable.",
    },
  },
} satisfies Story;
