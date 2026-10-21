import { rem } from "@mantine/core";
import { NextIntlClientProvider } from "next-intl";
import { expect, fn, userEvent, within } from "storybook/test";
import koreanMessages from "@/i18n/ko-KR-messages";
import { RuntimeEnvironmentPreview } from "@/shared/runtime-environment/AgentRuntimeEnvironmentVariables.story-fixtures";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { AgentRuntimeSettings } from "./AgentRuntimeSettings";
import type {
  AgentResponse,
  AgentRuntimeResponse,
  WorkspaceRuntimeProfileResponse,
} from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const agent: AgentResponse = {
  deletion_status: null,
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
  runtime_add_available: true,
  runtime_remove_available: false,
  toolkit_management_available: true,
  terminal_enabled: true,
  browser_enabled: false,
  infrastructure_terminal_enabled: true,
  workspace_terminal_enabled: true,
  effective_terminal_enabled: true,
  terminal_denied_scope: null,
  memory_enabled: true,
  tool_search_enabled: false,
  max_turns: null,
  auto_archive_ttl_days: 30,
  routine_check_interval_minutes: 30,
  routine_min_action_delay_minutes: 30,
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
  infrastructure_network: {
    mode: "direct",
    allowed_cidrs: ["0.0.0.0/0", "::/0"],
    denied_cidrs: [],
    domain_mode: null,
    allowed_domains: [],
    denied_domains: [],
  },
  effective_network: {
    mode: "direct",
    allowed_cidrs: ["0.0.0.0/0", "::/0"],
    denied_cidrs: [],
    domain_mode: null,
    allowed_domains: [],
    denied_domains: [],
  },
  terminal_enabled: true,
  infrastructure_terminal_enabled: true,
  effective_terminal_enabled: true,
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
  lifecycle: null,
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
  lifecycle: {
    target: "stopped",
    convergence: "stable",
    provider: { connection: "connected", resource: "stopped" },
    runner: { state: "disconnected" },
    availability: "stopped",
    reason_code: null,
    desired_generation: 2,
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
  tags: ["ci-contract"],
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
    metricsState: { type: "LOADING" },
    selectedProfileId: profile.id,
    actionError: null,
    actionNotice: null,
    addConfirmOpen: false,
    removeConfirmOpen: false,
    restartConfirmOpen: false,
    resetConfirmOpen: false,
    removalAcknowledged: false,
    isAdding: false,
    isUpdatingProfile: false,
    isUpdatingBrowser: false,
    onBrowserEnabledChange: noop,
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
    onOpenRestartConfirm: noop,
    onCloseRestartConfirm: noop,
    onOpenResetConfirm: noop,
    onCloseResetConfirm: noop,
    onStart: noop,
    onStop: noop,
    onConfirmRestart: noop,
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
      toolkit_management_available: true,
      terminal_enabled: true,
    },
    state: { type: "READY", runtime: managed, profiles: [profile] },
  },
} satisfies Story;

export const BrowserOptIn = {
  args: {
    ...Managed.args,
    onBrowserEnabledChange: fn(),
  },
  play: async ({ canvasElement, args }) => {
    const toggle = within(canvasElement).getByRole("switch", {
      name: /^Session browser\b/,
    });
    await expect(toggle).not.toBeChecked();
    await userEvent.click(toggle);
    await expect(args.onBrowserEnabledChange).toHaveBeenCalledWith(true);
  },
} satisfies Story;

export const BrowserEnabled = {
  args: {
    ...Managed.args,
    agent: { ...Managed.args.agent, browser_enabled: true },
  },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("switch", { name: /^Session browser\b/ }),
    ).toBeChecked();
  },
} satisfies Story;

export const BrowserUpdating = {
  args: { ...Managed.args, isUpdatingBrowser: true },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("switch", { name: /^Session browser\b/ }),
    ).toBeDisabled();
  },
} satisfies Story;

