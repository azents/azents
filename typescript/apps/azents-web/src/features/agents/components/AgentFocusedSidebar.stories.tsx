import { rem } from "@mantine/core";
import { expect, userEvent, within } from "storybook/test";
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
  runtime_profile_id: null,
  runtime_profile_selection_version: 1,
  runtime_profile_available: false,
  runtime_profile_availability_reason_code: "runtime_profile_unconfigured",
  runtime_capability: "none",
  runtime_capability_version: 1,
  runtime_profile_configuration_status: "not_applicable",
  runtime_add_available: false,
  runtime_remove_available: false,
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
    product_mode: "team",
    run_state: "idle",
    pinned: false,
    unread_terminal_run_id: null,
    auto_archive_after: null,
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
    product_mode: "team",
    run_state: "running",
    pinned: false,
    unread_terminal_run_id: null,
    auto_archive_after: "2026-08-10T11:45:00Z",
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
    product_mode: "team",
    run_state: "idle",
    pinned: false,
    unread_terminal_run_id: null,
    auto_archive_after: "2026-08-02T03:10:00Z",
    created_at: "2026-06-25T01:00:00Z",
    updated_at: "2026-06-25T03:10:00Z",
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
    pinnedSessions: [],
    recentSessions: sessions,
    activeSessionId: "sess_primary",
    onCreateSession: () => {},
    onRenameSession: async () => {},
    onArchiveSession: () => {},
    onSetSessionPinned: () => {},
    nowMs: Date.parse("2026-07-29T12:00:00Z"),
  },
} satisfies Meta<typeof AgentFocusedSidebar>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Read = {
  args: {
    recentSessions: sessions.filter((session) => session.id === "sess_primary"),
  },
} satisfies Story;

export const Unread = {
  args: {
    recentSessions: sessions
      .filter((session) => session.id === "sess_primary")
      .map((session) => ({
        ...session,
        unread_terminal_run_id: "3123456789abcdef0123456789abcdef",
      })),
  },
} satisfies Story;

export const Running = {
  args: {
    recentSessions: sessions.filter((session) => session.id === "sess_release"),
  },
} satisfies Story;

export const Pinned = {
  args: {
    pinnedSessions: sessions
      .filter((session) => session.id === "sess_ci")
      .map((session) => ({
        ...session,
        pinned: true,
        auto_archive_after: null,
      })),
  },
} satisfies Story;

export const AutoArchiveDueSoon = {
  args: {
    recentSessions: sessions.filter((session) => session.id === "sess_ci"),
  },
} satisfies Story;

export const RunningWithUnreadBoundary = {
  args: {
    recentSessions: sessions
      .filter((session) => session.id === "sess_release")
      .map((session) => ({
        ...session,
        unread_terminal_run_id: "3123456789abcdef0123456789abcdef",
      })),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByLabelText(/running/i)).toBeVisible();
    await expect(
      canvas.queryByRole("img", { name: /unread/i }),
    ).not.toBeInTheDocument();
  },
} satisfies Story;

export const Loaded = {} satisfies Story;

export const AgentProfileLinksToDirectory = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("link", { name: /Release Operator/i }),
    ).toHaveAttribute("href", "/w/engineering/agents/agent_01/sessions");
  },
} satisfies Story;

export const UserMenuOpen = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /Alex Morgan/i }));
  },
} satisfies Story;

export const LoadingSessions = {
  args: {
    recentSessions: [],
    sessionsLoading: true,
  },
} satisfies Story;

export const SessionLoadError = {
  args: {
    recentSessions: [],
    sessionsError: "Failed to load sessions",
  },
} satisfies Story;

export const EmptySessions = {
  args: {
    recentSessions: [],
  },
} satisfies Story;

const userSessions: AgentSessionResponse[] = [
  {
    id: "sess_private_notes",
    agent_id: "agent_01",
    current_model_target_label: null,
    current_reasoning_effort: null,
    title: "Private release notes",
    title_source: "manual",
    status: "active",
    archived_at: null,
    purge_after: null,
    archive_retention_days_snapshot: null,
    primary_kind: null,
    product_mode: "user",
    run_state: "idle",
    pinned: false,
    unread_terminal_run_id: null,
    auto_archive_after: "2026-08-12T09:00:00Z",
    created_at: "2026-06-26T08:00:00Z",
    updated_at: "2026-06-26T09:00:00Z",
  },
  {
    id: "sess_private_draft_followup",
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
    product_mode: "user",
    run_state: "running",
    pinned: true,
    unread_terminal_run_id: null,
    auto_archive_after: null,
    created_at: "2026-06-27T08:00:00Z",
    updated_at: "2026-06-27T10:15:00Z",
  },
];

export const MySessionsTab = {
  args: {
    sessionListScope: "user",
    sessions: userSessions,
    activeSessionId: "sess_private_notes",
    onSessionListScopeChange: () => {},
  },
} satisfies Story;

export const MySessionsEmpty = {
  args: {
    sessionListScope: "user",
    sessions: [],
    onSessionListScopeChange: () => {},
  },
} satisfies Story;

export const TeamSessionsTab = {
  args: {
    sessionListScope: "team",
    pinnedSessions: sessions.filter(
      (session) => session.primary_kind === "team_primary",
    ),
    recentSessions: sessions.filter((session) => session.primary_kind === null),
    onSessionListScopeChange: () => {},
  },
} satisfies Story;
