import { rem } from "@mantine/core";
import { useTranslations } from "next-intl";
import { expect, fn, userEvent, within } from "storybook/test";
import { renderStaticModelPicker } from "@/shared/model-options/components/model-option-editor-story-fixtures";
import { SelectableModelOptionsEditorContainer } from "@/shared/model-options/containers/SelectableModelOptionsEditorContainer";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { useWorkspaceModelSettingsCardForm } from "../containers/useWorkspaceModelSettingsCardForm";
import { WorkspaceModelSettingsCard } from "./WorkspaceModelSettingsCard";
import type { WorkspaceModelSettingsCardContainerProps } from "../containers/useWorkspaceModelSettingsCardForm";
import type {
  ImageGenerationCatalogState,
  ProviderIntegrationOption,
} from "@/shared/model-options/model-selection";
import type {
  AgentModelSelection,
  ImageGenerationModelCatalogResponse,
  WorkspaceModelSettingsResponse,
} from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

interface WorkspaceModelSettingsCardStoryProps extends WorkspaceModelSettingsCardContainerProps {
  imageCatalogStates: ReadonlyMap<string, ImageGenerationCatalogState>;
  onSyncImageCatalog: (integrationId: string) => Promise<void>;
}

const model: AgentModelSelection = {
  llm_provider_integration_id: "integration-workspace",
  provider: "openai",
  model_identifier: "workspace-model",
  model_display_name: "Workspace model",
  model_developer: "openai",
  normalized_capabilities: {
    reasoning: { supported: false, effort_levels: [] },
    built_in_tools: { supported: ["image_generation"] },
    context_window: {
      max_input_tokens: 128_000,
      max_output_tokens: 16_000,
    },
    modalities: { input: ["text"], output: ["text"] },
    tool_calling: { supported: true },
    parameters: {},
    compatibility: {},
  },
  model_snapshot: {},
  pricing: null,
};

const settings: WorkspaceModelSettingsResponse = {
  default_selectable_model_options: [
    {
      label: "default",
      candidates: [
        {
          model_selection: model,
          settings: {
            context_window_tokens: null,
            max_output_tokens: null,
            builtin_tools: [{ name: "image_generation", config: {} }],
          },
        },
      ],
      subagent_enabled: true,
      subagent_guidance: null,
    },
  ],
  default_main_model_label: "default",
  default_lightweight_model_label: "default",
};

const providerOptions: ProviderIntegrationOption[] = [
  {
    value: "integration-workspace",
    label: "Workspace OpenAI",
    provider: "openai",
    integration: {
      id: "integration-workspace",
      provider: "openai",
      name: "Workspace OpenAI",
      config: null,
      enabled: true,
      created_at: "2026-10-04T00:00:00Z",
      updated_at: "2026-10-04T00:00:00Z",
    },
    disabled: false,
  },
];

const catalog: ImageGenerationModelCatalogResponse = {
  default_available: true,
  explicit_selection_supported: true,
  catalog_id: "workspace-image-catalog",
  last_success_at: "2026-10-04T00:00:00Z",
  latest_sync: null,
  stale: false,
  usable: true,
  sync_available_at: null,
  automatic_retry_blocked: false,
  entries: [],
  total: 0,
};

function WorkspaceModelSettingsCardStory(
  props: WorkspaceModelSettingsCardStoryProps,
): React.ReactElement {
  const t = useTranslations("workspace.llmSettings.modelSelection");
  const { form, hasSubmitAttempted, submit } =
    useWorkspaceModelSettingsCardForm(props);
  return (
    <WorkspaceModelSettingsCard
      canManage={props.canManage}
      submitting={props.submitting}
      error={props.error}
      onSubmit={submit(props.imageCatalogStates)}
      modelOptionsEditor={
        <SelectableModelOptionsEditorContainer
          handle={props.handle}
          title={t("optionsTitle")}
          description={t("optionsDescription")}
          options={form.values.defaultSelectableModelOptions}
          mainModelLabel={form.values.defaultMainModelLabel}
          lightweightModelLabel={form.values.defaultLightweightModelLabel}
          providerOptions={props.providerOptions}
          canEdit={props.canManage}
          showValidationErrors={hasSubmitAttempted}
          onSyncCatalog={props.onSyncCatalog}
          imageGenerationCatalogStates={props.imageCatalogStates}
          canSyncImageCatalog={props.canManage}
          onSyncImageCatalog={props.onSyncImageCatalog}
          onChangeOptions={(options) =>
            form.setFieldValue("defaultSelectableModelOptions", options)
          }
          onChangeMainModelLabel={(label) =>
            form.setFieldValue("defaultMainModelLabel", label)
          }
          onChangeLightweightModelLabel={(label) =>
            form.setFieldValue("defaultLightweightModelLabel", label)
          }
          renderModelPicker={renderStaticModelPicker}
        />
      }
    />
  );
}

