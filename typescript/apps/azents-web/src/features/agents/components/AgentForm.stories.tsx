import { rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { AgentForm } from "./AgentForm";
import type {
  ModelSelectionOption,
  ProviderIntegrationOption,
} from "../model-selection";
import type { AgentFormValues } from "../schemas";
import type { AgentModelSelection, AgentResponse } from "@azents/public-client";
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
  effective_context_window_tokens: 1_000_000,
  effective_auto_compaction_threshold_tokens: 900_000,
  model_parameters: {
    reasoning_effort: "medium",
    builtin_tools: [{ name: "web_search" }],
  },
  system_prompt: "Help the workspace team with engineering tasks.",
  enabled: true,
  type: "public",
  runtime_provider_id: null,
  shell_enabled: true,
  memory_enabled: true,
  max_turns: null,
  avatar: null,
  created_at: "2026-05-14T00:00:00Z",
  updated_at: "2026-05-14T00:00:00Z",
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
    mutationState: { type: "IDLE", error: null, builtinToolErrors: null },
    adminListState: { type: "READY", admins: [] },
    catalogStates: new Map(),
    modelsLoading: false,
    members: [],
    providerOptions,
    modelOptions,
    onSyncCatalog: () => {},
    onSubmit: noopSubmit,
    onAddAdmin: () => {},
    onRemoveAdmin: () => {},
    mode: "embedded",
  },
} satisfies Meta<typeof AgentForm>;

export default meta;

type Story = StoryObj<typeof meta>;

export const DefaultPreselected = {} satisfies Story;

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
