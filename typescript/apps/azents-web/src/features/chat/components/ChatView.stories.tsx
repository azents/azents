import { Box, rem } from "@mantine/core";
import { expect, fn, userEvent, within } from "storybook/test";
import {
  completedToolCall,
  createChatMessage,
  failedToolCall,
  runningToolCall,
  storySessionId,
} from "../story-fixtures";
import { ChatView } from "./ChatView";
import type { ProjectDirectoryPickerState } from "../workspace/components/WorkspaceDirectoryPickerModal";
import type { WorkspacePanelContainerOutput } from "../workspace/containers/useWorkspacePanelContainer";
import type {
  WorkspacePanelState,
  WorkspaceProjectPanelState,
} from "../workspace/types";
import type { ChatEventResponse } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import type { ReactElement } from "react";

const noop = (): void => {};
const noopPath = (): void => {};
const closedProjectPickerState: ProjectDirectoryPickerState = {
  type: "CLOSED",
};
const sendMessage = (): Promise<boolean> => Promise.resolve(true);

function timelineEvent(
  id: string,
  kind: ChatEventResponse["kind"],
  payload: ChatEventResponse["payload"],
  createdAt = "2026-05-01T10:00:00.000Z",
): ChatEventResponse {
  return {
    id,
    session_id: storySessionId,
    kind,
    payload,
    model_order: 1,
    external_id: null,
    adapter: null,
    provider: null,
    model: null,
    native_format: null,
    schema_version: "1",
    created_at: createdAt,
  };
}

const readyWorkspaceState: WorkspacePanelState = {
  type: "SERVER",
  server: {
    runtime: {
      type: "RUNNING",
      runtime_id: "runtime-1",
      detail: null,
    },
    workspace: {
      type: "READY",
      manifest: {
        root: "/workspace/agent",
        cwd: "/workspace/agent/project",
        entries: [],
        git: null,
      },
    },
    actions: {
      start: null,
      stop: {
        type: "STOP_RUNTIME",
        method: "POST",
        path: "",
      },
      restart: null,
      reset: {
        type: "RESET_RUNTIME",
        method: "POST",
        path: "",
      },
    },
  },
  manifest: {
    root: "/workspace/agent",
    cwd: "/workspace/agent/project",
    entries: [
      {
        name: "src",
        path: "/workspace/agent/project/src",
        kind: "directory",
        size: null,
        mediaType: null,
        modifiedAt: null,
      },
      {
        name: "README.md",
        path: "/workspace/agent/project/README.md",
        kind: "file",
        size: 2048,
        mediaType: "text/markdown",
        modifiedAt: "2026-05-01T10:00:00.000Z",
      },
    ],
  },
  directory: {
    path: "/workspace/agent/project",
    entries: [
      {
        name: "src",
        path: "/workspace/agent/project/src",
        kind: "directory",
        size: null,
        mediaType: null,
        modifiedAt: null,
      },
      {
        name: "README.md",
        path: "/workspace/agent/project/README.md",
        kind: "file",
        size: 2048,
        mediaType: "text/markdown",
        modifiedAt: "2026-05-01T10:00:00.000Z",
      },
    ],
  },
  directoryEntriesByPath: {
    "/workspace/agent/project": [
      {
        name: "src",
        path: "/workspace/agent/project/src",
        kind: "directory",
        size: null,
        mediaType: null,
        modifiedAt: null,
      },
      {
        name: "README.md",
        path: "/workspace/agent/project/README.md",
        kind: "file",
        size: 2048,
        mediaType: "text/markdown",
        modifiedAt: "2026-05-01T10:00:00.000Z",
      },
    ],
  },
  fileState: { type: "IDLE" },
  workspaceView: "browser",
  selectedFilePath: null,
  selectedPaths: [],
  selectedEntry: null,
  inspectorState: { type: "IDLE" },
  isRefreshing: false,
  isMutating: false,
  isStarting: false,
  isStopping: false,
  isResetting: false,
};