export const RemovalConfirmation = {
  args: {
    ...Managed.args,
    removeConfirmOpen: true,
    onRemovalAcknowledgedChange: fn(),
    onConfirmRemove: fn(),
  },
  play: async ({ canvasElement, args }) => {
    const dialog = within(canvasElement.ownerDocument.body).getByRole(
      "dialog",
      {
        name: "Permanently remove Runtime?",
      },
    );
    const modal = within(dialog);
    await expect(modal.getByText("This action is irreversible")).toBeVisible();
    for (const text of ["Active root sessions", "Deleted", "Retained"]) {
      await expect(modal.getByText(text)).toBeVisible();
    }
    await expect(
      modal.getByRole("button", { name: "Permanently remove Runtime" }),
    ).toBeDisabled();
    await userEvent.click(
      modal.getByRole("checkbox", {
        name: "I understand that Runtime removal is permanent and may interrupt active work.",
      }),
    );
    await expect(args.onRemovalAcknowledgedChange).toHaveBeenCalledWith(true);
    await expect(args.onConfirmRemove).not.toHaveBeenCalled();
  },
} satisfies Story;

export const RemovalAcknowledged = {
  args: {
    ...RemovalConfirmation.args,
    removalAcknowledged: true,
    onConfirmRemove: fn(),
  },
  play: async ({ canvasElement, args }) => {
    const dialog = within(canvasElement.ownerDocument.body).getByRole(
      "dialog",
      {
        name: "Permanently remove Runtime?",
      },
    );
    const confirm = within(dialog).getByRole("button", {
      name: "Permanently remove Runtime",
    });
    await expect(confirm).toBeEnabled();
    await userEvent.click(confirm);
    await expect(args.onConfirmRemove).toHaveBeenCalledOnce();
  },
} satisfies Story;

export const RestartConfirmation = {
  args: {
    ...Managed.args,
    restartConfirmOpen: true,
    onConfirmRestart: fn(),
  },
  play: async ({ canvasElement, args }) => {
    const dialog = within(canvasElement.ownerDocument.body).getByRole(
      "dialog",
      {
        name: "Restart Runtime?",
      },
    );
    const modal = within(dialog);
    await expect(
      modal.getByText(
        "The Runtime will be temporarily unavailable while it restarts.",
      ),
    ).toBeVisible();
    await expect(
      modal.getByText(
        "Agent Workspace files and preserved Runtime storage are retained.",
      ),
    ).toBeVisible();
    await userEvent.click(
      modal.getByRole("button", { name: "Restart Runtime" }),
    );
    await expect(args.onConfirmRestart).toHaveBeenCalledOnce();
  },
} satisfies Story;

export const ResetConfirmation = {
  args: {
    ...Managed.args,
    resetConfirmOpen: true,
    onConfirmReset: fn(),
  },
  play: async ({ canvasElement, args }) => {
    const dialog = within(canvasElement.ownerDocument.body).getByRole(
      "dialog",
      {
        name: "Reset Runtime state?",
      },
    );
    const modal = within(dialog);
    await expect(
      modal.getByText("Agent Workspace data will be deleted"),
    ).toBeVisible();
    await expect(
      modal.getByText(
        "Reset discards current Runtime workspace files and preserved Runtime state, then prepares an empty Runtime. This cannot be undone.",
      ),
    ).toBeVisible();
    await userEvent.click(modal.getByRole("button", { name: "Reset Runtime" }));
    await expect(args.onConfirmReset).toHaveBeenCalledOnce();
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
      toolkit_management_available: true,
      terminal_enabled: true,
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

export const EnvironmentVariablesPreview = {
  decorators: [
    (Story) => (
      <NextIntlClientProvider locale="ko-KR" messages={koreanMessages}>
        <Story />
      </NextIntlClientProvider>
    ),
  ],
  args: {
    ...Managed.args,
    environmentVariables: <RuntimeEnvironmentPreview />,
    metricsState: {
      type: "READY",
      metrics: {
        summary: "stopped",
        scope: null,
        cpu: {
          state: "stopped",
          measured_at: null,
          used: null,
          total: null,
          percentage: null,
        },
        memory: {
          state: "stopped",
          measured_at: null,
          used: null,
          total: null,
          percentage: null,
        },
        disk: {
          state: "stopped",
          measured_at: null,
          used: null,
          total: null,
          percentage: null,
        },
        samples: [],
      },
    },
  },
} satisfies Story;
