import { rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { SelectableModelOptionsEditor } from "./SelectableModelOptionsEditor";
import type {
  ProviderIntegrationOption,
  SelectableModelOptionFormValue,
} from "../model-selection";
import type { ModelCapabilities } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const capabilities: ModelCapabilities = {
  reasoning: { supported: true, effort_levels: ["low", "medium", "high"] },
  built_in_tools: { supported: ["web_search"] },
  context_window: { max_input_tokens: 1_000_000, max_output_tokens: null },
  modalities: { input: ["text"], output: ["text"] },
  tool_calling: { supported: true },
  parameters: {},
  compatibility: {},
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

const defaultOption: SelectableModelOptionFormValue = {
  id: "default",
  label: "default",
  model_provider_integration_id: "integration-main",
  model_selection_value: "integration-main:gpt-5.5",
  model_display_name: "GPT 5.5",
  model_identifier: "gpt-5.5",
  normalized_capabilities: capabilities,
  context_window_tokens: null,
  max_output_tokens: null,
  builtin_tools: ["web_search"],
};

const lightweightOption: SelectableModelOptionFormValue = {
  id: "lightweight",
  label: "lightweight",
  model_provider_integration_id: "integration-main",
  model_selection_value: "integration-main:gpt-5.5-mini",
  model_display_name: "GPT 5.5 mini",
  model_identifier: "gpt-5.5-mini",
  normalized_capabilities: {
    ...capabilities,
    reasoning: { supported: false, effort_levels: [] },
    built_in_tools: { supported: [] },
  },
  context_window_tokens: null,
  max_output_tokens: null,
  builtin_tools: [],
};

const options: SelectableModelOptionFormValue[] = [
  defaultOption,
  lightweightOption,
];
const meta = {
  component: SelectableModelOptionsEditor,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(840)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    handle: "acme",
    title: "Selectable models",
    description:
      "Define an ordered model list. Main and lightweight selections reference labels from this list.",
    options,
    mainModelLabel: "default",
    lightweightModelLabel: "lightweight",
    providerOptions,
    canEdit: true,
    onSyncCatalog: () => {},
    onChangeOptions: () => {},
    onChangeMainModelLabel: () => {},
    onChangeLightweightModelLabel: () => {},
  },
} satisfies Meta<typeof SelectableModelOptionsEditor>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Default = {} satisfies Story;

export const DuplicateLabel = {
  args: {
    showValidationErrors: true,
    options: [
      defaultOption,
      {
        ...lightweightOption,
        label: "default",
      },
    ],
  },
} satisfies Story;

export const PendingNewModel = {
  args: {
    options: [
      defaultOption,
      lightweightOption,
      {
        id: "option-1",
        label: "option-1",
        model_provider_integration_id: null,
        model_selection_value: null,
        model_display_name: null,
        model_identifier: null,
        normalized_capabilities: null,
        context_window_tokens: null,
        max_output_tokens: null,
        builtin_tools: [],
      },
    ],
  },
} satisfies Story;

export const MissingModel = {
  args: {
    showValidationErrors: true,
    options: [
      {
        ...defaultOption,
        model_selection_value: null,
        model_display_name: null,
        model_identifier: null,
        normalized_capabilities: null,
        context_window_tokens: null,
        max_output_tokens: null,
        builtin_tools: [],
      },
    ],
    lightweightModelLabel: "default",
  },
} satisfies Story;