const workspacePanel: WorkspacePanelContainerOutput = {
  state: readyWorkspaceState,
  projectState: {
    type: "READY",
    projects: [],
    registrationDialog: { type: "CLOSED" },
    isRegisteringProject: false,
    isCreatingWorktree: false,
    registerProjectError: null,
    pendingDeleteProjectId: null,
  } satisfies WorkspaceProjectPanelState,
  onStartRuntime: noop,
  onStopRuntime: noop,
  onRestartRuntime: noop,
  onResetRuntime: noop,
  onOpenDirectory: noop,
  onOpenFile: noop,
  onShowInfo: noop,
  onBackToBrowser: noop,
  onToggleSelectedPath: noop,
  onClearSelection: noop,
  onRefresh: noop,
  onCreateDirectory: noop,
  onRenamePath: noop,
  onMovePath: noop,
  onDeletePath: noop,
  onBulkMovePaths: noop,
  onBulkDeletePaths: noop,
  getDownloadHref: (path: string): string => `/download?path=${path}`,
  projectPickerState: closedProjectPickerState,
  isProjectPickerOpen: false,
  onOpenProjectPicker: noop,
  onCloseProjectPicker: noop,
  onOpenProjectPickerDirectory: noopPath,
  onSelectProjectPickerDirectory: noop,
  onRefreshProjectPicker: noop,
  onStartRuntimeForProjectPicker: noop,
  onCloseProjectRegistration: noop,
  onSetProjectRegistrationMode: noop,
  onSetProjectRegistrationStartingRef: noop,
  onSubmitProjectRegistration: noop,
  onDeleteProject: noop,
  onRemoveProjectEntry: noop,
  onDeleteWorktreeProjectEntry: noop,
  onSetBrowserMode: noop,
};

const meta = {
  component: ChatView,
  decorators: [
    (Story: () => ReactElement) => (
      <Box h="100dvh" pos="relative" style={{ zIndex: 300 }}>
        <Story />
      </Box>
    ),
  ],
} satisfies Meta<typeof ChatView>;

export default meta;

type Story = StoryObj<typeof meta>;

const baseArgs = {
  chatViewState: { type: "READY" },
  chatTimelineState: { type: "LATEST_FOLLOWING" },
  timelineEvents: [],
  messages: [
    createChatMessage({
      id: "user-question",
      role: "user",
      content: "Show me the generated files.",
    }),
    createChatMessage({
      id: "assistant-answer",
      content: "Use the workspace browser to inspect the result.",
    }),
  ],
  pendingInputBuffers: [],
  activeAgent: null,
  defaultInferenceProfile: {
    model_target_label: "default",
    reasoning_effort: null,
  },
  isResponsePending: false,
  isWritePending: false,
  liveRun: null,
  onSendInput: sendMessage,
  onDeletePendingInputBuffer: noop,
  onClearGoal: sendMessage,
  onUpdateGoal: sendMessage,
  onPauseGoal: sendMessage,
  onResumeGoal: sendMessage,
  hasMore: false,
  isLoadingMore: false,
  isLoadingNewer: false,
  onLoadMore: noop,
  onLoadNewer: noop,
  onResetToLatest: noop,
  onSubmitMessageEdit: sendMessage,
  onRetryFailedRun: sendMessage,
  wasCommandBlocked: false,
  isStopAvailable: false,
  isStopPending: false,
  onStopRequest: noop,
  inputActions: [],
  authorizationRequests: [],
  onAuthorizationComplete: noop,
  actionExecutions: [],
  workspacePanel,
  goal: { objective: null, status: null },
  todo: { items: [] },
} satisfies Story["args"];

