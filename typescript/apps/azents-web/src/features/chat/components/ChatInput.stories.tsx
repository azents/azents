import { rem } from "@mantine/core";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { pendingFiles } from "../story-fixtures";
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

function draftStorageKey(sessionId: string): string {
  return `azents.chat.inputDraft.story-agent-001.${sessionId}`;
}

function lastSelectedProfileStorageKey(sessionId: string): string {
  return `azents.chat.lastSelectedInferenceProfile.story-agent-001.${sessionId}`;
}

function storeMantineString(key: string, value: string): void {
  window.localStorage.setItem(key, JSON.stringify(value));
}

function seedLastSelectedProfile(
  sessionId: string,
  profile: RequestedInferenceProfile,
): void {
  storeMantineString(
    lastSelectedProfileStorageKey(sessionId),
    JSON.stringify(profile),
  );
}

function seedDraftProfile(
  sessionId: string,
  message: string,
  profile: RequestedInferenceProfile,
): void {
  storeMantineString(
    draftStorageKey(sessionId),
    JSON.stringify({
      message,
      action: null,
      inference_profile: profile,
    }),
  );
}

function clearComposerStorage(sessionId: string): void {
  window.localStorage.removeItem(draftStorageKey(sessionId));
  window.localStorage.removeItem(lastSelectedProfileStorageKey(sessionId));
}

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

export const SuccessfulSendPreservesProfile = {
  args: {
    ...baseArgs,
    sessionId: "story-session-preserve-profile",
  },
  decorators: [
    (Story) => {
      clearComposerStorage("story-session-preserve-profile");
      seedDraftProfile("story-session-preserve-profile", "Keep this profile", {
        model_target_label: "Fast",
        reasoning_effort: null,
      });
      return <Story />;
    },
  ],
  play: async ({ canvasElement }) => {
    const page = within(canvasElement.ownerDocument.body);
    await waitFor(async () => {
      await expect(page.getByRole("textbox")).toHaveValue("Keep this profile");
      await expect(
        page.getByRole("button", { name: /^Model$/ }),
      ).toHaveTextContent("Fast");
    });
    await userEvent.click(page.getByRole("button", { name: "Send" }));

    await waitFor(async () => {
      await expect(page.getByRole("textbox")).toHaveValue("");
    });
    await expect(
      page.getByRole("button", { name: /^Model$/ }),
    ).toHaveTextContent("Fast");
    await expect(
      window.localStorage.getItem(
        lastSelectedProfileStorageKey("story-session-preserve-profile"),
      ),
    ).toContain("Fast");
    await expect(
      window.localStorage.getItem(
        draftStorageKey("story-session-preserve-profile"),
      ),
    ).toBeNull();
  },
} satisfies Story;

export const RestoresRawLastSelectedEffort = {
  args: {
    ...baseArgs,
    sessionId: "story-session-restore-raw-profile",
  },
  decorators: [
    (Story) => {
      clearComposerStorage("story-session-restore-raw-profile");
      seedLastSelectedProfile("story-session-restore-raw-profile", {
        model_target_label: "Default",
        reasoning_effort: "future-ultra",
      });
      return <Story />;
    },
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(async () => {
      await expect(
        canvas.getByRole("button", { name: /^Model$/ }),
      ).toHaveTextContent("Default · future-ultra");
    });
  },
} satisfies Story;

export const DraftProfileOutranksLastSelected = {
  args: {
    ...baseArgs,
    sessionId: "story-session-draft-precedence",
  },
  decorators: [
    (Story) => {
      clearComposerStorage("story-session-draft-precedence");
      seedLastSelectedProfile("story-session-draft-precedence", {
        model_target_label: "Fast",
        reasoning_effort: null,
      });
      seedDraftProfile(
        "story-session-draft-precedence",
        "Preserve the unsent draft",
        {
          model_target_label: "Default",
          reasoning_effort: "future-draft-effort",
        },
      );
      return <Story />;
    },
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(async () => {
      await expect(canvas.getByRole("textbox")).toHaveValue(
        "Preserve the unsent draft",
      );
      await expect(
        canvas.getByRole("button", { name: /^Model$/ }),
      ).toHaveTextContent("Default · future-draft-effort");
    });
  },
} satisfies Story;

export const DeletedLastSelectedTargetFallsBack = {
  args: {
    ...baseArgs,
    sessionId: "story-session-deleted-profile",
  },
  decorators: [
    (Story) => {
      clearComposerStorage("story-session-deleted-profile");
      seedLastSelectedProfile("story-session-deleted-profile", {
        model_target_label: "Removed",
        reasoning_effort: "future-ultra",
      });
      seedDraftProfile(
        "story-session-deleted-profile",
        "Keep this draft after target deletion",
        {
          model_target_label: "Removed",
          reasoning_effort: "future-ultra",
        },
      );
      return <Story />;
    },
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(async () => {
      await expect(
        canvas.getByRole("button", { name: /^Model$/ }),
      ).toHaveTextContent("Default");
      await expect(canvas.getByRole("textbox")).toHaveValue(
        "Keep this draft after target deletion",
      );
      await expect(
        window.localStorage.getItem(
          lastSelectedProfileStorageKey("story-session-deleted-profile"),
        ),
      ).toBeNull();
      await expect(
        window.localStorage.getItem(
          draftStorageKey("story-session-deleted-profile"),
        ),
      ).not.toContain("Removed");
    });
    await expect(canvas.queryByText(/future-ultra/)).not.toBeInTheDocument();
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
