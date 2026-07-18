import { rem } from "@mantine/core";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";
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
  built_in_tools: { supported: ["web_search", "image_generation"] },
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
  context_window_tokens: 128_000,
  max_output_tokens: 8_000,
  builtin_tools: ["web_search", "image_generation"],
  subagent_enabled: true,
  subagent_guidance: "Use for complex synthesis tasks.",
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
  subagent_enabled: false,
  subagent_guidance: "Prefer for repository exploration.",
};

const options: SelectableModelOptionFormValue[] = [
  defaultOption,
  lightweightOption,
];

function SelectableModelOptionsEditorHarness(): React.ReactElement {
  const [currentOptions, setCurrentOptions] = useState([defaultOption]);
  const [mainLabel, setMainLabel] = useState<string | null>("default");
  const [lightweightLabel, setLightweightLabel] = useState<string | null>(
    "default",
  );
  return (
    <SelectableModelOptionsEditor
      handle="acme"
      title="Selectable models"
      description="Add a model and edit its label."
      options={currentOptions}
      mainModelLabel={mainLabel}
      lightweightModelLabel={lightweightLabel}
      providerOptions={providerOptions}
      canEdit
      onSyncCatalog={() => Promise.resolve()}
      onChangeOptions={setCurrentOptions}
      onChangeMainModelLabel={setMainLabel}
      onChangeLightweightModelLabel={setLightweightLabel}
    />
  );
}

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
    onSyncCatalog: () => Promise.resolve(),
    onChangeOptions: () => {},
    onChangeMainModelLabel: () => {},
    onChangeLightweightModelLabel: () => {},
  },
} satisfies Meta<typeof SelectableModelOptionsEditor>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Default = {} satisfies Story;

export const AddModelFocusesEmptyLabel = {
  render: () => <SelectableModelOptionsEditorHarness />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Add model" }));
    const labels = canvas.getAllByRole("textbox", { name: "Model label" });
    await expect(labels).toHaveLength(2);
    const newLabel = labels[1];
    if (newLabel == null) {
      throw new Error("New model label input was not rendered");
    }
    await expect(newLabel).toHaveValue("");
    await expect(newLabel).toHaveFocus();
  },
} satisfies Story;

export const SettingsModal = {
  args: {
    options: [defaultOption],
    lightweightModelLabel: "default",
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Model settings" }),
    );
    const body = within(document.body);
    await expect(
      body.getByRole("dialog", { name: "Settings for default" }),
    ).toBeVisible();
    await expect(body.getByLabelText("Web search")).toBeChecked();
    await expect(body.getByLabelText("Image generation")).toBeChecked();
  },
} satisfies Story;

export const SubagentPolicyInteraction = {
  render: () => <SelectableModelOptionsEditorHarness />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Model settings" }),
    );
    const body = within(document.body);
    const enabledSwitch = body.getByRole("checkbox", {
      name: "Available for explicit subagent selection",
    });
    const guidance = body.getByRole("textbox", {
      name: "Subagent selection guidance",
    });
    await expect(enabledSwitch).toBeChecked();
    await expect(guidance).toHaveValue("Use for complex synthesis tasks.");
    await userEvent.click(enabledSwitch);
    await expect(enabledSwitch).not.toBeChecked();
    await expect(guidance).toBeDisabled();
    await expect(guidance).toHaveValue("Use for complex synthesis tasks.");
  },
} satisfies Story;

export const ExplicitSubagentSelectionDisabled = {
  args: {
    options: [lightweightOption],
    mainModelLabel: "lightweight",
    lightweightModelLabel: "lightweight",
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Model settings" }),
    );
    const body = within(document.body);
    await expect(
      body.getByRole("checkbox", {
        name: "Available for explicit subagent selection",
      }),
    ).not.toBeChecked();
    await expect(
      body.getByRole("textbox", { name: "Subagent selection guidance" }),
    ).toBeDisabled();
  },
} satisfies Story;

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
        label: "",
        model_provider_integration_id: null,
        model_selection_value: null,
        model_display_name: null,
        model_identifier: null,
        normalized_capabilities: null,
        context_window_tokens: null,
        max_output_tokens: null,
        builtin_tools: [],
        subagent_enabled: true,
        subagent_guidance: null,
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
      },
    ],
    lightweightModelLabel: "default",
  },
} satisfies Story;
