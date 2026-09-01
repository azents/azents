import { rem } from "@mantine/core";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { longUploadErrorFile, pendingFiles } from "../story-fixtures";
import { ChatInput } from "./ChatInput";
import type { UploadedFile } from "../hooks/useFileUpload";
import type { InputActionDefinition, TodoStateSnapshot } from "../types";
import type {
  AgentModelSelection,
  AgentResponse,
  RequestedInferenceProfile,
  SelectableModelSettings,
} from "@azents/public-client";
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

function settingsForModel(model: AgentModelSelection): SelectableModelSettings {
  return {
    context_window_tokens: null,
    max_output_tokens: null,
    builtin_tools: (
      model.normalized_capabilities.built_in_tools?.supported ?? []
    ).map((name) => ({ name })),
    subagent_enabled: true,
    subagent_guidance: null,
  };
}

const selectableModelOptions: AgentResponse["selectable_model_options"] = [
  {
    label: "Default",
    model_selection: reasoningModel,
    settings: settingsForModel(reasoningModel),
  },
  {
    label: "Fast",
    model_selection: noEffortModel,
    settings: settingsForModel(noEffortModel),
  },
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
  {
    id: "cleanup_orphan_git_worktrees",
    keyword: "cleanup-worktrees",
    label: "Clean up worktrees",
    description:
      "Remove managed Git worktrees not connected to an active session.",
    action: { type: "cleanup_orphan_git_worktrees" },
    category: "turn",
    message: {
      policy: "optional",
      placeholder: "Optional cleanup note.",
      max_length: null,
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
  contextUsageEnabled: true,
  contextUsage: {
    runId: "run-context-usage",
    inferenceProfile: {
      model_target_label: "Default",
      model_display_name: "GPT 5.5",
      reasoning_effort: "high",
    },
    effectiveContextWindowTokens: 270_000,
    effectiveAutoCompactionThresholdTokens: 243_000,
    promptTokens: 47_043,
    completionTokens: 1_200,
    totalTokens: 48_243,
    cachedTokens: 12_000,
    cacheCreationTokens: 2_400,
    reasoningTokens: 800,
  },
  isUploading: false,
  pendingFiles: [],
  goal: null,
  todo: null,
  uploadAll,
  onSendInput: sendInput,
  onApplyInferenceProfile: () => Promise.resolve(true),
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

const modelChangeReviewMessage =
  "Summarize the latest deployment status and highlight any risks.";
const appliedDefaultProfile: RequestedInferenceProfile = {
  model_target_label: "Default",
  reasoning_effort: null,
};

export const ModelChangeState1UnchangedWithText = {
  args: {
    ...baseArgs,
    sessionId: "story-session-model-change-state-1",
    initialInputValue: modelChangeReviewMessage,
    appliedInferenceProfile: appliedDefaultProfile,
  },
} satisfies Story;

export const ModelChangeState2PendingWithText = {
  args: {
    ...baseArgs,
    sessionId: "story-session-model-change-state-2",
    initialInputValue: modelChangeReviewMessage,
    appliedInferenceProfile: appliedDefaultProfile,
  },
  play: async ({ canvasElement }) => {
    const page = within(canvasElement.ownerDocument.body);
    await userEvent.click(page.getByRole("button", { name: "Model" }));
    await userEvent.click(
      page.getByRole("button", { name: /Fast gpt-5\.5-mini/ }),
    );
    await expect(page.getByRole("button", { name: "Model" })).toHaveTextContent(
      "Fast",
    );

    await userEvent.click(page.getByRole("button", { name: "Model" }));
    await userEvent.click(
      page.getByRole("button", { name: /Default gpt-5\.5/ }),
    );
    await expect(page.getByRole("button", { name: "Model" })).toHaveTextContent(
      "Default",
    );
  },
} satisfies Story;

export const ModelChangeState3PendingWithoutText = {
  args: {
    ...baseArgs,
    sessionId: "story-session-model-change-state-3",
    initialInputValue: "",
    appliedInferenceProfile: appliedDefaultProfile,
  },
} satisfies Story;

export const ModelChangeState4PendingWithStop = {
  args: {
    ...baseArgs,
    sessionId: "story-session-model-change-state-4",
    initialInputValue: "",
    appliedInferenceProfile: appliedDefaultProfile,
    isStopAvailable: true,
  },
  play: async ({ canvasElement }) => {
    const page = within(canvasElement.ownerDocument.body);
    await userEvent.click(page.getByRole("button", { name: "Model" }));
    await userEvent.click(
      page.getByRole("button", { name: /Fast gpt-5\.5-mini/ }),
    );
    await expect(
      page.getByRole("button", { name: "Apply model change" }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Stop run" })).toBeVisible();
  },
} satisfies Story;

export const DeletedAppliedModelLabelIsPreserved = {
  args: {
    ...baseArgs,
    sessionId: "story-session-deleted-applied-model",
    onSendInput: fn(),
    appliedInferenceProfile: {
      model_target_label: "Retired",
      reasoning_effort: "high",
    },
  },
  play: async ({ canvasElement, args }) => {
    const page = within(canvasElement.ownerDocument.body);
    const input = page.getByRole("textbox");
    await expect(page.getByRole("button", { name: "Model" })).toHaveTextContent(
      "Retired",
    );
    await userEvent.type(input, "Use the retained Session model");
    await userEvent.click(page.getByRole("button", { name: "Send" }));
    await expect(args.onSendInput).toHaveBeenCalledWith(
      "Use the retained Session model",
      null,
      {
        model_target_label: "Retired",
        reasoning_effort: "high",
      },
    );
  },
} satisfies Story;

export const WithPendingFiles = {
  args: {
    ...baseArgs,
    pendingFiles,
  },
} satisfies Story;

export const WithLongUploadError = {
  args: {
    ...baseArgs,
    pendingFiles: [longUploadErrorFile],
  },
} satisfies Story;

export const MobileWithLongUploadError = {
  args: {
    ...baseArgs,
    isMobile: true,
    pendingFiles: [longUploadErrorFile],
  },
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(390)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
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
    await userEvent.click(canvas.getByRole("textbox"));
    await expect(
      canvas.getByText(
        "Polish the composer layout and verify the mobile model picker",
      ),
    ).toBeVisible();
    await expect(
      canvas.getByRole("option", { name: /compact/i }),
    ).toBeVisible();

    const suggestions = canvas
      .getByText("Slash commands")
      .closest(".mantine-Paper-root");
    const todoPreview = canvas
      .getByText(
        "Polish the composer layout and verify the mobile model picker",
      )
      .closest("button");
    if (suggestions === null || todoPreview === null) {
      throw new Error("Expected slash suggestions and Todo preview surfaces");
    }
    await expect(
      suggestions.getBoundingClientRect().bottom,
    ).toBeLessThanOrEqual(todoPreview.getBoundingClientRect().top);
  },
} satisfies Story;

export const InputActionSuggestionsCloseOnBlur = {
  args: {
    ...baseArgs,
    initialInputValue: "/",
    sessionId: "story-session-suggestions-close-on-blur",
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const input = canvas.getByRole("textbox");
    await userEvent.click(input);
    await expect(canvas.getByRole("listbox")).toBeVisible();
    await userEvent.tab();
    await expect(canvas.queryByRole("listbox")).not.toBeInTheDocument();
    await userEvent.click(input);
    await expect(canvas.getByRole("listbox")).toBeVisible();
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
    await userEvent.click(canvas.getByRole("option", { name: /compact/i }));
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

export const SelectedActionPreservesMessage = {
  args: {
    ...baseArgs,
    initialInputValue: "/co Hello, Azents!",
    sessionId: "story-session-selected-action-preserves-message",
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const input = canvas.getByRole("textbox");
    await userEvent.click(input);
    await expect(
      canvas.getByRole("option", { name: /compact/i }),
    ).toBeVisible();
    await userEvent.click(canvas.getByRole("option", { name: /compact/i }));
    await expect(canvas.getByText("/compact")).toBeVisible();
    await expect(input).toHaveValue("Hello, Azents!");
  },
} satisfies Story;

export const CleanupActionSelection = {
  args: {
    ...baseArgs,
    sessionId: "story-session-cleanup-action-selection",
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("textbox"), "/cleanup");
    await userEvent.click(
      canvas.getByRole("option", { name: /clean up worktrees/i }),
    );
    await expect(canvas.getByText("/cleanup-worktrees")).toBeVisible();
    await expect(canvas.getByRole("textbox")).toHaveValue("");
  },
} satisfies Story;

export const KeyboardInputActionSelection = {
  args: {
    ...baseArgs,
    sessionId: "story-session-keyboard-action-selection",
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const input = canvas.getByRole("textbox");
    await userEvent.click(input);
    await userEvent.keyboard("/");
    await expect(canvas.getByRole("listbox")).toBeVisible();
    await expect(
      canvas.getByRole("option", { name: /clean up worktrees/i }),
    ).toHaveAttribute("aria-selected", "true");

    await userEvent.keyboard("{ArrowDown}");
    await expect(
      canvas.getByRole("option", { name: /compact/i }),
    ).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{ArrowUp}");
    await expect(
      canvas.getByRole("option", { name: /clean up worktrees/i }),
    ).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{ArrowDown}");
    await userEvent.keyboard("{Enter}");
    await expect(canvas.getByText("/compact")).toBeVisible();
    await expect(input).toHaveValue("");

    await userEvent.keyboard("/cleanup");
    await expect(canvas.getByRole("listbox")).toBeVisible();
    await userEvent.keyboard("{Escape}");
    await expect(canvas.queryByRole("listbox")).not.toBeInTheDocument();
    await expect(input).toHaveValue("/cleanup");
    await expect(input).toHaveAttribute("aria-expanded", "false");
  },
} satisfies Story;

export const LongModelLabel = {
  args: {
    ...baseArgs,
    selectableModelOptions: [
      {
        label: "Production reasoning model with a deliberately long label",
        model_selection: reasoningModel,
        settings: settingsForModel(reasoningModel),
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
      {
        label: "Default",
        model_selection: emptyEffortModel,
        settings: settingsForModel(emptyEffortModel),
      },
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
      {
        label: "Default",
        model_selection: fullReasoningModel,
        settings: settingsForModel(fullReasoningModel),
      },
      {
        label: "Fast",
        model_selection: noEffortModel,
        settings: settingsForModel(noEffortModel),
      },
    ],
  },
  play: async ({ canvasElement }) => {
    const page = within(canvasElement.ownerDocument.body);
    await userEvent.click(page.getByRole("button", { name: /^Model$/ }));
    await expect(
      page.getByRole("region", { name: "Token usage" }),
    ).toBeVisible();
    await expect(page.getByText("Effective context window")).toBeVisible();
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

export const DesktopProfileKeyboardNavigation = {
  args: {
    ...baseArgs,
    sessionId: "story-session-desktop-profile-keyboard-navigation",
    selectableModelOptions: [
      {
        label: "Default",
        model_selection: fullReasoningModel,
        settings: settingsForModel(fullReasoningModel),
      },
      {
        label: "Fast",
        model_selection: noEffortModel,
        settings: settingsForModel(noEffortModel),
      },
    ],
  },
  play: async ({ canvasElement }) => {
    const page = within(canvasElement.ownerDocument.body);
    const trigger = page.getByRole("button", { name: /^Model$/ });
    trigger.focus();

    await userEvent.keyboard("{ArrowDown}");
    const modelSection = await waitFor(() =>
      page.getByRole("button", { name: /Model Default/ }),
    );
    await waitFor(() => expect(modelSection).toHaveFocus());
    await expect(
      page
        .getByRole("region", { name: "Token usage" })
        .compareDocumentPosition(modelSection),
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);

    await userEvent.keyboard("{ArrowRight}");
    const defaultModel = await waitFor(() =>
      page.getByRole("button", { name: /Default gpt-5\.6/ }),
    );
    await waitFor(() => expect(defaultModel).toHaveFocus());
    await userEvent.keyboard("{ArrowDown}");
    const fastModel = page.getByRole("button", {
      name: /Fast gpt-5\.5-mini/,
    });
    await waitFor(() => expect(fastModel).toHaveFocus());
    await userEvent.keyboard("{ArrowUp}");
    await waitFor(() => expect(defaultModel).toHaveFocus());
    await userEvent.keyboard("{Enter}");
    await expect(defaultModel).toHaveAttribute("aria-pressed", "true");

    await userEvent.keyboard("{ArrowLeft}");
    await waitFor(() => expect(modelSection).toHaveFocus());
    await userEvent.keyboard("{ArrowDown}");
    const effortSection = await waitFor(() =>
      page.getByRole("button", { name: /Reasoning effort medium/ }),
    );
    await waitFor(() => expect(effortSection).toHaveFocus());

    await userEvent.keyboard("{ArrowRight}");
    const mediumEffort = await waitFor(() =>
      page.getByRole("button", { name: "medium" }),
    );
    await waitFor(() => expect(mediumEffort).toHaveFocus());
    await userEvent.keyboard("{ArrowDown}");
    const highEffort = page.getByRole("button", { name: "high" });
    await waitFor(() => expect(highEffort).toHaveFocus());
    await userEvent.keyboard("{Enter}");
    await expect(highEffort).toHaveAttribute("aria-pressed", "true");

    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(effortSection).toHaveFocus());
    await userEvent.keyboard("{Escape}");
    await waitFor(() =>
      expect(page.queryByRole("dialog", { name: "Model" })).toBeNull(),
    );
    await waitFor(() => expect(trigger).toHaveFocus());
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

export const MobileContextUsageAutoScroll = {
  args: {
    ...baseArgs,
    sessionId: "story-session-mobile-context-usage",
    isMobile: true,
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
    const scrollIntoView = spyOn(
      Element.prototype,
      "scrollIntoView",
    ).mockImplementation(() => null);
    try {
      await userEvent.click(
        page.getByRole("button", { name: "Open token usage details" }),
      );
      await waitFor(() =>
        expect(page.getByRole("dialog", { name: "Model" })).toBeVisible(),
      );
      await waitFor(() =>
        expect(page.getByRole("region", { name: "Token usage" })).toBeVisible(),
      );
      await waitFor(() =>
        expect(scrollIntoView).toHaveBeenCalledWith({
          behavior: "smooth",
          block: "start",
        }),
      );
    } finally {
      scrollIntoView.mockRestore();
    }
  },
} satisfies Story;

export const SubagentContextUsage = {
  args: {
    ...baseArgs,
    sessionId: "story-session-subagent-context-usage",
    isMobile: true,
    inputDisabled: true,
    disabledPlaceholder: "Messages can only be sent from the root agent.",
    inferenceProfileSelectionEnabled: false,
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
    const scrollIntoView = spyOn(
      Element.prototype,
      "scrollIntoView",
    ).mockImplementation(() => null);
    try {
      await expect(
        page.queryByRole("button", { name: /^Model$/ }),
      ).not.toBeInTheDocument();
      await userEvent.click(
        page.getByRole("button", { name: "Open token usage details" }),
      );
      await waitFor(() =>
        expect(page.getByRole("dialog", { name: "Token usage" })).toBeVisible(),
      );
      await expect(
        page.queryByText("Reasoning effort"),
      ).not.toBeInTheDocument();
      await expect(
        page.getByRole("region", { name: "Token usage" }),
      ).toBeVisible();
      await waitFor(() =>
        expect(scrollIntoView).toHaveBeenCalledWith({
          behavior: "smooth",
          block: "start",
        }),
      );
    } finally {
      scrollIntoView.mockRestore();
    }
  },
} satisfies Story;

export const MobileWithPendingFiles = {
  args: {
    ...baseArgs,
    isMobile: true,
    pendingFiles,
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
      {
        label: "Default",
        model_selection: fullReasoningModel,
        settings: settingsForModel(fullReasoningModel),
      },
      {
        label: "Fast",
        model_selection: noEffortModel,
        settings: settingsForModel(noEffortModel),
      },
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
    await userEvent.click(page.getByRole("button", { name: /^Model$/ }));
    await waitFor(() => expect(page.getByText("gpt-5.6")).toBeVisible());
    await expect(page.getByText("gpt-5.5-mini")).toBeVisible();
    await expect(
      page
        .getByText("gpt-5.6")
        .compareDocumentPosition(
          page.getByRole("region", { name: "Token usage" }),
        ),
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    await expect(page.getByText("Reasoning effort")).toBeVisible();
    await expect(page.getByRole("button", { name: "medium" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expect(page.getByRole("button", { name: "max" })).toBeVisible();
    await userEvent.click(page.getByRole("button", { name: "max" }));
    await expect(page.getByRole("button", { name: "max" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expect(page.queryByRole("option")).not.toBeInTheDocument();
    await expect(page.getByRole("button", { name: "Done" })).toBeVisible();
    await expect(
      page.queryByRole("button", { name: "Close drawer" }),
    ).not.toBeInTheDocument();
    await userEvent.click(page.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(page.getByRole("dialog")).not.toBeVisible());
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