const longConversationMessages = Array.from({ length: 28 }, (_, index) =>
  createChatMessage({
    id: `mobile-scroll-${index}`,
    role: index % 2 === 0 ? "user" : "assistant",
    content:
      index === 27
        ? "https://example.com/workspaces/azents/sessions/mobile-layout-regression/this-is-a-very-long-unbroken-token-that-must-not-push-the-chat-layout-outside-the-mobile-viewport"
        : index % 2 === 0
          ? `Please inspect file ${index + 1}.`
          : `I checked the workspace output for item ${index + 1}. The result includes enough detail to make this message wrap across multiple lines on a narrow mobile viewport.`,
  }),
);

export const WithWorkspaceBrowser = {
  args: baseArgs,
} satisfies Story;

export const MultiTurnToolActivity = {
  args: {
    ...baseArgs,
    timelineEvents: [
      timelineEvent("activity-user", "user_message", {
        content: "Inspect the implementation and run the checks.",
      }),
      timelineEvent("activity-tool-1", "client_tool_call", {
        call_id: completedToolCall.id,
        name: completedToolCall.name,
        arguments: completedToolCall.arguments,
      }),
      timelineEvent("activity-tool-1-result", "client_tool_result", {
        call_id: completedToolCall.id,
        status: "completed",
        output: completedToolCall.result,
      }),
      timelineEvent("activity-turn-1", "turn_marker", { usage: {} }),
      timelineEvent("activity-tool-2", "client_tool_call", {
        call_id: failedToolCall.id,
        name: failedToolCall.name,
        arguments: failedToolCall.arguments,
      }),
      timelineEvent("activity-tool-2-result", "client_tool_result", {
        call_id: failedToolCall.id,
        status: "failed",
        output: failedToolCall.result,
      }),
      timelineEvent("activity-turn-2", "turn_marker", { usage: {} }),
      timelineEvent("activity-tool-3", "client_tool_call", {
        call_id: runningToolCall.id,
        name: runningToolCall.name,
        arguments: runningToolCall.arguments,
      }),
    ],
    messages: [
      createChatMessage({
        id: "activity-user",
        role: "user",
        content: "Inspect the implementation and run the checks.",
      }),
      createChatMessage({
        id: "activity-tool-1",
        content: null,
        toolCalls: [completedToolCall],
      }),
      createChatMessage({
        id: "activity-turn-1",
        role: "turn_complete",
        content: null,
      }),
      createChatMessage({
        id: "activity-tool-2",
        content: null,
        toolCalls: [failedToolCall],
      }),
      createChatMessage({
        id: "activity-turn-2",
        role: "turn_complete",
        content: null,
      }),
      createChatMessage({
        id: "activity-tool-3",
        content: null,
        toolCalls: [runningToolCall],
      }),
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Failed 1")).toBeVisible();
    await expect(canvas.getByLabelText("Completed")).toBeVisible();
    await expect(canvas.queryByText(completedToolCall.name)).toBeNull();

    await userEvent.click(canvas.getByRole("button", { name: /Activity/ }));
    await expect(canvas.getByText(completedToolCall.name)).toBeVisible();
    await expect(canvas.getByText(failedToolCall.name)).toBeVisible();
    await expect(canvas.getByText(runningToolCall.name)).toBeVisible();
  },
} satisfies Story;

export const SpecializedDeliverableAndApproval = {
  args: {
    ...baseArgs,
    timelineEvents: [
      timelineEvent("specialized-user", "user_message", {
        content: "Inspect the project, generate a preview, then continue.",
      }),
      timelineEvent("specialized-read", "client_tool_call", {
        call_id: "specialized-read-call",
        name: "read",
        arguments: JSON.stringify({ path: "/workspace/agent/project/a.ts" }),
      }),
      timelineEvent("specialized-turn-1", "turn_marker", { usage: {} }),
      timelineEvent("specialized-image", "provider_tool_call", {
        call_id: "specialized-image-call",
        name: "image_generation",
        arguments: JSON.stringify({ prompt: "A calm activity timeline" }),
        status: "completed",
      }),
      timelineEvent("specialized-exec", "client_tool_call", {
        call_id: "specialized-exec-call",
        name: "exec_command",
        arguments: JSON.stringify({ command: "pnpm test" }),
      }),
    ],
    messages: [
      createChatMessage({
        id: "specialized-user",
        role: "user",
        content: "Inspect the project, generate a preview, then continue.",
      }),
      createChatMessage({
        id: "specialized-read",
        content: null,
        toolCalls: [
          {
            id: "specialized-read-call",
            callId: "specialized-read-call",
            name: "read",
            arguments: JSON.stringify({
              path: "/workspace/agent/project/a.ts",
            }),
            result: "file content",
            status: "completed",
          },
        ],
      }),
      createChatMessage({
        id: "specialized-turn-1",
        role: "turn_complete",
        content: null,
      }),
      createChatMessage({
        id: "specialized-image",
        content: null,
        providerToolCalls: [
          {
            id: "specialized-image-call",
            callId: "specialized-image-call",
            name: "image_generation",
            arguments: JSON.stringify({ prompt: "A calm activity timeline" }),
            output: "Generated one image.",
            status: "completed",
            attachments: [
              {
                attachmentId: "specialized-image-file",
                uri: "exchange://generated/specialized-image-file",
                mediaType: "image/png",
                name: "activity.png",
              },
              {
                attachmentId: "specialized-image-log",
                uri: "exchange://generated/specialized-image-log",
                mediaType: "text/plain",
                name: "generation.log",
              },
            ],
          },
        ],
      }),
      createChatMessage({
        id: "specialized-exec",
        content: null,
        toolCalls: [
          {
            id: "specialized-exec-call",
            callId: "specialized-exec-call",
            name: "exec_command",
            arguments: JSON.stringify({ command: "pnpm test" }),
            result: "58 tests passed",
            status: "completed",
          },
        ],
      }),
    ],
    authorizationRequests: [
      {
        toolkitId: "github",
        toolkitName: "GitHub",
        authorizationUrl: "https://example.com/oauth",
      },
    ],
    onAuthorizationComplete: fn(),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const activityButtons = canvas.getAllByRole("button", { name: /Activity/ });
    await expect(activityButtons).toHaveLength(2);
    await expect(
      canvas.getByRole("button", { name: "activity.png" }),
    ).toBeVisible();
    await expect(canvas.getByText("Review")).toBeVisible();

    const firstActivity = activityButtons.at(0);
    if (!firstActivity) {
      throw new Error("Expected the first activity disclosure");
    }
    await userEvent.click(firstActivity);
    await expect(canvas.getByText("read")).toBeVisible();
    await expect(canvas.getByText("generation.log")).toBeVisible();
  },
} satisfies Story;

export const LongMobileConversation = {
  args: {
    ...baseArgs,
    messages: longConversationMessages,
  },
} satisfies Story;

export const WithLiveRunRetry = {
  args: {
    ...baseArgs,
    isResponsePending: true,
    liveRun: {
      run_id: "run-retry-story",
      phase: "waiting_for_model",
      status: "running",
      inferenceProfile: {
        model_target_label: "default",
        model_display_name: "GPT 5.5",
        reasoning_effort: null,
      },
      modelCallStartedAt: new Date(Date.now() - 5_000).toISOString(),
      retry: {
        errorKind: "model_provider",
        status: "running",
        lastErrorMessage: "The provider returned a temporary rate limit.",
        failedAttemptCount: 1,
        maxRetries: 5,
        backoffSeconds: 10,
        nextRetryAt: new Date(Date.now() + 30_000).toISOString(),
        attempts: [
          {
            attemptNumber: 1,
            userMessage: "The provider returned a temporary rate limit.",
            errorType: "RateLimitError",
            source: "model_provider",
            failedAt: "2026-05-01T10:00:00.000Z",
            backoffSeconds: 10,
            nextRetryAt: "2026-05-01T10:00:10.000Z",
            retryability: "transient",
            failureCode: "provider_rate_limited",
            truncated: false,
          },
        ],
      },
    },
  },
} satisfies Story;

export const WithPreparingContext = {
  args: {
    ...baseArgs,
    isResponsePending: true,
    liveRun: {
      run_id: "run-preparing-context-story",
      phase: "compacting",
      status: "running",
      inferenceProfile: {
        model_target_label: "default",
        model_display_name: "GPT 5.5",
        reasoning_effort: null,
      },
      modelCallStartedAt: null,
      retry: null,
      operation: {
        kind: "preparing_context",
        operationId: "run-preparing-context-story:preparing-context",
        status: "running",
      },
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText("Summarizing previous conversation…"),
    ).toBeVisible();
  },
} satisfies Story;

export const StreamingModelWithPartialOutput = {
  args: {
    ...baseArgs,
    timelineEvents: [
      timelineEvent("streaming-user-input", "user_message", {
        content: "Explain the current model call state.",
      }),
      timelineEvent(
        "streaming-reasoning",
        "reasoning",
        { summary: "Inspect the current model call state." },
        new Date(Date.now() - 12_000).toISOString(),
      ),
      timelineEvent("streaming-assistant-output", "assistant_message", {
        content: "The model is still streaming this response",
      }),
    ],
    messages: [
      createChatMessage({
        id: "streaming-user-input",
        role: "user",
        content: "Explain the current model call state.",
      }),
      createChatMessage({
        id: "streaming-reasoning",
        content: null,
        reasoningSummary: "Inspect the current model call state.",
        metadata: { event_render_key: "reasoning:event:streaming-reasoning" },
      }),
      createChatMessage({
        id: "streaming-assistant-output",
        content: "The model is still streaming this response",
        status: "partial",
      }),
    ],
    isResponsePending: true,
    liveRun: {
      run_id: "run-streaming-story",
      phase: "streaming_model",
      status: "running",
      inferenceProfile: {
        model_target_label: "default",
        model_display_name: "GPT 5.5",
        reasoning_effort: null,
      },
      modelCallStartedAt: new Date(Date.now() - 12_000).toISOString(),
      retry: null,
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const activity = canvas.getByRole("button", { name: /Activity/ });
    const output = canvas.getByText(
      "The model is still streaming this response",
    );
    await expect(output).toBeVisible();
    await expect(
      canvas.getByRole("status", { name: "Agent is working" }),
    ).toBeVisible();
    await expect(
      canvas.getByText(/Waiting for model response \(\d+s\)/),
    ).toBeVisible();
    await expect(
      activity.compareDocumentPosition(output) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  },
} satisfies Story;

export const WithActionExecutionFailure = {
  args: {
    ...baseArgs,
    chatTimelineState: {
      type: "DETACHED_HISTORY_BROWSING",
      hasNewer: true,
      newestCursor: "action-result-cursor",
    },
    messages: [],
    actionExecutions: [
      {
        provenance: "durable",
        execution: {
          id: "action-execution-1",
          input_buffer_id: "buffer-action-1",
          action_type: "create_git_worktree",
          action: {
            type: "create_git_worktree",
            source_project_path: "/workspace/agent/project",
            starting_ref: "main",
          },
          status: "failed",
          owner_generation: 1,
          failure_summary:
            "Git worktree creation failed because the branch already exists.",
          started_at: "2026-05-19T00:00:00Z",
          completed_at: "2026-05-19T00:00:05Z",
          updated_at: "2026-05-19T00:00:05Z",
        },
        events: [
          {
            id: "action-event-1",
            action_execution_id: "action-execution-1",
            sequence: 1,
            kind: "command_started",
            step_key: "create_worktree",
            command_argv: ["git", "worktree", "add", "../project-feature"],
            content: null,
            created_at: "2026-05-19T00:00:00Z",
          },
          {
            id: "action-event-2",
            action_execution_id: "action-execution-1",
            sequence: 2,
            kind: "command_failed",
            step_key: "create_worktree",
            command_argv: null,
            content: "fatal: 'project-feature' is already checked out",
            created_at: "2026-05-19T00:00:05Z",
          },
        ],
      },
    ],
  },
} satisfies Story;

export const DetachedLatestResetIsKeyboardAccessible = {
  args: {
    ...baseArgs,
    chatTimelineState: {
      type: "DETACHED_HISTORY_BROWSING",
      hasNewer: true,
      newestCursor: "detached-latest-cursor",
    },
    onResetToLatest: fn(),
  },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    const latestButton = canvas.getByRole("button", { name: "New message" });
    await expect(latestButton).toBeVisible();
    latestButton.focus();
    await userEvent.keyboard("{Enter}");
    await expect(args.onResetToLatest).toHaveBeenCalledOnce();
  },
} satisfies Story;

export const WithPendingInputBuffer = {
  args: {
    ...baseArgs,
    pendingInputBuffers: [
      {
        id: "pending-buffer-1",
        sessionId: storySessionId,
        content: "Add this to the next model turn before answering.",
        attachments: [],
        metadata: { source: "web" },
        createdAt: "2026-05-19T00:00:00Z",
        status: "pending",
        requestedInferenceProfile: {
          model_target_label: "default",
          reasoning_effort: null,
        },
      },
    ],
  },
} satisfies Story;

export const LiveOperationRendersAbovePendingInput = {
  args: {
    ...baseArgs,
    pendingInputBuffers: [
      {
        id: "pending-buffer-after-operation",
        sessionId: storySessionId,
        content: "This input remains pending after the operation.",
        attachments: [],
        metadata: { source: "web" },
        createdAt: "2026-05-19T00:00:02Z",
        status: "pending",
        requestedInferenceProfile: {
          model_target_label: "default",
          reasoning_effort: null,
        },
      },
    ],
    actionExecutions: [
      {
        provenance: "live",
        execution: {
          id: "action-execution-live",
          input_buffer_id: "consumed-action-buffer",
          action_type: "create_git_worktree",
          action: {
            type: "create_git_worktree",
            source_project_path: "/workspace/agent/project",
            starting_ref: "main",
          },
          status: "running",
          owner_generation: 1,
          failure_summary: null,
          started_at: "2026-05-19T00:00:00Z",
          updated_at: "2026-05-19T00:00:01Z",
        },
        events: [],
      },
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const operation = canvas.getByText("Worktree action");
    const pendingInput = canvas.getByText(
      "This input remains pending after the operation.",
    );
    const position = operation.compareDocumentPosition(pendingInput);
    await expect(position & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  },
} satisfies Story;

export const DetachedHistoryHidesLiveOperation = {
  args: {
    ...baseArgs,
    chatTimelineState: {
      type: "DETACHED_HISTORY_BROWSING",
      hasNewer: true,
      newestCursor: "detached-operation-cursor",
    },
    actionExecutions: [
      {
        provenance: "live",
        execution: {
          id: "detached-action-execution-live",
          input_buffer_id: "detached-consumed-action-buffer",
          action_type: "create_git_worktree",
          action: {
            type: "create_git_worktree",
            source_project_path: "/workspace/agent/project",
            starting_ref: "main",
          },
          status: "running",
          owner_generation: 1,
          failure_summary: null,
          started_at: "2026-05-19T00:00:00Z",
          updated_at: "2026-05-19T00:00:01Z",
        },
        events: [],
      },
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByText("Worktree action")).toBeNull();
  },
} satisfies Story;

export const KeyboardShrunkMobileConversation = {
  args: {
    ...baseArgs,
    messages: longConversationMessages,
  },
  decorators: [
    (Story: () => ReactElement) => (
      <Box h={rem(520)}>
        <Story />
      </Box>
    ),
  ],
} satisfies Story;
