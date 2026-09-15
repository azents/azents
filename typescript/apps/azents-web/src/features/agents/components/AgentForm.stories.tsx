import { rem } from "@mantine/core";
import { useForm } from "@mantine/form";
import { expect, userEvent, within } from "storybook/test";
import { reasoningEffortLevels } from "@/shared/lib/reasoning-effort";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { useAgentFormTranslations } from "../containers/useAgentFormTranslations";
import {
  findSelectableModelOptionByLabel,
  selectableModelOptionFormValuesFromStoredOptions,
} from "../model-selection";
import { AgentForm } from "./AgentForm";
import type {
  ImageGenerationCatalogState,
  ModelSelectionOption,
  ProviderIntegrationOption,
} from "../model-selection";
import type { AgentFormValues } from "../schemas";
import type { AgentFormState } from "../types";
import type { AgentFormProps } from "./AgentForm";
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
  selectable_model_options: [
    {
      label: "default",
      candidates: [
        {
          model_selection: mainSelection,
          settings: {
            context_window_tokens: null,
            max_output_tokens: null,
            builtin_tools: [{ name: "web_search" }],
          },
        },
      ],
      subagent_enabled: true,
      subagent_guidance: "Use for complex synthesis tasks.",
      execution_option_definitions: [],
    },
    {
      label: "lightweight",
      candidates: [
        {
          model_selection: lightweightSelection,
          settings: {
            context_window_tokens: null,
            max_output_tokens: null,
            builtin_tools: [],
          },
        },
      ],
      subagent_enabled: false,
      subagent_guidance: null,
      execution_option_definitions: [],
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
  runtime_profile_id: "workspace-runtime-profile-standard",
  runtime_profile_selection_version: 1,
  runtime_profile_available: true,
  runtime_profile_availability_reason_code: null,
  runtime_capability: "managed",
  runtime_capability_version: 1,
  runtime_profile_configuration_status: "configured",
  runtime_add_available: false,
  runtime_remove_available: true,
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

const emptyImageGenerationCatalogStates = new Map<
  string,
  ImageGenerationCatalogState
>();

function storyFormValues(formState: AgentFormState): AgentFormValues {
  if (formState.type === "EDIT") {
    const agent = formState.agent;
    return {
      name: agent.name,
      description: agent.description ?? "",
      selectable_model_options:
        selectableModelOptionFormValuesFromStoredOptions(
          agent.selectable_model_options,
        ),
      main_model_label: agent.main_model_label,
      lightweight_model_label: agent.lightweight_model_label,
      system_prompt: agent.system_prompt ?? "",
      runtime_profile_id: agent.runtime_profile_id,
      type: agent.type,
      enabled: agent.enabled,
      reasoning_effort: agent.model_parameters?.reasoning_effort ?? null,
      terminal_enabled: agent.terminal_enabled,
      memory_enabled: agent.memory_enabled,
      tool_search_enabled: agent.tool_search_enabled,
      max_turns: agent.max_turns,
      auto_archive_ttl_days: agent.auto_archive_ttl_days,
      subagent_max_subagents: agent.subagent_settings.max_subagents ?? 3,
      subagent_max_depth: agent.subagent_settings.max_depth ?? 1,
    };
  }
  return {
    name: "",
    description: "",
    selectable_model_options: [],
    main_model_label: null,
    lightweight_model_label: null,
    system_prompt: "",
    runtime_profile_id: null,
    type: "public",
    enabled: true,
    reasoning_effort: null,
    terminal_enabled: true,
    memory_enabled: true,
    tool_search_enabled: true,
    max_turns: null,
    auto_archive_ttl_days: 30,
    subagent_max_subagents: 3,
    subagent_max_depth: 1,
  };
}

function AgentFormStory(props: AgentFormProps): React.ReactElement {
  const t = useAgentFormTranslations();
  const form = useForm<AgentFormValues>({
    mode: "controlled",
    initialValues: storyFormValues(props.formState),
  });
  const selectedMainModelOption = findSelectableModelOptionByLabel(
    form.values.selectable_model_options,
    form.values.main_model_label,
  );
  const selectedModelEffortLevels = reasoningEffortLevels(
    selectedMainModelOption?.candidates[0]?.normalized_capabilities ?? null,
  );
  return (
    <AgentForm
      {...props}
      includeToolkitSection={false}
      t={t}
      form={form}
      hasSubmitAttempted={false}
      onSubmitAttempted={() => {}}
      selectedModelEffortLevels={selectedModelEffortLevels}
      imageGenerationCatalogStates={emptyImageGenerationCatalogStates}
      canSyncImageCatalog={false}
      onSyncImageCatalog={async () => {}}
    />
  );
}

const meta = {
  component: AgentFormStory,
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
    canManageIntegrations: true,
    onSyncCatalog: () => Promise.resolve(),
    onSubmit: noopSubmit,
    onAddAdmin: () => {},
    onRemoveAdmin: () => {},
    mode: "embedded",
  },
} satisfies Meta<typeof AgentFormStory>;

export default meta;

type Story = StoryObj<typeof meta>;

export const DefaultPreselected = {} satisfies Story;

export const CreateUsesWorkspaceDefault = {
  args: {
    formState: { type: "CREATE" },
    runtimeProfiles: [runtimeProfile],
  },
} satisfies Story;

export const RuntimeFreeCreateHidesTerminalSettings = {
  args: {
    formState: { type: "CREATE" },
    runtimeProfiles: [runtimeProfile],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.queryByText("Enable interactive Terminal"),
    ).not.toBeInTheDocument();
    await expect(canvas.getByText("Enable Memory")).toBeVisible();
    await expect(canvas.getByText("Enable Tool Search")).toBeVisible();

    await userEvent.click(canvas.getByLabelText("Runtime profile"));
    const documentBody = within(canvasElement.ownerDocument.body);
    await userEvent.click(await documentBody.findByText("Standard runtime"));
    await expect(canvas.getByText("Enable interactive Terminal")).toBeVisible();
  },
} satisfies Story;

export const RuntimeFreeEditHidesTerminalSettings = {
  args: {
    formState: {
      type: "EDIT",
      agent: {
        ...baseAgent,
        runtime_profile_id: null,
        runtime_profile_available: false,
        runtime_profile_availability_reason_code:
          "runtime_profile_unconfigured",
        runtime_capability: "none",
        runtime_profile_configuration_status: "not_applicable",
        runtime_remove_available: false,
        effective_terminal_enabled: false,
        terminal_denied_scope: "runtime",
      },
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.queryByText("Enable interactive Terminal"),
    ).not.toBeInTheDocument();
    await expect(
      canvas.queryByText("Current effective Terminal: unavailable"),
    ).not.toBeInTheDocument();
    await expect(canvas.getByText("Enable Memory")).toBeVisible();
    await expect(canvas.getByText("Enable Tool Search")).toBeVisible();
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
        effective_context_window_tokens: 128_000,
        effective_auto_compaction_threshold_tokens: 115_200,
        model_parameters: null,
      },
    },
  },
} satisfies Story;
