import { Box, rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { createChatMessage } from "../story-fixtures";
import { ChatSessionView } from "./ChatSessionView";
import type { ChatSessionContainerOutput } from "../containers/useChatSessionContainer";
import type { ChatSessionViewContainerOutput } from "../containers/useChatSessionViewContainer";
import type { SubagentNavigationLinks } from "../subagentNavigation";
import type { WorkspacePanelContainerOutput } from "../workspace/containers/useWorkspacePanelContainer";
import type { ComposerSubscriptionUsagePresentationProps } from "./ComposerSubscriptionUsage";
import type { RuntimeTerminalContainerOutput } from "@/features/runtime-terminal/containers/useRuntimeTerminalContainer";
import type {
  AgentModelSelection,
  AgentResponse,
  AgentSessionResponse,
} from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const noop = (): void => {};
const sendMessage = (): Promise<boolean> => Promise.resolve(true);

const subscriptionModel: AgentModelSelection = {
  llm_provider_integration_id: "integration-openrouter",
  provider: "openrouter",
  model_identifier: "openai/gpt-5.1",
  model_display_name: "GPT 5.1",
  model_developer: "openai",
  model_family: "gpt-5",
  normalized_capabilities: {
    reasoning: { supported: true, effort_levels: ["low", "medium", "high"] },
    built_in_tools: { supported: ["web_search"] },
    context_window: { max_input_tokens: 128_000, max_output_tokens: null },
    modalities: { input: ["text"], output: ["text"] },
    tool_calling: { supported: true },
    parameters: {},
    compatibility: {},
  },
  model_snapshot: {},
  source_metadata: null,
  last_refreshed_at: "2026-08-20T10:00:00Z",
};

const agent: AgentResponse = {
  id: "agent_release",
  name: "Release Operator",
  description: "Coordinates release checklists and CI follow-up.",
  type: "private",
  enabled: true,
  avatar: null,
  model_selection: subscriptionModel,
  lightweight_model_selection: null,
  selectable_model_options: [
    {
      label: "default",
      model_selection: subscriptionModel,
      settings: {
        context_window_tokens: null,
        max_output_tokens: null,
        builtin_tools: [{ name: "web_search" }],
        subagent_enabled: true,
        subagent_guidance: "Use for release coordination.",
      },
    },
  ],
  main_model_label: "default",
  lightweight_model_label: "default",
  effective_context_window_tokens: 128_000,
  effective_auto_compaction_threshold_tokens: 115_000,
  model_parameters: { reasoning_effort: "medium" },
  system_prompt: "Coordinate release work for the workspace.",
  runtime_profile_id: "runtime_profile_standard",
  runtime_profile_selection_version: 1,
  runtime_profile_available: true,
  runtime_profile_availability_reason_code: null,
  runtime_capability: "managed",
  runtime_capability_version: 2,
  runtime_profile_configuration_status: "configured",
  runtime_add_available: false,
  runtime_remove_available: true,
  terminal_enabled: true,
  infrastructure_terminal_enabled: true,
  workspace_terminal_enabled: true,
  effective_terminal_enabled: true,
  terminal_denied_scope: null,
  memory_enabled: true,
  tool_search_enabled: false,
  max_turns: null,
  auto_archive_ttl_days: 30,
  subagent_settings: { max_subagents: 3, max_depth: 1 },
  created_at: "2026-08-20T09:00:00Z",
  updated_at: "2026-08-20T09:00:00Z",
};

const session: AgentSessionResponse = {
  id: "session_release",
  agent_id: agent.id,
  current_model_target_label: "default",
  current_reasoning_effort: "medium",
  title: "Release readiness review",
  title_source: "manual",
  status: "active",
  archived_at: null,
  purge_after: null,
  archive_retention_days_snapshot: null,
  primary_kind: null,
  product_mode: "team",
  run_state: "idle",
  pinned: false,
  unread_terminal_run_id: null,
  auto_archive_after: null,
  created_at: "2026-08-20T09:30:00Z",
  updated_at: "2026-08-20T10:00:00Z",
};

const subscriptionUsage: ComposerSubscriptionUsagePresentationProps = {
  resetKey: "integration-openrouter",
  onRefresh: async (): Promise<void> => {},
  state: {
    type: "UNAVAILABLE",
    reason: "temporarily_unavailable",
    retryable: true,
  },
};

const workspacePanel: WorkspacePanelContainerOutput = {
  state: { type: "LOADING" },
  metricsState: { type: "LOADING" },
  projectState: {
    type: "READY",
    projects: [],
    registrationDialog: { type: "CLOSED" },
    isRegisteringProject: false,
    isCreatingWorktree: false,
    registerProjectError: null,
    pendingDeleteProjectId: null,
  },
  runtimeSettingsHref: "/w/engineering/agents/agent_release/settings/runtime",
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
  projectPickerState: { type: "CLOSED" },
  isProjectPickerOpen: false,
  onOpenProjectPicker: noop,
  onCloseProjectPicker: noop,
  onOpenProjectPickerDirectory: noop,
  onSelectProjectPickerDirectory: noop,
  onRefreshProjectPicker: noop,
  onStartRuntimeForProjectPicker: noop,
  onRestartRuntimeForProjectPicker: noop,
  onCloseProjectRegistration: noop,
  onSetProjectRegistrationMode: noop,
  onSetProjectRegistrationStartingRef: noop,
  onSubmitProjectRegistration: noop,
  onDeleteProject: noop,
  onRemoveProjectEntry: noop,
  onDeleteWorktreeProjectEntry: noop,
  onSetBrowserMode: noop,
};

const chatSession: ChatSessionContainerOutput = {
  sessionId: session.id,
  chatViewState: { type: "READY" },
  chatTimelineState: { type: "LATEST_FOLLOWING" },
  messages: [
    createChatMessage({
      id: "message-user",
      role: "user",
      content: "Summarize the release blockers.",
      senderUserId: "user_ada",
    }),
    createChatMessage({
      id: "message-assistant",
      content: "The staging deployment is ready for approval.",
    }),
  ],
  timelineEvents: [],
  pendingInputBuffers: [],
  pendingMailboxEntries: [],
  connectionStatus: "connected",
  isResponsePending: false,
  isWritePending: false,
  isModelResponsePending: false,
  lastEventReceivedAt: "2026-08-20T10:00:00Z",
  liveRun: null,
  hasMore: false,
  isLoadingMore: false,
  isLoadingNewer: false,
  appliedInferenceProfile: null,
  defaultInferenceProfile: {
    model_target_label: "default",
    reasoning_effort: "medium",
  },
  onApplyInferenceProfile: sendMessage,
  onSendInput: sendMessage,
  onDeletePendingInputBuffer: noop,
  onClearGoal: sendMessage,
  onUpdateGoal: sendMessage,
  onPauseGoal: sendMessage,
  onResumeGoal: sendMessage,
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
  tokenUsage: null,
  goal: { objective: null, status: null },
  todo: { items: [] },
};

const subagentNavigation: SubagentNavigationLinks = {
  currentName: "CI investigator",
  currentPath: "/ci-investigator",
  parent: {
    session_agent_id: "session-agent-parent",
    agent_session_id: "session_parent",
    parent_session_agent_id: null,
    name: "Release coordinator",
    path: "/",
  },
  root: {
    session_agent_id: "session-agent-root",
    agent_session_id: "session_root",
    parent_session_agent_id: null,
    name: "Release coordinator",
    path: "/",
  },
};

const terminal: RuntimeTerminalContainerOutput = {
  projection: {
    state: "ready",
    reason_code: null,
    denied_scope: null,
    can_start_runtime: false,
    can_open_or_attach: true,
    terminal: null,
  },
  projectionLoading: false,
  presentation: "collapsed",
  connection: { type: "idle" },
  replayTruncated: false,
  hasNewOutput: false,
  ctrlActive: false,
  altActive: false,
  hostRef: noop,
  onExpand: noop,
  onFocus: noop,
  onCollapse: noop,
  onReturnToDock: noop,
  onTerminate: noop,
  onRetry: noop,
  onToggleCtrl: noop,
  onToggleAlt: noop,
  onSoftwareKey: noop,
  onFocusKeyboard: noop,
  dockHeight: 260,
  onDockResizeStart: noop,
  onDockResizeBy: noop,
};

const args: ChatSessionViewContainerOutput = {
  handle: "engineering",
  agent,
  sessionId: session.id,
  headerSession: session,
  chatSession,
  currentWorkspaceProfile: { userId: "user_ada", name: "Ada Lovelace" },
  subscriptionUsage,
  workspacePanel,
  subagentNavigation: null,
  terminal,
  terminalMobile: false,
  runtimeDrawerOpened: false,
  onSessionTitleChange: noop,
  onOpenRuntime: noop,
  onCloseRuntime: noop,
};

const meta = {
  component: ChatSessionView,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(1440)}>
        <Box h="100dvh">
          <Story />
        </Box>
      </StorybookCanvas>
    ),
  ],
  args,
} satisfies Meta<typeof ChatSessionView>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Conversation = {} satisfies Story;