const meta = {
  component: WorkspaceModelSettingsCardStory,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(960)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    settings,
    handle: "engineering",
    providerOptions,
    canManage: true,
    submitting: false,
    error: null,
    onSyncCatalog: fn(async () => {}),
    onSyncImageCatalog: fn(async () => {}),
    onSubmit: fn(),
    imageCatalogStates: new Map([
      ["integration-workspace", { type: "LOADED", data: catalog }],
    ]),
  },
} satisfies Meta<typeof WorkspaceModelSettingsCardStory>;

export default meta;
type Story = StoryObj<typeof meta>;

export const EditableDefaults = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("textbox", { name: "Model label" }),
    ).toHaveValue("default");
    await userEvent.click(
      canvas.getByRole("button", { name: "Save default models" }),
    );
    await expect(args.onSubmit).toHaveBeenCalledTimes(1);
    await expect(args.onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        defaultMainModelLabel: "default",
        defaultLightweightModelLabel: "default",
      }),
    );
  },
} satisfies Story;

export const EmptyDefaults = {
  args: { settings: null },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Save default models" }),
    );
    await expect(args.onSubmit).not.toHaveBeenCalled();
    await expect(
      canvas.getByText("Add at least one model label."),
    ).toBeVisible();
  },
} satisfies Story;

export const ReadOnly = {
  args: { canManage: false },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.queryByRole("button", { name: "Save default models" }),
    ).not.toBeInTheDocument();
    await expect(
      canvas.getByRole("textbox", { name: "Model label" }),
    ).toBeDisabled();
  },
} satisfies Story;

export const Submitting = {
  args: { submitting: true },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("button", {
        name: "Save default models",
      }),
    ).toHaveAttribute("data-loading", "true");
  },
} satisfies Story;

export const SaveError = {
  args: { error: "Workspace model settings could not be saved." },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByText(
        "Workspace model settings could not be saved.",
      ),
    ).toBeVisible();
  },
} satisfies Story;

export const ImageCatalogLoading = {
  args: {
    imageCatalogStates: new Map([
      ["integration-workspace", { type: "LOADING" }],
    ]),
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(
      within(canvasElement).getByRole("button", { name: "Model settings" }),
    );
    await expect(
      within(canvasElement.ownerDocument.body).getByText(
        "Loading image models",
      ),
    ).toBeVisible();
  },
} satisfies Story;

export const ImageCatalogError = {
  args: {
    imageCatalogStates: new Map([
      ["integration-workspace", { type: "ERROR", message: "Unavailable." }],
    ]),
  },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(
      within(canvasElement).getByRole("button", { name: "Model settings" }),
    );
    const body = within(canvasElement.ownerDocument.body);
    await expect(
      body.getByText("Image models could not be loaded"),
    ).toBeVisible();
    await userEvent.click(
      body.getByRole("button", { name: "Sync image models" }),
    );
    await expect(args.onSyncImageCatalog).toHaveBeenCalledWith(
      "integration-workspace",
    );
  },
} satisfies Story;

export const MobileDefaults = {
  parameters: { testViewport: { width: 390, height: 844 } },
  play: async ({ canvasElement }) => {
    const document = canvasElement.ownerDocument;
    await expect(document.defaultView?.innerWidth).toBe(390);
    await expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(
      document.documentElement.clientWidth,
    );
    await expect(
      within(canvasElement).getByRole("button", {
        name: "Save default models",
      }),
    ).toBeVisible();
  },
} satisfies Story;
