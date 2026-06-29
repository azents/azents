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
    registrationRequests: [],
    isRegisteringProject: false,
    registerProjectError: null,
    pendingApproveRequestId: null,
    pendingRejectRequestId: null,
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
  onSelectProjectPickerDirectory: noopPath,
  onRefreshProjectPicker: noop,
  onStartRuntimeForProjectPicker: noop,
  onApproveRegistrationRequest: noop,
  onRejectRegistrationRequest: noop,
  onDeleteProject: noop,
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
  isResponsePending: false,
  isWritePending: false,
  isModelResponsePending: false,
  handle: "azents",
  onSendMessage: sendMessage,
  onSendCommand: sendMessage,
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
  isCompacting: false,
  wasCommandBlocked: false,
  isStopAvailable: false,
  isStopPending: false,
  onStopRequest: noop,
  slashCommands: [],
  authorizationRequests: [],
  onAuthorizationComplete: noop,
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
