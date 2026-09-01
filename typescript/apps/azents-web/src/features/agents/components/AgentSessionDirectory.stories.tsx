import { rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { AgentSessionDirectory } from "./AgentSessionDirectory";
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

const activeSession: AgentSessionResponse = {
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
  run_state: "idle",
  pinned: true,
  unread_terminal_run_id: null,
  auto_archive_after: "2026-08-10T11:45:00Z",
  created_at: "2026-06-25T09:00:00Z",
  updated_at: "2026-06-25T11:45:00Z",
};

const archivedSession: AgentSessionResponse = {
  id: "sess_archived",
  agent_id: "agent_01",
  current_model_target_label: null,
  current_reasoning_effort: null,
  title: "Investigate flaky deployment",
  title_source: "manual",
  status: "archived",
  primary_kind: null,
  product_mode: "team",
  run_state: "idle",
  pinned: false,
  unread_terminal_run_id: null,
  auto_archive_after: null,
  archived_at: "2026-07-18T04:30:00Z",
  purge_after: "2026-08-17T04:30:00Z",
  archive_retention_days_snapshot: 30,
  created_at: "2026-07-12T08:00:00Z",
  updated_at: "2026-07-18T04:30:00Z",
};

const meta = {
  component: AgentSessionDirectory,
  decorators: [
    (Story) => (
      <StorybookCanvas>
        <div style={{ height: rem(760) }}>
          <Story />
        </div>
      </StorybookCanvas>
    ),
  ],
  args: {
    handle: "engineering",
    agent,
    status: "active",
    page: 1,
    pageSize: 25,
    sessions: [activeSession],
    totalCount: 1,
    currentArchiveRetentionDays: 30,
    loading: false,
    error: null,
    actionError: null,
    renamingSessionId: null,
    archivingSessionId: null,
    pinningSessionId: null,
    restoringSessionId: null,
    onStatusChange: () => {},
    onPageChange: () => {},
    onCreateSession: () => {},
    onRenameSession: async () => {},
    onArchiveSession: () => {},
    onSetSessionPinned: () => {},
    onRestoreSession: () => {},
  },
} satisfies Meta<typeof AgentSessionDirectory>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Active = {} satisfies Story;

export const Archived = {
  args: {
    status: "archived",
    sessions: [archivedSession],
  },
} satisfies Story;

export const Empty = {
  args: {
    sessions: [],
    totalCount: 0,
  },
} satisfies Story;

export const Loading = {
  args: {
    sessions: [],
    loading: true,
  },
} satisfies Story;

export const ErrorState = {
  args: {
    sessions: [],
    error: "Failed to load sessions",
  },
} satisfies Story;

export const Paginated = {
  args: {
    page: 2,
    sessions: [activeSession, { ...activeSession, id: "sess_follow_up" }],
    totalCount: 52,
  },
} satisfies Story;
