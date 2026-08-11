import { rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { AgentForm } from "./AgentForm";
import type {
  ModelSelectionOption,
  ProviderIntegrationOption,
} from "../model-selection";
import type { AgentFormValues } from "../schemas";
import type {
  AgentModelSelection,
  AgentResponse,
  WorkspaceRuntimeProfileResponse,
} from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const mainSelection: AgentModelSelection = {
  llm_provider_integration_id: "integration-main",
  provider: "openai",
  model_identifier: "gpt-5.5",
  model_display_name: "GPT 5.5",
  model_developer: "openai",
  model_family: "gpt-5",
  normalized_capabilities: {
    reasoning: { supported: true, effort_levels: ["low", "medium", "high"] },
    built_in_tools: { supported: ["web_search"] },
    context_window: { max_input_tokens: 1_000_000, max_output_tokens: null },
    modalities: { input: ["text"], output: ["text"] },
    tool_calling: { supported: true },
    parameters: {},
    compatibility: {},
  },
  model_snapshot: {},
  source_metadata: null,
  last_refreshed_at: "2026-05-14T00:00:00Z",
};

const lightweightSelection: AgentModelSelection = {
  ...mainSelection,
  model_identifier: "gpt-5.5-mini",
  model_display_name: "GPT 5.5 mini",
  normalized_capabilities: {
    ...mainSelection.normalized_capabilities,
    reasoning: { supported: false, effort_levels: [] },
    built_in_tools: { supported: [] },
    context_window: { max_input_tokens: 128_000, max_output_tokens: null },
  },
};

const providerOptions: ProviderIntegrationOption[] = [
  {
    value: "integration-main",
    label: "OpenAI · openai",
    provider: "openai",
    integration: {
      id: "integration-main",
      provider: "openai",
      name: "OpenAI",
      config: null,
      enabled: true,
      created_at: "2026-05-14T00:00:00Z",
      updated_at: "2026-05-14T00:00:00Z",
    },
    disabled: false,
  },
];

const modelOptions: ModelSelectionOption[] = [
  {
    value: "integration-main:gpt-5.5",
    label: "OpenAI · GPT 5.5 (gpt-5.5)",
    integrationId: "integration-main",
    integrationName: "OpenAI",
    integrationEnabled: true,
    modelIdentifier: "gpt-5.5",
    model: mainSelection,
    disabled: false,
  },
  {
    value: "integration-main:gpt-5.5-mini",
    label: "OpenAI · GPT 5.5 mini (gpt-5.5-mini)",
    integrationId: "integration-main",
    integrationName: "OpenAI",
    integrationEnabled: true,
    modelIdentifier: "gpt-5.5-mini",
    model: lightweightSelection,
    disabled: false,
  },
];

const baseAgent: AgentResponse = {
  id: "agent-1",
  name: "Snapshot Agent",
  description: "Exercises model selection snapshot settings.",
  model_selection: mainSelection,
  lightweight_model_selection: lightweightSelection,
  selectable_model_options: [
    {
      label: "default",
      model_selection: mainSelection,
      settings: {
        context_window_tokens: null,
        max_output_tokens: null,
        builtin_tools: [{ name: "web_search" }],
        subagent_enabled: true,
        subagent_guidance: "Use for complex synthesis tasks.",
      },
    },
    {
      label: "lightweight",
      model_selection: lightweightSelection,
      settings: {
        context_window_tokens: null,
        max_output_tokens: null,
        builtin_tools: [],
        subagent_enabled: false,
        subagent_guidance: null,
      },
    },
  ],
  main_model_label: "default",
  lightweight_model_label: "lightweight",
  effective_context_window_tokens: 1_000_000,
  effective_auto_compaction_threshold_tokens: 900_000,
  model_parameters: {
    reasoning_effort: "medium",
  },
  system_prompt: "Help the workspace team with engineering tasks.",
  enabled: true,
  type: "public",
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
  memory_enabled: true,
  tool_search_enabled: false,
  max_turns: null,
  auto_archive_ttl_days: 30,
  subagent_settings: { max_subagents: 3, max_depth: 1 },
  avatar: null,
  created_at: "2026-05-14T00:00:00Z",
  updated_at: "2026-05-14T00:00:00Z",
};

const runtimeProfile: WorkspaceRuntimeProfileResponse = {
  id: "workspace-runtime-profile-standard",
  provider_id: "runtime-provider-docker",
  infrastructure_profile_id: "infrastructure-profile-standard",
  display_name: "Standard runtime",
  description: "Balanced runtime configuration for general agent work.",
  lifecycle: "active",
  policy: { schema_version: 1, network_restriction: null },
  version: 3,
  digest: "sha256:runtime-profile-digest",
  available: true,
  availability_reason_code: null,
  capability_revision_id: "capability-revision-7",
  infrastructure_profile_version: 2,
  compatible: true,
  missing_capabilities: [],
  incompatible_constraints: [],
  created_at: "2026-07-31T06:00:00Z",
  updated_at: "2026-07-31T06:00:00Z",
};

function noopSubmit(values: AgentFormValues): void {
  void values;
}

const meta = {
  component: AgentForm,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(760)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    handle: "acme",
    formState: { type: "EDIT", agent: baseAgent },
    mutationState: { type: "IDLE", error: null },
    adminListState: { type: "READY", admins: [] },
    catalogStates: new Map(),
    modelsLoading: false,
    members: [],
    providerOptions,
    modelOptions,
    workspaceModelSettings: null,
    runtimeProfiles: [],
    runtimeProfilesLoading: false,
    onSyncCatalog: () => Promise.resolve(),
    onSubmit: noopSubmit,
    onAddAdmin: () => {},
    onRemoveAdmin: () => {},
    mode: "embedded",
  },
} satisfies Meta<typeof AgentForm>;

export default meta;

type Story = StoryObj<typeof meta>;

export const DefaultPreselected = {} satisfies Story;

export const CreateUsesWorkspaceDefault = {
  args: {
    formState: { type: "CREATE" },
    runtimeProfiles: [runtimeProfile],
  },
} satisfies Story;

export const UnavailableRuntimeProfile = {
  args: {
    formState: {
      type: "EDIT",
      agent: {
        ...baseAgent,
        runtime_profile_id: runtimeProfile.id,
        runtime_profile_available: false,
        runtime_profile_availability_reason_code: "provider_unavailable",
      },
    },
    runtimeProfiles: [
      {
        ...runtimeProfile,
        available: false,
        availability_reason_code: "provider_unavailable",
        capability_revision_id: null,
        compatible: false,
      },
    ],
  },
} satisfies Story;

export const NoModelsAvailable = {
  args: {
    formState: { type: "CREATE" },
    providerOptions: [],
    modelOptions: [],
  },
} satisfies Story;

export const UnsupportedCapabilities = {
  args: {
    formState: {
      type: "EDIT",
      agent: {
        ...baseAgent,
        model_selection: lightweightSelection,
        lightweight_model_selection: null,
        effective_context_window_tokens: 128_000,
        effective_auto_compaction_threshold_tokens: 115_200,
        model_parameters: null,
      },
    },
  },
} satisfies Story;
