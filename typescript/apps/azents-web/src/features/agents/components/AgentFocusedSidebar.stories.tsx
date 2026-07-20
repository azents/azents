import { rem } from "@mantine/core";
import { userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { AgentFocusedSidebar } from "./AgentFocusedSidebar";
import type {
  AgentResponse,
  AgentSessionResponse,
} from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const agent: AgentResponse = {
  id: "agent_01",
  name: "Release Operator",
  description:
    "Coordinates release checklists, CI failures, and follow-up PRs.",
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
  system_prompt: "Help the workspace team with release operations.",
  runtime_provider_id: null,
  shell_enabled: true,
  memory_enabled: true,
  tool_search_enabled: false,
  max_turns: null,
  subagent_settings: { max_subagents: 3, max_depth: 1 },
  created_at: "2026-06-25T08:00:00Z",
  updated_at: "2026-06-25T08:00:00Z",
};

const sessions: AgentSessionResponse[] = [
  {
    id: "sess_primary",
    agent_id: "agent_01",
    current_model_target_label: null,
    current_reasoning_effort: null,
    title: null,
    title_source: null,
    status: "active",
    archived_at: null,
    purge_after: null,
    archive_retention_days_snapshot: null,
    primary_kind: "team_primary",
    run_state: "idle",
    created_at: "2026-06-24T08:00:00Z",
    updated_at: "2026-06-26T04:30:00Z",
  },
  {
    id: "sess_release",
    agent_id: "agent_01",
    current_model_target_label: null,
    current_reasoning_effort: null,
    title: "Release checklist follow-up",
    title_source: "manual",
    status: "active",
    archived_at: null,
    purge_after: null,
    archive_retention_days_snapshot: null,
    primary_kind: null,
    run_state: "running",
    created_at: "2026-06-25T09:00:00Z",
    updated_at: "2026-06-25T11:45:00Z",
  },
  {
    id: "sess_ci",
    agent_id: "agent_01",
    current_model_target_label: null,
    current_reasoning_effort: null,
    title: null,
    title_source: null,
    status: "active",
    archived_at: null,
    purge_after: null,
    archive_retention_days_snapshot: null,
    primary_kind: null,
    run_state: "idle",
    created_at: "2026-06-25T01:00:00Z",
    updated_at: "2026-06-25T03:10:00Z",
  },
];

const archivedSessions: AgentSessionResponse[] = [
  {
    id: "sess_archived",
    agent_id: "agent_01",
    current_model_target_label: null,
    current_reasoning_effort: null,
    title: "Investigate flaky deployment",
    title_source: "manual",
    status: "archived",
    primary_kind: null,
    run_state: "idle",
    archived_at: "2026-07-18T04:30:00Z",
    purge_after: "2026-08-17T04:30:00Z",
    archive_retention_days_snapshot: 30,
    created_at: "2026-07-12T08:00:00Z",
    updated_at: "2026-07-18T04:30:00Z",
  },
  {
    id: "sess_archived_unlimited",
    agent_id: "agent_01",
    current_model_target_label: null,
    current_reasoning_effort: null,
    title: null,
    title_source: null,
    status: "archived",
    primary_kind: null,
    run_state: "idle",
    archived_at: "2026-07-10T01:00:00Z",
    purge_after: null,
    archive_retention_days_snapshot: null,
    created_at: "2026-07-09T01:00:00Z",
    updated_at: "2026-07-10T01:00:00Z",
  },
];

const meta = {
  component: AgentFocusedSidebar,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(320)}>
        <div style={{ height: rem(720) }}>
          <Story />
        </div>
      </StorybookCanvas>
    ),
  ],
  args: {
    handle: "engineering",
    agent,
    currentUser: {
      name: "Alex Morgan",
      email: "alex@example.com",
    },
    adminAccessUrl: "https://admin.example.com",
    loggingOut: false,
    onLogout: () => {},
    sessions,
    archivedSessions,
    activeSessionId: "sess_primary",
    onCreateSession: () => {},
    onRenameSession: async () => {},
    onArchiveSession: () => {},
    onRestoreSession: () => {},
  },
} satisfies Meta<typeof AgentFocusedSidebar>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Loaded = {} satisfies Story;

export const UserMenuOpen = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /Alex Morgan/i }));
  },
} satisfies Story;

export const LoadingSessions = {
  args: {
    sessions: [],
    sessionsLoading: true,
  },
} satisfies Story;

export const SessionLoadError = {
  args: {
    sessions: [],
    sessionsError: "Failed to load sessions",
  },
} satisfies Story;

export const EmptySessions = {
  args: {
    sessions: [],
  },
} satisfies Story;

export const ArchivedSessionsExpanded = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /Archived/i }));
  },
} satisfies Story;
