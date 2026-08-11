import { rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { AgentRuntimeSettings } from "./AgentRuntimeSettings";
import type {
  AgentResponse,
  AgentRuntimeResponse,
  WorkspaceRuntimeProfileResponse,
} from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const agent: AgentResponse = {
  id: "agent_01",
  name: "Release Operator",
  description: "Coordinates release checklists and CI follow-up.",
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
  runtime_add_available: true,
  runtime_remove_available: false,
  shell_enabled: true,
  memory_enabled: true,
  tool_search_enabled: false,
  max_turns: null,
  auto_archive_ttl_days: 30,
  subagent_settings: { max_subagents: 3, max_depth: 1 },
  created_at: "2026-06-25T08:00:00Z",
  updated_at: "2026-06-25T08:00:00Z",
};

const profile: WorkspaceRuntimeProfileResponse = {
  id: "runtime_profile_01",
  provider_id: "provider_01",
  infrastructure_profile_id: "infrastructure_profile_01",
  display_name: "Standard isolated Runtime",
  description: "Workspace default Runtime for development tasks.",
  lifecycle: "active",
  policy: { schema_version: 1, network_restriction: null },
  version: 1,
  digest: "sha256:profile",
  available: true,
  availability_reason_code: null,
  capability_revision_id: "capability_revision_01",
  infrastructure_profile_version: 1,
  compatible: true,
  missing_capabilities: [],
  incompatible_constraints: [],
  created_at: "2026-06-25T08:00:00Z",
  updated_at: "2026-06-25T08:00:00Z",
};

const actions = {
  add: false,
  remove: false,
  start: false,
  stop: false,
  restart: false,
  reset: false,
  observe: false,
  use_runner: false,
};

const runtimeFree: AgentRuntimeResponse = {
  capability: "none",
  capability_version: 1,
  runtime_profile_id: null,
  runtime_profile_selection_version: 1,
  runtime_profile_status: "not_applicable",
  runtime_profile_available: false,
  runtime_profile_availability_reason_code: null,
  removal_impact: null,
  removal: null,
  runtime: null,
  state: null,
  configuration: null,
  actions: { ...actions, add: true },
};

const managed: AgentRuntimeResponse = {
  ...runtimeFree,
  capability: "managed",
  capability_version: 2,
  runtime_profile_id: profile.id,
  runtime_profile_selection_version: 2,
  runtime_profile_status: "configured",
  runtime_profile_available: true,
  removal_impact: {
    active_root_session_count: 2,
    active_subagent_count: 3,
    active_run_count: 1,
    queued_runtime_action_count: 2,
  },
  configuration: {
    status: "configured_not_created",
    desired: null,
    applied: null,
  },
  actions: { ...actions, remove: true, start: true },
};

const removing: AgentRuntimeResponse = {
  ...managed,
  capability: "removing",
  capability_version: 3,
  removal: {
    id: "removal_01",
    status: "running",
    stage: "cleaning_product_state",
    confirmed_at: "2026-08-10T09:00:00Z",
    cleanup_scanned_context_count: 14,
    cleanup_invalidated_context_count: 9,
    product_cleanup_completed_at: null,
    physical_deletion_required: true,
    physical_delete_requested_at: null,
    physical_delete_acknowledgement_kind: null,
    physical_delete_acknowledged_at: null,
    attempt_count: 1,
    next_attempt_at: null,
    last_error_kind: null,
    last_error_summary: null,
    started_at: "2026-08-10T09:00:01Z",
    completed_at: null,
    updated_at: "2026-08-10T09:00:05Z",
  },
  actions,
};

const noop = (): void => {};

const meta = {
  component: AgentRuntimeSettings,
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
    state: { type: "READY", runtime: runtimeFree, profiles: [profile] },
    selectedProfileId: profile.id,
    actionError: null,
    actionNotice: null,
    addConfirmOpen: false,
    removeConfirmOpen: false,
    resetConfirmOpen: false,
    removalAcknowledged: false,
    isAdding: false,
    isUpdatingProfile: false,
    isRemoving: false,
    lifecycleAction: null,
    onSelectProfile: noop,
    onOpenAddConfirm: noop,
    onCloseAddConfirm: noop,
    onConfirmAdd: noop,
    onUpdateProfile: noop,
    onOpenRemoveConfirm: noop,
    onCloseRemoveConfirm: noop,
    onRemovalAcknowledgedChange: noop,
    onConfirmRemove: noop,
    onOpenResetConfirm: noop,
    onCloseResetConfirm: noop,
    onStart: noop,
    onStop: noop,
    onRestart: noop,
    onConfirmReset: noop,
    onRefresh: noop,
  },
} satisfies Meta<typeof AgentRuntimeSettings>;

export default meta;

type Story = StoryObj<typeof meta>;

export const RuntimeFree = {} satisfies Story;

export const Managed = {
  args: {
    agent: {
      ...agent,
      runtime_profile_id: profile.id,
      runtime_capability: "managed",
      runtime_add_available: false,
      runtime_remove_available: true,
    },
    state: { type: "READY", runtime: managed, profiles: [profile] },
  },
} satisfies Story;

export const RemovalConfirmation = {
  args: {
    ...Managed.args,
    removeConfirmOpen: true,
  },
} satisfies Story;

export const Removing = {
  args: {
    agent: {
      ...agent,
      runtime_profile_id: profile.id,
      runtime_capability: "removing",
      runtime_add_available: false,
      runtime_remove_available: false,
    },
    state: { type: "READY", runtime: removing, profiles: [profile] },
    selectedProfileId: null,
  },
} satisfies Story;

export const Loading = {
  args: {
    state: { type: "LOADING" },
  },
} satisfies Story;
