import { Box, rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { AgentDraftChat } from "./AgentDraftChat";
import type { AgentDraftChatContainerOutput } from "../containers/useAgentDraftChatContainer";
import type { ComposerSubscriptionUsagePresentationProps } from "@/features/chat/components/ComposerSubscriptionUsage";
import type { AgentModelSelection, AgentResponse } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const noop = (): void => {};
const sendMessage = (): Promise<boolean> => Promise.resolve(true);
const uploadAll = (): Promise<[]> => Promise.resolve([]);

const subscriptionModel: AgentModelSelection = {
  llm_provider_integration_id: "integration-openrouter",
  provider: "openrouter",
  model_identifier: "openai/gpt-5.1",
  model_display_name: "GPT 5.1",
  model_developer: "openai",
  model_family: "gpt-5",
  normalized_capabilities: {
    reasoning: { supported: true, effort_levels: ["low", "medium", "high"] },
    built_in_tools: { supported: ["web_search"] },
    context_window: { max_input_tokens: 128_000, max_output_tokens: null },
    modalities: { input: ["text"], output: ["text"] },
    tool_calling: { supported: true },
    parameters: {},
    compatibility: {},
  },
  model_snapshot: {},
  source_metadata: null,
  last_refreshed_at: "2026-08-20T10:00:00Z",
};

const agent: AgentResponse = {
  id: "agent_release",
  name: "Release Operator",
  description: "Coordinates release checklists and CI follow-up.",
  type: "private",
  enabled: true,
  avatar: null,
  model_selection: subscriptionModel,
  lightweight_model_selection: null,
  selectable_model_options: [
    {
      label: "default",
      model_selection: subscriptionModel,
      settings: {
        context_window_tokens: null,
        max_output_tokens: null,
        builtin_tools: [{ name: "web_search" }],
        subagent_enabled: true,
        subagent_guidance: "Use for release coordination.",
      },
    },
  ],
  main_model_label: "default",
  lightweight_model_label: "default",
  effective_context_window_tokens: 128_000,
  effective_auto_compaction_threshold_tokens: 115_000,
  model_parameters: { reasoning_effort: "medium" },
  system_prompt: "Coordinate release work for the workspace.",
  runtime_profile_id: null,
  runtime_profile_selection_version: 1,
  runtime_profile_available: false,
  runtime_profile_availability_reason_code: "runtime_profile_unconfigured",
  runtime_capability: "none",
  runtime_capability_version: 1,
  runtime_profile_configuration_status: "not_applicable",
  runtime_add_available: false,
  runtime_remove_available: false,
  shell_enabled: true,
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
  created_at: "2026-08-20T09:00:00Z",
  updated_at: "2026-08-20T09:00:00Z",
};

const subscriptionUsage: ComposerSubscriptionUsagePresentationProps = {
  resetKey: "integration-openrouter",
  onRefresh: async (): Promise<void> => {},
  state: {
    type: "AVAILABLE",
    refreshing: false,
    snapshot: {
      type: "available",
      integration_id: "integration-openrouter",
      provider: "openrouter",
      fetched_at: "2026-08-20T10:00:00Z",
      plan_label: "Pro",
      limits: [
        {
          id: "primary",
          label: "Monthly limit",
          used_percent: 42,
          window_minutes: 43_200,
          resets_at: "2026-09-01T00:00:00Z",
          primary: true,
        },
      ],
      financial_details: {
        type: "openrouter",
        credit_limit: 100,
        credit_remaining: 58,
        usage: 42,
        usage_daily: 2,
        usage_weekly: 12,
        usage_monthly: 42,
        limit_reset: null,
        include_byok_in_limit: false,
      },
    },
  },
};

const args: AgentDraftChatContainerOutput = {
  handle: "engineering",
  agent,
  sessionScope: "team",
  isWritePending: false,
  isInputUploading: false,
  isMobile: false,
  canSendMessage: true,
  pendingFiles: [],
  defaultInferenceProfile: {
    model_target_label: "default",
    reasoning_effort: "medium",
  },
  subscriptionUsage,
  selectedProjectPaths: [],
  workspaceItems: [],
  activeWorktreeItemId: null,
  gitRefPreviewState: { type: "IDLE" },
  projectPresetState: { type: "READY", presets: [] },
  projectPickerState: { type: "CLOSED" },
  isProjectPickerOpen: false,
  onAddPresetProject: noop,
  onAddWorktreeProject: noop,
  onSetWorkspaceItemKind: noop,
  onActivateWorktreeItem: noop,
  onSetWorktreeStartingRef: noop,
  onRemoveWorkspaceItem: noop,
  onOpenProjectPicker: noop,
  onCloseProjectPicker: noop,
  onOpenProjectPickerDirectory: noop,
  onSelectProjectPickerDirectory: noop,
  onRefreshProjectPicker: noop,
  onStartRuntimeForProjectPicker: noop,
  onRestartRuntimeForProjectPicker: noop,
  onSessionScopeChange: noop,
  onSendInput: sendMessage,
  onSendMessage: sendMessage,
  addFiles: noop,
  removeFile: noop,
  clearFiles: noop,
  resetDoneFiles: noop,
  uploadAll,
  onAfterSend: noop,
  onStopRequest: noop,
};

const meta = {
  component: AgentDraftChat,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(1120)}>
        <Box h="100dvh">
          <Story />
        </Box>
      </StorybookCanvas>
    ),
  ],
  args,
} satisfies Meta<typeof AgentDraftChat>;

export default meta;

type Story = StoryObj<typeof meta>;

export const RuntimeFree = {} satisfies Story;

export const ManagedProjectSetup = {
  args: {
    agent: {
      ...agent,
      runtime_capability: "managed",
      runtime_capability_version: 2,
      runtime_profile_id: "runtime_profile_standard",
      runtime_profile_available: true,
      runtime_profile_availability_reason_code: null,
      runtime_profile_configuration_status: "configured",
      runtime_add_available: false,
      runtime_remove_available: true,
      terminal_enabled: true,
    },
    workspaceItems: [
      {
        id: "project-azents",
        type: "existing_project",
        path: "/workspace/agent/azents",
      },
      {
        id: "worktree-web",
        type: "git_worktree",
        sourceProjectPath: "/workspace/agent/azents/typescript",
        startingRef: "refs/heads/main",
      },
    ],
    activeWorktreeItemId: "worktree-web",
    gitRefPreviewState: {
      type: "READY",
      refs: [
        {
          name: "main",
          ref: "refs/heads/main",
          type: "branch",
          target: "abcdef",
          default: true,
        },
      ],
    },
  },
} satisfies Story;

export const ProjectPresetError = {
  args: {
    ...ManagedProjectSetup.args,
    projectPresetState: {
      type: "ERROR",
      message: "Project presets could not be loaded.",
    },
  },
} satisfies Story;
