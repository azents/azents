import { rem } from "@mantine/core";
import { expect, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { pendingFiles } from "../story-fixtures";
import { ChatInput } from "./ChatInput";
import type { UploadedFile } from "../hooks/useFileUpload";
import type { InputActionDefinition, TodoStateSnapshot } from "../types";
import type { AgentModelSelection, AgentResponse } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const reasoningModel: AgentModelSelection = {
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

const fullReasoningModel: AgentModelSelection = {
  ...reasoningModel,
  model_identifier: "gpt-5.6",
  model_display_name: "GPT 5.6",
  normalized_capabilities: {
    ...reasoningModel.normalized_capabilities,
    reasoning: {
      supported: true,
      effort_levels: [
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
      ],
    },
  },
};

const emptyEffortModel: AgentModelSelection = {
  ...reasoningModel,
  model_identifier: "reasoning-without-explicit-efforts",
  model_display_name: "Reasoning without explicit efforts",
  normalized_capabilities: {
    ...reasoningModel.normalized_capabilities,
    reasoning: { supported: true, effort_levels: [] },
  },
};

const noEffortModel: AgentModelSelection = {
  ...reasoningModel,
  model_identifier: "gpt-5.5-mini",
  model_display_name: "GPT 5.5 mini",
  normalized_capabilities: {
    ...reasoningModel.normalized_capabilities,
    reasoning: { supported: false, effort_levels: [] },
    built_in_tools: { supported: [] },
    context_window: { max_input_tokens: 128_000, max_output_tokens: null },
  },
};

const selectableModelOptions: AgentResponse["selectable_model_options"] = [
  { label: "Default", model_selection: reasoningModel },
  { label: "Fast", model_selection: noEffortModel },
];

const uploadAll = (): Promise<UploadedFile[]> => Promise.resolve([]);
const sendInput = (): Promise<boolean> => Promise.resolve(true);
const clearFiles = (): void => {};
const resetDoneFiles = (): void => {};
const addFiles: (files: FileList) => void = () => {};
const removeFile = (): void => {};
const afterSend = (): void => {};
const stopRequest = (): void => {};
const todo: TodoStateSnapshot = {
  items: [
    {
      content: "Polish the composer layout and verify the mobile model picker",
      status: "in_progress",
    },
    {
      content: "Monitor CI after pushing the fix",
      status: "pending",
    },
  ],
};

const inputActions: InputActionDefinition[] = [
  {
    id: "command:compact",
    keyword: "compact",
    label: "Compact",
    description:
      "Summarize previous conversation and compact the context window.",
    action: { type: "command", name: "compact" },
    category: "command",
    message: { policy: "optional", placeholder: "Send to run this command." },
    attachments: { policy: "unsupported" },
  },
  {
    id: "goal",
    keyword: "goal",
    label: "Goal",
    description: "Create a session goal.",
    action: { type: "goal" },
    category: "turn",
    message: {
      policy: "required",
      placeholder: "Describe the goal for this session.",
      max_length: 4000,
    },
    attachments: { policy: "unsupported" },
  },
];

const meta = {
  component: ChatInput,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(860)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof ChatInput>;

export default meta;

type Story = StoryObj<typeof meta>;

const baseArgs = {
  agentId: "story-agent-001",
  sessionId: "story-session-001",
  isMobile: false,
  selectableModelOptions,
  defaultInferenceProfile: {
    model_target_label: "Default",
    reasoning_effort: null,
  },
  isUploading: false,
  pendingFiles: [],
  goal: null,
  todo: null,
  uploadAll,
  onSendInput: sendInput,
  clearFiles,
  resetDoneFiles,
  addFiles,
  removeFile,
  onAfterSend: afterSend,
  wasCommandBlocked: false,
  isStopAvailable: false,
  isStopPending: false,
  onStopRequest: stopRequest,
  inputActions,
};

export const Ready = {
  args: baseArgs,
} satisfies Story;

export const WithPendingFiles = {
  args: {
    ...baseArgs,
    pendingFiles,
  },
} satisfies Story;

export const WaitingForResponse = {
  args: {
    ...baseArgs,
    isStopAvailable: true,
  },
} satisfies Story;

export const CommandBlocked = {
  args: {
    ...baseArgs,
    wasCommandBlocked: true,
  },
} satisfies Story;

export const WithTodo = {
  args: {
    ...baseArgs,
    todo,
  },
} satisfies Story;

export const InputActionSuggestions = {
  args: {
    ...baseArgs,
    initialInputValue: "/",
    todo,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText(
        "Polish the composer layout and verify the mobile model picker",
      ),
    ).toBeVisible();
    await expect(
      canvas.getByRole("button", { name: /compact/i }),
    ).toBeVisible();
  },
} satisfies Story;

export const SelectedActionChip = {
  args: {
    ...baseArgs,
    sessionId: "story-session-selected-action-chip",
    todo,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("textbox"), "/");
    await userEvent.click(canvas.getByRole("button", { name: /compact/i }));
    const chip = canvas.getByText("/compact").parentElement;
    await expect(chip).toBeVisible();
    await expect(chip).toHaveStyle({ borderStyle: "none" });
    await expect(
      canvas.getByText(
        "Polish the composer layout and verify the mobile model picker",
      ),
    ).toBeVisible();
  },
} satisfies Story;

export const LongModelLabel = {
  args: {
    ...baseArgs,
    selectableModelOptions: [
      {
        label: "Production reasoning model with a deliberately long label",
        model_selection: reasoningModel,
      },
      ...selectableModelOptions,
    ],
    defaultInferenceProfile: {
      model_target_label:
        "Production reasoning model with a deliberately long label",
      reasoning_effort: "high",
    },
  },
} satisfies Story;

export const TargetWithoutEffort = {
  args: {
    ...baseArgs,
    defaultInferenceProfile: {
      model_target_label: "Fast",
      reasoning_effort: null,
    },
  },
} satisfies Story;

export const EmptyEffortList = {
  args: {
    ...baseArgs,
    sessionId: "story-session-empty-effort-list",
    selectableModelOptions: [
      { label: "Default", model_selection: emptyEffortModel },
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.queryByLabelText("Reasoning effort"),
    ).not.toBeInTheDocument();
  },
} satisfies Story;

export const DesktopFullReasoningEffort = {
  args: {
    ...baseArgs,
    sessionId: "story-session-desktop-full-reasoning",
    selectableModelOptions: [
      { label: "Default", model_selection: fullReasoningModel },
      { label: "Fast", model_selection: noEffortModel },
    ],
  },
  play: async ({ canvasElement }) => {
    const page = within(canvasElement.ownerDocument.body);
    await userEvent.click(page.getByRole("button", { name: "Model" }));
    await userEvent.click(page.getByRole("button", { name: /Model Default/ }));
    await expect(page.getByText("gpt-5.6")).toBeVisible();
    await expect(page.getByText("gpt-5.5-mini")).toBeVisible();
    await userEvent.click(
      page.getByRole("button", { name: /Reasoning effort medium/ }),
    );
    await expect(
      page.getByRole("button", { name: /^medium$/ }),
    ).toHaveAttribute("aria-pressed", "true");
  },
} satisfies Story;

export const Mobile = {
  args: {
    ...baseArgs,
    isMobile: true,
    initialInputValue: "Review the current deployment status.",
  },
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(390)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Story;

export const MobileFullReasoningEffort = {
  args: {
    ...baseArgs,
    sessionId: "story-session-mobile-full-reasoning",
    isMobile: true,
    selectableModelOptions: [
      { label: "Default", model_selection: fullReasoningModel },
      { label: "Fast", model_selection: noEffortModel },
    ],
  },
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(390)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  play: async ({ canvasElement }) => {
    const page = within(canvasElement.ownerDocument.body);
    await userEvent.click(page.getByRole("button", { name: "Model" }));
    await expect(page.getByText("gpt-5.6")).toBeVisible();
    await expect(page.getByText("gpt-5.5-mini")).toBeVisible();
    const effortSelect = page.getByLabelText("Reasoning effort");
    await expect(effortSelect).toBeVisible();
    await expect(effortSelect).toHaveValue("medium");
    await userEvent.click(effortSelect);
    await expect(page.getByRole("option", { name: "max" })).toBeVisible();
    await expect(
      page.queryByRole("option", { name: "Default" }),
    ).not.toBeInTheDocument();
  },
} satisfies Story;

export const EditingMessage = {
  args: {
    ...baseArgs,
    editingMessageId: "user-message-001",
    editingInitialValue: "Please summarize only the failed checks.",
    editingInferenceProfile: {
      model_target_label: "Default",
      reasoning_effort: "high",
    },
  },
} satisfies Story;

export const EditingWithUnsupportedEffort = {
  args: {
    ...baseArgs,
    editingMessageId: "user-message-unsupported-effort",
    editingInitialValue: "Re-run this with the fast model.",
    editingInferenceProfile: {
      model_target_label: "Fast",
      reasoning_effort: "high",
    },
  },
} satisfies Story;

export const EditingBlockedByRun = {
  args: {
    ...baseArgs,
    editingMessageId: "user-message-001",
    editingInitialValue: "Please summarize only the failed checks.",
    editingInferenceProfile: {
      model_target_label: "Fast",
      reasoning_effort: null,
    },
    editSendDisabled: true,
  },
} satisfies Story;
