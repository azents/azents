import { rem } from "@mantine/core";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { SelectableModelOptionsEditor } from "./SelectableModelOptionsEditor";
import type {
  ImageGenerationCatalogState,
  ProviderIntegrationOption,
  SelectableModelCandidateFormValue,
  SelectableModelOptionFormValue,
} from "../model-selection";
import type { ModelCapabilities } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const capabilities: ModelCapabilities = {
  reasoning: { supported: true, effort_levels: ["low", "medium", "high"] },
  built_in_tools: { supported: ["web_search", "image_generation"] },
  context_window: {
    default_input_tokens: 272_000,
    max_input_tokens: 872_000,
    max_output_tokens: null,
  },
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

const imageCatalogData = {
  default_available: true,
  explicit_selection_supported: true,
  catalog_id: "image-catalog-main",
  snapshot_id: "image-snapshot-main",
  snapshot_configuration_version: 1,
  current_configuration_version: 1,
  snapshot_created_at: "2026-09-10T00:00:00Z",
  latest_attempt: null,
  stale: false,
  generation_current: true,
  sync_available_at: null,
  automatic_retry_blocked: false,
  entries: [
    {
      id: "image-entry-flare",
      provider: "openai",
      provider_model_identifier: "gpt-image-2.5-flare",
      display_name: "GPT Image 2.5 Flare",
      description: "Recommended for fast, cost-balanced image generation.",
      recommendation_rank: 1,
      lifecycle_status: "active",
      visibility_status: "selectable",
      source_metadata: null,
      projection_metadata: null,
    },
    {
      id: "image-entry-sunburst",
      provider: "openai",
      provider_model_identifier: "gpt-image-2.5-sunburst",
      display_name: "GPT Image 2.5 Sunburst",
      description: "Highest-quality image generation choice.",
      recommendation_rank: 2,
      lifecycle_status: "active",
      visibility_status: "selectable",
      source_metadata: null,
      projection_metadata: null,
    },
  ],
  total: 2,
} satisfies Extract<ImageGenerationCatalogState, { type: "LOADED" }>["data"];

const loadedImageCatalogStates = new Map<string, ImageGenerationCatalogState>([
  ["integration-main", { type: "LOADED", data: imageCatalogData }],
]);

const defaultCandidate: SelectableModelCandidateFormValue = {
  id: "default-primary",
  model_provider_integration_id: "integration-main",
  model_selection_value: "integration-main:gpt-5.5",
  model_display_name: "GPT 5.5",
  model_identifier: "gpt-5.5",
  normalized_capabilities: capabilities,
  context_window_tokens: 128_000,
  max_output_tokens: 8_000,
  builtin_tools: ["web_search", "image_generation"],
  builtin_tool_configs: {
    web_search: {},
    image_generation: {},
  },
};

const defaultOption: SelectableModelOptionFormValue = {
  id: "default",
  label: "default",
  candidates: [defaultCandidate],
  subagent_enabled: true,
  subagent_guidance: "Use for complex synthesis tasks.",
};

const explicitImageCandidate: SelectableModelCandidateFormValue = {
  ...defaultCandidate,
  builtin_tool_configs: {
    ...defaultCandidate.builtin_tool_configs,
    image_generation: {
      model: "gpt-image-2.5-flare",
    },
  },
};

const explicitImageOption: SelectableModelOptionFormValue = {
  ...defaultOption,
  candidates: [explicitImageCandidate],
};

const lightweightCandidate: SelectableModelCandidateFormValue = {
  id: "lightweight-primary",
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
  builtin_tool_configs: {},
};

const lightweightOption: SelectableModelOptionFormValue = {
  id: "lightweight",
  label: "lightweight",
  candidates: [lightweightCandidate],
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
      imageGenerationCatalogStates={loadedImageCatalogStates}
      canSyncImageCatalog
      onSyncImageCatalog={() => Promise.resolve()}
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
    imageGenerationCatalogStates: loadedImageCatalogStates,
    canSyncImageCatalog: true,
    onSyncImageCatalog: () => Promise.resolve(),
    onChangeOptions: () => {},
    onChangeMainModelLabel: () => {},
    onChangeLightweightModelLabel: () => {},
  },
} satisfies Meta<typeof SelectableModelOptionsEditor>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Default = {} satisfies Story;

export const OrderedFallbackCandidates = {
  args: {
    options: [
      {
        ...defaultOption,
        candidates: [
          defaultCandidate,
          {
            ...lightweightCandidate,
            id: "default-fallback",
          },
        ],
      },
    ],
    lightweightModelLabel: "default",
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Primary")).toBeVisible();
    await expect(canvas.getByText("Fallback 1")).toBeVisible();
    await userEvent.click(
      canvas.getByRole("button", { name: "Copy Primary settings" }),
    );
    await expect(
      canvas.getByText(/Compatible Primary settings copied/),
    ).toBeVisible();
  },
} satisfies Story;

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
      body.getByRole("dialog", { name: "default · GPT 5.5 settings" }),
    ).toBeVisible();
    await expect(
      body.getByText(
        "No user cap uses the model default of 272,000 tokens. The catalog maximum is 872,000 tokens; higher values are saved but clamped at runtime.",
      ),
    ).toBeVisible();
    await expect(body.getByLabelText("Web search")).toBeChecked();
    await expect(body.getByLabelText("Image generation")).toBeChecked();
  },
} satisfies Story;