export const LoadingHistory = {
  args: {
    chatSession: {
      ...chatSession,
      chatViewState: { type: "LOADING_HISTORY" },
      messages: [],
    },
    subscriptionUsage: null,
  },
} satisfies Story;

export const SubagentConversation = {
  args: {
    subagentNavigation,
  },
} satisfies Story;

export const PolicyDeniedTerminal = {
  args: {
    terminal: {
      ...terminal,
      projection: {
        state: "unavailable",
        reason_code: "terminal_disabled",
        denied_scope: "agent",
        can_start_runtime: false,
        can_open_or_attach: false,
        terminal: null,
      },
    },
  },
} satisfies Story;

export const RuntimeFreeTerminal = {
  args: {
    agent: {
      ...agent,
      runtime_capability: "none",
      runtime_profile_id: null,
      runtime_profile_available: false,
      runtime_profile_availability_reason_code: "runtime_profile_unconfigured",
      runtime_profile_configuration_status: "not_applicable",
      infrastructure_terminal_enabled: null,
      workspace_terminal_enabled: null,
      effective_terminal_enabled: false,
      terminal_denied_scope: "runtime",
    },
    terminal: {
      ...terminal,
      projection: {
        state: "absent",
        reason_code: "runtime_free_agent",
        denied_scope: "runtime",
        can_start_runtime: false,
        can_open_or_attach: false,
        terminal: null,
      },
    },
  },
} satisfies Story;
