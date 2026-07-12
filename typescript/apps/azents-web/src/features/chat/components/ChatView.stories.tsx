import { Box, rem } from "@mantine/core";
import { createChatMessage, storySessionId } from "../story-fixtures";
import { ChatView } from "./ChatView";
import type { ProjectDirectoryPickerState } from "../workspace/components/WorkspaceDirectoryPickerModal";
import type { WorkspacePanelContainerOutput } from "../workspace/containers/useWorkspacePanelContainer";
import type {
  WorkspacePanelState,
  WorkspaceProjectPanelState,
} from "../workspace/types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import type { ReactElement } from "react";

const noop = (): void => {};
const noopPath = (): void => {};
const closedProjectPickerState: ProjectDirectoryPickerState = {
  type: "CLOSED",
};
const sendMessage = (): Promise<boolean> => Promise.resolve(true);

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
  isModelResponsePending: false,
  liveRun: null,
  handle: "azents",
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
  isCompacting: false,
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
      retry: {
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
    isModelResponsePending: true,
  },
} satisfies Story;

export const WithActionExecutionFailure = {
  args: {
    ...baseArgs,
    messages: [],
    actionExecutions: [
      {
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