export const ImageGenerationModelSettings = {
  args: {
    options: [explicitImageOption],
    lightweightModelLabel: "default",
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Model settings" }),
    );
    const body = within(document.body);
    await expect(
      body.getByRole("combobox", { name: "Image model" }),
    ).toHaveValue("gpt-image-2.5-flare");
  },
} satisfies Story;

export const ImageGenerationModelMenu = {
  args: {
    options: [explicitImageOption],
    lightweightModelLabel: "default",
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Model settings" }),
    );
    const body = within(document.body);
    await userEvent.click(body.getByRole("combobox", { name: "Image model" }));
    await expect(body.getByText("GPT Image 2.5 Sunburst")).toBeVisible();
  },
} satisfies Story;

export const ImageGenerationModelUnavailable = {
  args: {
    options: [
      {
        ...defaultOption,
        candidates: [
          {
            ...defaultCandidate,
            builtin_tool_configs: {
              ...defaultCandidate.builtin_tool_configs,
              image_generation: { model: "gpt-image-2" },
            },
          },
        ],
      },
    ],
    lightweightModelLabel: "default",
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Model settings" }),
    );
    const body = within(document.body);
    await expect(body.getByText("Image model unavailable")).toBeVisible();
  },
} satisfies Story;

export const ImageGenerationCatalogLoading = {
  args: {
    options: [explicitImageOption],
    lightweightModelLabel: "default",
    imageGenerationCatalogStates: new Map([
      ["integration-main", { type: "LOADING" }],
    ]),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Model settings" }),
    );
    const body = within(document.body);
    await expect(body.getByText("Loading image models")).toBeVisible();
  },
} satisfies Story;

export const ImageGenerationLastSyncFailed = {
  args: {
    options: [explicitImageOption],
    lightweightModelLabel: "default",
    imageGenerationCatalogStates: new Map([
      [
        "integration-main",
        {
          type: "LOADED",
          data: {
            ...imageCatalogData,
            latest_attempt: {
              id: "image-attempt-failed",
              status: "failed",
              started_at: "2026-09-10T00:00:00Z",
              finished_at: "2026-09-10T00:00:01Z",
              failure_code: "provider_unavailable",
              failure_message: "Provider listing failed.",
              action_hint: "Try again.",
              fetched_count: 0,
              matched_count: 0,
              skipped_count: 0,
              hidden_count: 0,
            },
          },
        },
      ],
    ]),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Model settings" }),
    );
    const body = within(document.body);
    await expect(
      body.getByText("Latest image model sync failed"),
    ).toBeVisible();
    await expect(
      body.getByRole("combobox", { name: "Image model" }),
    ).toHaveValue("gpt-image-2.5-flare");
  },
} satisfies Story;

export const ImageGenerationDefaultOnly = {
  args: {
    options: [defaultOption],
    lightweightModelLabel: "default",
    imageGenerationCatalogStates: new Map([
      [
        "integration-main",
        {
          type: "UNSUPPORTED",
          data: {
            ...imageCatalogData,
            explicit_selection_supported: false,
            catalog_id: null,
            snapshot_id: null,
            snapshot_configuration_version: null,
            current_configuration_version: null,
            snapshot_created_at: null,
            entries: [],
            total: 0,
          },
        },
      ],
    ]),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Model settings" }),
    );
    const body = within(document.body);
    await expect(body.getByLabelText("Image generation")).toBeChecked();
    await expect(
      body.queryByRole("combobox", { name: "Image model" }),
    ).toBeNull();
    await expect(body.queryByText("Default model only")).toBeNull();
    await expect(body.queryByText("GPT Image 2.5 Flare")).toBeNull();
  },
} satisfies Story;

export const SubagentPolicyInteraction = {
  render: () => <SelectableModelOptionsEditorHarness />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Label settings" }),
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
      canvas.getByRole("button", { name: "Label settings" }),
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
        candidates: [
          {
            id: "option-1-primary",
            model_provider_integration_id: null,
            model_selection_value: null,
            model_display_name: null,
            model_identifier: null,
            normalized_capabilities: null,
            context_window_tokens: null,
            max_output_tokens: null,
            builtin_tools: [],
            builtin_tool_configs: {},
          },
        ],
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
        candidates: [
          {
            ...defaultCandidate,
            model_selection_value: null,
            model_display_name: null,
            model_identifier: null,
            normalized_capabilities: null,
          },
        ],
      },
    ],
    lightweightModelLabel: "default",
  },
} satisfies Story;
